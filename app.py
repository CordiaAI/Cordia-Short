from __future__ import annotations

import json
import os
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from flask import Flask, jsonify, redirect, request, send_from_directory

from cordia.agent import Agent, AgentBusy, AgentUnavailable, InvalidAgentAction
from cordia.agent_runs import AgentRuns
from cordia.connector_runtime import ConnectorError, ConnectorRuntime
from cordia.connectors import catalog_for_onboarding, resolve_application
from cordia.onboarding import normalize_applications, score_profile
from cordia.store import SURVEY_FIELDS, Store
from cordia.survey import STAGE_ORDER, public_stage_schema
from cordia.survey_results import build_survey_results
from cordia.workspace_mcp import WorkspaceMCPClient, WorkspaceMCPError


ROOT = Path(__file__).resolve().parent
SESSION_COOKIE = "cordia_session"
ADJUSTMENT_LABELS = {
    ("context", -1): "Use only what I said",
    ("context", 1): "Use more context",
    ("scope", -1): "Focus on the details",
    ("scope", 1): "Show the bigger picture",
    ("directness", -1): "Use a measured tone",
    ("directness", 1): "Be more direct",
    ("implementation", -1): "Explain the reasoning",
    ("implementation", 1): "Give me the implementation",
}


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not os.environ.get(name):
            os.environ[name] = value.strip().strip('"').strip("'")


def resolve_action_starter(applications: list[dict], value) -> dict | None:
    """Resolve a UI action reference from server-owned Surveyor state."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("workspace action is invalid")
    connector_id = str(value.get("connector_id") or "").strip()
    action_id = str(value.get("action_id") or "").strip()
    if not connector_id or not action_id:
        raise ValueError("workspace action is invalid")
    for application in applications:
        identities = {
            str(application.get("registry_id") or "").strip(),
            str(application.get("application_id") or "").strip(),
        }
        if connector_id not in identities:
            continue
        action = next(
            (
                item
                for item in application.get("actions") or []
                if str(item.get("id") or "").strip() == action_id
            ),
            None,
        )
        if action:
            return {
                "connector_id": application.get("registry_id")
                or application.get("application_id"),
                "application_name": str(application.get("name") or "this application").strip(),
                "action_id": action_id,
                "label": str(action.get("label") or "Run action").strip(),
                "prompt": str(action.get("prompt") or "").strip(),
            }
    raise ValueError("workspace action is invalid")


def create_app(
    config: dict | None = None,
    agent=None,
    agent_factory=None,
    connector_runtime=None,
    workspace_client=None,
) -> Flask:
    main_checkout = ROOT.parents[1] if ROOT.parent.name == ".worktrees" else ROOT
    load_local_env(main_checkout / ".env.local")
    load_local_env(main_checkout / ".env.pipedream.local")
    if main_checkout != ROOT:
        load_local_env(ROOT / ".env.local")
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(
        DATABASE=ROOT / "data" / "cordia.db",
        WORKSPACE_ROOT=ROOT / "data" / "workspaces",
        SESSION_COOKIE_SECURE=os.getenv("CORDIA_ENV", "development") != "development",
        COMING_SOON_AFTER_SURVEY=os.getenv(
            "CORDIA_COMING_SOON_AFTER_SURVEY", "true"
        ).strip().lower()
        not in {"false", "0", "no"},
    )
    if config:
        app.config.update(config)

    store = Store(app.config["DATABASE"], app.config["WORKSPACE_ROOT"])
    cordia_agent = agent or Agent(
        os.getenv("OPENAI_API_KEY", ""), os.getenv("OPENAI_MODEL", "gpt-5-mini")
    )
    make_agent = agent_factory or Agent
    default_agent_runtime = {
        "provider": "Cordia",
        "model": getattr(cordia_agent, "model", "default"),
        "source": "server",
    }
    runtime = connector_runtime or ConnectorRuntime(store)
    workspace = workspace_client or WorkspaceMCPClient(runtime, store)
    app.extensions["cordia_store"] = store
    app.extensions["cordia_agent"] = cordia_agent
    app.extensions["connector_runtime"] = runtime
    app.extensions["workspace_mcp_client"] = workspace

    def current_user() -> int | None:
        return store.user_for_session(request.cookies.get(SESSION_COOKIE))

    def require_user() -> int:
        user_id = current_user()
        if not user_id:
            raise PermissionError("sign in required")
        return user_id

    def onboarding_payload(user_id: int) -> dict:
        onboarding = store.onboarding_state(user_id)
        onboarding["stage_schemas"] = {
            stage: public_stage_schema(stage, onboarding["answers"])
            for stage in STAGE_ORDER
        }
        catalog_state = expanded_catalog_state(
            onboarding["answers"].get("workspace_discovery", {})
        )
        applications = catalog_state["applications"]
        connector_catalog = catalog_for_onboarding(applications)
        onboarding["application_catalog"] = applications
        onboarding["application_catalog_status"] = catalog_state["status"]
        if catalog_state.get("message"):
            onboarding["application_catalog_message"] = catalog_state["message"]
        discovery = onboarding["answers"].get("workspace_discovery", {})
        if discovery:
            statuses = {
                connector_id: status
                for connector_id in connector_catalog
                if (status := store.connection_status(user_id, connector_id)) is not None
            }
            normalized = normalize_applications(
                discovery.get("applications", []), connector_catalog, statuses
            )
            selected = [
                {
                    field: application[field]
                    for field in (
                        "application_id",
                        "name",
                        "logo",
                        "already_uses",
                        "wants_added",
                        "current_activities",
                        "desired_activities",
                        "inputs_outputs",
                        "control_level",
                        "registry_id",
                        "auth_kind",
                        "status",
                        "actions",
                    )
                }
                for application in normalized
            ]
            onboarding["selected_applications"] = selected
            if onboarding.get("review"):
                onboarding["review"]["selected_applications"] = selected
        return onboarding

    def expanded_catalog_state(discovery: dict) -> dict:
        catalog_state = runtime.catalog_state("", 100)
        applications = list(catalog_state["applications"])
        if catalog_state["status"] != "ready":
            return catalog_state
        known_ids = {application["id"] for application in applications}
        for selected in discovery.get("applications", []):
            value = selected.get("application_id") or selected.get("name")
            if not value:
                continue
            if selected.get("application_id") and resolve_application(value, applications):
                continue
            matches = runtime.catalog_state(str(value), 20)
            if matches["status"] != "ready":
                continue
            for application in matches["applications"]:
                if application["id"] not in known_ids:
                    applications.append(application)
                    known_ids.add(application["id"])
        return {**catalog_state, "applications": applications}

    def state_payload(user_id: int | None = None) -> dict:
        user_id = current_user() if user_id is None else user_id
        if not user_id:
            return {"state": "signed_out"}
        onboarding = onboarding_payload(user_id)
        if not store.survey_complete(user_id):
            return {"state": "onboarding", "onboarding": onboarding}
        if app.config["COMING_SOON_AFTER_SURVEY"]:
            stages = store.onboarding_stages(user_id)
            try:
                results = build_survey_results(
                    stages,
                    score_profile(stages),
                    onboarding.get("selected_applications", []),
                )
            except (KeyError, TypeError, ValueError):
                app.logger.exception("survey result derivation failed")
                results = {
                    "status": {
                        "label": "Workspace coming soon",
                        "detail": "Your survey is saved, but Cordia could not display the profile yet.",
                    },
                    "plot": None,
                    "direct_findings": [],
                    "connector_plans": [],
                    "indirect_findings": [],
                    "unknowns": [
                        {
                            "title": "Profile display",
                            "statement": "Not enough evidence could be displayed safely. Your saved survey was not changed.",
                        }
                    ],
                }
            return {"state": "results", "survey_results": results}
        workspace_directory = store.workspace_root / str(user_id)
        needs_fde_bootstrap = not (workspace_directory / "surveyor.md").exists() or not (
            workspace_directory / "fde.md"
        ).exists()
        build_error = None
        if needs_fde_bootstrap:
            try:
                with agent_runs.lock(user_id):
                    store.fde_markdown(user_id)
                    agent_runs.start_workspace_build(user_id, locked=True)
            except AgentBusy:
                pass
            except (AgentUnavailable, InvalidAgentAction, ConnectorError, WorkspaceMCPError) as exc:
                build_error = f"Cordia restored your Surveyor workspace, but could not start its FDE build: {exc}"
                store.add_message(user_id, "assistant", build_error, kind="agent")
        return {
            "state": "workspace",
            "build_error": build_error,
            "selected_applications": onboarding.get("selected_applications", []),
            "operator": store.surveyor_markdown(user_id),
            "messages": store.messages(user_id),
            "artifacts": [
                runtime.decorate_artifact(user_id, artifact)
                for artifact in store.artifacts(user_id)
            ],
            "setup_card": store.setup_card(user_id),
            "agent_runtime": agent_runtime_payload(user_id),
            "agent_run": agent_runs.latest(user_id),
        }

    def agent_runtime_payload(user_id: int):
        del user_id
        return default_agent_runtime

    def active_agent(user_id: int):
        del user_id
        return cordia_agent

    agent_runs = AgentRuns(store, workspace, active_agent)
    app.extensions["agent_runs"] = agent_runs

    def exclusive_workspace_action(handler):
        @wraps(handler)
        def execute(*args, **kwargs):
            user_id = require_user()
            with agent_runs.lock(user_id):
                pending = agent_runs.latest(user_id)
                if pending and pending["status"] == "waiting_connection":
                    raise AgentBusy("Finish or cancel the pending authorization first")
                return handler(*args, **kwargs)
        return execute

    def create_operation_artifact(
        user_id: int, connector_id: str, operation_id: str
    ) -> dict:
        operation = workspace.call(
            user_id,
            "connector_call",
            {"connector_id": connector_id, "operation_id": operation_id, "inputs": {}},
        )
        return workspace.call(
            user_id,
            "artifact_create",
            {"payload": operation["artifact"]},
        )["artifact"]

    def continue_after_connection(user_id: int, connector_id: str) -> dict:
        try:
            resumed = agent_runs.resume(user_id, connector_id, locked=True)
        except (AgentUnavailable, InvalidAgentAction, WorkspaceMCPError):
            store.add_message(
                user_id,
                "assistant",
                "- The service is verified, but Cordia could not resume the FDE build automatically. The build needs attention; you do not need to authorize this service again.",
            )
            return {"status": "failed", "artifact": None}
        if resumed is not None:
            return {"status": resumed["run"]["status"], **resumed}
        pending = agent_runs.latest(user_id)
        if pending and pending["status"] == "waiting_connection":
            return {"status": "waiting_connection", "artifact": None}
        try:
            connector = runtime.application(connector_id)
        except ConnectorError:
            connector = {"name": connector_id}
        store.add_message(
            user_id,
            "assistant",
            f"{connector['name']} is connected and its tools are ready for Cordia to use.",
            kind="agent",
        )
        return {"status": "completed", "artifact": None}

    @app.errorhandler(PermissionError)
    def permission_error(exc):
        return jsonify({"ok": False, "error": str(exc)}), 401

    @app.errorhandler(AgentBusy)
    def agent_busy(exc):
        return jsonify({"ok": False, "error": str(exc), **state_payload()}), 409

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "assets/cordia-favicon.ico")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/state")
    def state():
        return jsonify(state_payload())

    @app.post("/api/register")
    def register():
        payload = request.get_json(silent=True) or {}
        try:
            user_id = store.register(payload.get("email", ""), payload.get("password", ""))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        token = store.create_session(user_id)
        response = jsonify({"ok": True, **state_payload(user_id)})
        response.status_code = 201
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="Lax",
            secure=bool(app.config["SESSION_COOKIE_SECURE"]),
            max_age=7 * 24 * 60 * 60,
        )
        return response

    @app.post("/api/signin")
    def signin():
        payload = request.get_json(silent=True) or {}
        user_id = store.authenticate(payload.get("email", ""), payload.get("password", ""))
        if not user_id:
            return jsonify({"ok": False, "error": "email or password is incorrect"}), 401
        token = store.create_session(user_id)
        response = jsonify({"ok": True, **state_payload(user_id)})
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="Lax",
            secure=bool(app.config["SESSION_COOKIE_SECURE"]),
            max_age=7 * 24 * 60 * 60,
        )
        return response

    @app.post("/api/signout")
    def signout():
        store.end_session(request.cookies.get(SESSION_COOKIE))
        response = jsonify({"ok": True, "state": "signed_out"})
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.post("/api/survey")
    def survey():
        user_id = require_user()
        answers = store.survey_answers(user_id)
        if store.onboarding_stages(user_id) or not any(answers.get(field) for field in SURVEY_FIELDS):
            return jsonify({"error": "Continue in the new Surveyor"}), 410
        if store.legacy_survey_complete(user_id):
            return jsonify({"ok": False, "error": "Surveyor is already complete"}), 409
        current = next(field for field in SURVEY_FIELDS if not answers.get(field))
        answer = str((request.get_json(silent=True) or {}).get("answer", "")).strip()
        if not answer:
            return jsonify({"ok": False, "error": "answer is required"}), 400
        store.add_message(user_id, "user", answer, kind="survey")
        store.save_survey_answer(user_id, current, answer)
        return jsonify({"ok": True, **state_payload(user_id)})

    @app.get("/api/onboarding")
    def onboarding_state():
        user_id = require_user()
        return jsonify({"ok": True, "onboarding": onboarding_payload(user_id)})

    @app.put("/api/onboarding/<stage>")
    def onboarding_stage(stage):
        user_id = require_user()
        if store.survey_complete(user_id):
            return jsonify({"ok": False, "error": "Surveyor is already complete"}), 409
        try:
            store.save_onboarding_stage(user_id, stage, request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "onboarding": onboarding_payload(user_id)})

    @app.post("/api/onboarding/complete")
    def onboarding_complete():
        user_id = require_user()
        build_error = None
        try:
            with agent_runs.lock(user_id):
                discovery = store.onboarding_state(user_id)["answers"].get(
                    "workspace_discovery", {}
                )
                catalog = catalog_for_onboarding(
                    expanded_catalog_state(discovery)["applications"]
                )
                store.complete_onboarding(user_id, catalog)
                if not app.config["COMING_SOON_AFTER_SURVEY"]:
                    try:
                        agent_runs.start_workspace_build(user_id, locked=True)
                    except (AgentUnavailable, InvalidAgentAction, ConnectorError, WorkspaceMCPError) as exc:
                        build_error = f"Your Surveyor is saved, but Cordia could not start the workspace build: {exc}"
                        store.add_message(user_id, "assistant", build_error, kind="agent")
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "onboarding": onboarding_payload(user_id)}), 409
        except OSError:
            app.logger.exception("onboarding workspace installation failed")
            return jsonify({"ok": False, "error": "Cordia could not safely create your workspace. Your survey is saved."}), 500
        return jsonify({"ok": True, "build_error": build_error, **state_payload(user_id)})

    @app.post("/api/chat")
    def chat():
        user_id = require_user()
        if not store.survey_complete(user_id):
            return jsonify({"ok": False, "error": "complete Surveyor first"}), 409
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message", "")).strip()
        if not message:
            return jsonify({"ok": False, "error": "message is required"}), 400
        action_starter = None
        if payload.get("action_starter") is not None:
            try:
                action_starter = resolve_action_starter(
                    onboarding_payload(user_id).get("selected_applications", []),
                    payload["action_starter"],
                )
            except ValueError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
        artifact_context = None
        if payload.get("artifact_id") is not None:
            try:
                artifact_id = int(payload["artifact_id"])
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "artifact_id is invalid"}), 400
            artifact = next(
                (item for item in store.artifacts(user_id) if item["id"] == artifact_id),
                None,
            )
            if artifact is None:
                return jsonify({"ok": False, "error": "workspace artifact was not found"}), 404
            artifact_context = json.dumps(
                {
                    key: artifact.get(key)
                    for key in (
                        "title",
                        "type",
                        "source",
                        "operation_id",
                        "summary",
                        "columns",
                        "rows",
                        "items",
                        "value",
                    )
                    if artifact.get(key) is not None
                },
                ensure_ascii=False,
            )
        try:
            result = agent_runs.start(
                user_id,
                message,
                context=artifact_context,
                action_starter=action_starter,
            )
            return jsonify(
                {
                    "ok": result["run"]["status"] not in {"failed", "needs_configuration"},
                    **result,
                    **state_payload(user_id),
                }
            )
        except AgentUnavailable as exc:
            message = f"The Cordia Agent is unavailable: {exc}"
            store.add_message(user_id, "assistant", message)
            return jsonify({"ok": False, "error": message, **state_payload(user_id)}), 503
        except (InvalidAgentAction, ConnectorError) as exc:
            message = f"Cordia could not complete that request: {exc}"
            store.add_message(user_id, "assistant", message)
            return jsonify({"ok": False, "error": message, **state_payload(user_id)}), 422
        except WorkspaceMCPError as exc:
            message = f"Cordia could not complete that workspace action: {exc}"
            store.add_message(user_id, "assistant", message)
            return jsonify({"ok": False, "error": message, **state_payload(user_id)}), 502

    @app.post("/api/responses/<int:response_id>/adjust")
    def adjust_response(response_id: int):
        user_id = require_user()
        payload = request.get_json(silent=True) or {}
        axis = payload.get("axis")
        target = payload.get("target")
        label = ADJUSTMENT_LABELS.get((axis, target))
        if not label:
            return jsonify({"ok": False, "error": "Choose one available response adjustment"}), 400
        try:
            with agent_runs.lock(user_id):
                adjustment = store.adjust_operator(user_id, response_id, axis, target, label)
                result = agent_runs.revise(user_id, response_id, locked=True)
            return jsonify(
                {
                    "ok": True,
                    **result,
                    "adjustment": adjustment,
                    **state_payload(user_id),
                }
            )
        except LookupError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 404
        except AgentUnavailable as exc:
            message = f"Your preference was saved, but Cordia could not revise the response: {exc}"
            return jsonify({"ok": False, "error": message, **state_payload(user_id)}), 503
        except (InvalidAgentAction, ConnectorError) as exc:
            message = f"Your preference was saved, but Cordia could not revise the response: {exc}"
            return jsonify({"ok": False, "error": message, **state_payload(user_id)}), 422
        except WorkspaceMCPError as exc:
            message = f"Your preference was saved, but the workspace action failed: {exc}"
            return jsonify({"ok": False, "error": message, **state_payload(user_id)}), 502

    @app.get("/api/connectors/search")
    def connector_search():
        user_id = require_user()
        del user_id
        query = str(request.args.get("q", "")).strip()[:200]
        try:
            catalog = runtime.catalog_state(query, 50)
        except ConnectorError as exc:
            return jsonify({"ok": False, "error": str(exc), "applications": []}), 502
        return jsonify({"ok": catalog["status"] == "ready", **catalog})

    @app.get("/api/connectors/oauth/callback")
    def oauth_callback():
        user_id = require_user()
        with agent_runs.lock(user_id):
            state = request.args.get("state", "")
            connector_id = store.oauth_connector_for_state(user_id, state)
            if not connector_id:
                return redirect("/?error=invalid_oauth_state")
            if request.args.get("error"):
                store.consume_oauth_state(user_id, connector_id, state)
                agent_runs.deny(user_id, connector_id, locked=True)
                if (store.setup_card(user_id) or {}).get("connector_id") == connector_id:
                    store.clear_setup_card(user_id)
                return redirect("/?error=oauth_denied")
            try:
                runtime.finish_connection(user_id, connector_id, {"state": state, "code": request.args.get("code", "")})
            except ConnectorError:
                return redirect("/?error=connector_verification_failed")
            if (store.setup_card(user_id) or {}).get("connector_id") == connector_id:
                store.clear_setup_card(user_id)
            workspace_update = continue_after_connection(user_id, connector_id)
        query = urlencode(
            {"connected": connector_id, "workspace_update": workspace_update["status"]}
        )
        return redirect(f"/?{query}")

    @app.post("/api/connectors/setup")
    def connector_setup():
        user_id = require_user()
        payload = request.get_json(silent=True) or {}
        connector_id = str(payload.get("connector_id", "")).strip()
        credentials = payload.get("credentials")
        if not connector_id or not isinstance(credentials, dict):
            return jsonify({"ok": False, "error": "connector and credentials are required"}), 400
        with agent_runs.lock(user_id):
            if connector_id.startswith("mcp:"):
                server_id = connector_id[4:]
                try:
                    connection = workspace.finish_server_setup(
                        user_id, server_id, credentials
                    )
                except (ValueError, WorkspaceMCPError) as exc:
                    return jsonify(
                        {"ok": False, "error": str(exc), **state_payload(user_id)}
                    ), 422
                if (store.setup_card(user_id) or {}).get("connector_id") == connector_id:
                    store.clear_setup_card(user_id)
                workspace_update = continue_after_connection(user_id, connector_id)
                return jsonify(
                    {
                        "ok": True,
                        "connection": connection,
                        "workspace_update": workspace_update,
                        **state_payload(user_id),
                    }
                )
            try:
                connection = runtime.finish_connection(user_id, connector_id, credentials)
            except ConnectorError as exc:
                return jsonify({"ok": False, "error": str(exc), **state_payload(user_id)}), 422
            if (store.setup_card(user_id) or {}).get("connector_id") == connector_id:
                store.clear_setup_card(user_id)
            workspace_update = continue_after_connection(user_id, connector_id)
        return jsonify(
            {
                "ok": True,
                "connection": connection,
                "workspace_update": workspace_update,
                "artifact": workspace_update["artifact"],
                **state_payload(user_id),
            }
        )

    @app.post("/api/connectors/cancel")
    def connector_cancel():
        user_id = require_user()
        connector_id = str((request.get_json(silent=True) or {}).get("connector_id", ""))
        with agent_runs.lock(user_id):
            card = store.setup_card(user_id) or {}
            if card.get("connector_id") == connector_id:
                state = parse_qs(urlparse(card.get("action_url", "")).query).get("state", [""])[0]
                if state:
                    store.consume_oauth_state(user_id, connector_id, state)
            agent_runs.deny(user_id, connector_id, locked=True)
            if (store.setup_card(user_id) or {}).get("connector_id") == connector_id:
                store.clear_setup_card(user_id)
        return jsonify({"ok": True, **state_payload(user_id)})

    @app.post("/api/agent/approval")
    def agent_action_approval():
        user_id = require_user()
        payload = request.get_json(silent=True) or {}
        connector_id = str(payload.get("connector_id") or "").strip()
        approved = payload.get("approved")
        if not connector_id or not isinstance(approved, bool):
            return jsonify({"ok": False, "error": "connector and approval decision are required"}), 400
        try:
            result = agent_runs.approve(user_id, connector_id, approved)
        except LookupError as exc:
            return jsonify({"ok": False, "error": str(exc), **state_payload(user_id)}), 409
        except (AgentUnavailable, InvalidAgentAction, WorkspaceMCPError) as exc:
            return jsonify({"ok": False, "error": str(exc), **state_payload(user_id)}), 422
        return jsonify({"ok": True, **result, **state_payload(user_id)})

    @app.post("/api/connectors/select")
    @exclusive_workspace_action
    def connector_select():
        user_id = require_user()
        payload = request.get_json(silent=True) or {}
        connector_id = str(payload.get("connector_id", "")).strip()
        value = str(payload.get("value", "")).strip()
        if not connector_id or not value:
            return jsonify({"ok": False, "error": "connector and selection are required"}), 400
        try:
            selection = runtime.select_value(user_id, connector_id, value)
        except ConnectorError as exc:
            return jsonify({"ok": False, "error": str(exc), **state_payload(user_id)}), 422
        return jsonify({"ok": True, "selection": selection, **state_payload(user_id)})

    @app.post("/api/connectors/live-view")
    @exclusive_workspace_action
    def connector_live_view():
        user_id = require_user()
        payload = request.get_json(silent=True) or {}
        connector_id = str(payload.get("connector_id", "")).strip()
        if not connector_id:
            return jsonify({"ok": False, "error": "connector is required"}), 400
        try:
            access = runtime.live_view_access(user_id, connector_id)
        except ConnectorError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 422
        if access["status"] == "unsupported":
            return jsonify({"ok": False, "error": "Live View is not supported"}), 422
        if access["status"] != "granted":
            try:
                setup_card = runtime.start_connection(
                    user_id,
                    connector_id,
                    requested_scopes=access.get("missing_scopes") or None,
                )
            except ConnectorError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 422
            store.save_setup_card(user_id, setup_card)
            return jsonify(
                {
                    "ok": True,
                    "live_view": access,
                    "setup_card": setup_card,
                    **state_payload(user_id),
                }
            )
        try:
            artifact = create_operation_artifact(
                user_id, connector_id, access["operation"]
            )
        except WorkspaceMCPError as exc:
            return jsonify(
                {"ok": False, "error": str(exc), "live_view": access, **state_payload(user_id)}
            ), 502
        return jsonify(
            {
                "ok": True,
                "live_view": access,
                "artifact": artifact,
                **state_payload(user_id),
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
