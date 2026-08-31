from __future__ import annotations

import os
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from flask import Flask, jsonify, redirect, request, send_from_directory

from cordia.agent import Agent, AgentBusy, AgentUnavailable, InvalidAgentAction
from cordia.agent_runs import AgentRuns
from cordia.connector_runtime import ConnectorError, ConnectorRuntime
from cordia.connectors import CONNECTORS, resolve_connector
from cordia.onboarding import normalize_applications
from cordia.store import SURVEY_FIELDS, Store
from cordia.survey import STAGE_ORDER, public_stage_schema
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
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def create_app(
    config: dict | None = None,
    agent=None,
    agent_factory=None,
    connector_runtime=None,
    workspace_client=None,
) -> Flask:
    load_local_env(ROOT / ".env.local")
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(
        DATABASE=ROOT / "data" / "cordia.db",
        WORKSPACE_ROOT=ROOT / "data" / "workspaces",
        SESSION_COOKIE_SECURE=os.getenv("CORDIA_ENV", "development") != "development",
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
        onboarding["application_catalog"] = [
            {"id": connector["id"], "name": connector["name"]}
            for connector in CONNECTORS.values()
        ]
        discovery = onboarding["answers"].get("workspace_discovery", {})
        if discovery:
            statuses = {
                connector_id: status
                for connector_id in CONNECTORS
                if (status := store.connection_status(user_id, connector_id)) is not None
            }
            normalized = normalize_applications(
                discovery.get("applications", []), CONNECTORS, statuses
            )
            selected = [
                {
                    field: application[field]
                    for field in (
                        "application_id",
                        "name",
                        "already_uses",
                        "wants_added",
                        "current_activities",
                        "desired_activities",
                        "inputs_outputs",
                        "control_level",
                        "registry_id",
                        "status",
                    )
                }
                for application in normalized
            ]
            onboarding["selected_applications"] = selected
            if onboarding.get("review"):
                onboarding["review"]["selected_applications"] = selected
        return onboarding

    def state_payload(user_id: int | None = None) -> dict:
        user_id = current_user() if user_id is None else user_id
        if not user_id:
            return {"state": "signed_out"}
        onboarding = onboarding_payload(user_id)
        if not store.survey_complete(user_id):
            return {"state": "onboarding", "onboarding": onboarding}
        return {
            "state": "workspace",
            "selected_applications": onboarding.get("selected_applications", []),
            "operator": store.operator_markdown(user_id),
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
        selected = runtime.agent_runtime(user_id)
        selected_id = store.connection_setting(user_id, "__runtime__", "agent_model")
        if not selected and not selected_id:
            return default_agent_runtime
        try:
            available = runtime.agent_provider(user_id) is not None
        except RuntimeError:
            available = False
        if available:
            return selected
        connector = CONNECTORS.get(selected_id, {})
        return {"provider": (selected or {}).get("provider", connector.get("name", "Selected provider")) + " (unavailable)",
                "model": (selected or {}).get("model") or store.connection_setting(user_id, selected_id, "model") or "unavailable",
                "source": "connector"}

    def active_agent(user_id: int):
        try:
            provider = runtime.agent_provider(user_id)
        except RuntimeError as exc:
            raise AgentUnavailable("Selected model credentials are unavailable; reconnect the provider") from exc
        if not provider:
            if (runtime.agent_runtime(user_id)
                    or store.connection_setting(user_id, "__runtime__", "agent_model")):
                raise AgentUnavailable("Selected model credentials are unavailable; reconnect the provider")
            return cordia_agent
        selected = make_agent(provider["credential"], provider["model"])
        selected.source = "connector"
        return selected

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

    def prepare_selected_setup(user_id: int):
        pending = agent_runs.latest(user_id)
        if store.setup_card(user_id) or (pending and pending["status"] == "waiting_connection"):
            return
        for application in onboarding_payload(user_id).get("selected_applications", []):
            connector_id = application.get("registry_id")
            if (application.get("wants_added") and connector_id in CONNECTORS
                    and store.connection_status(user_id, connector_id) != "verified"):
                card = workspace.call(user_id, "connector_start", {"connector_id": connector_id})
                store.save_setup_card(user_id, card)
                return

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
            store.add_message(user_id, "assistant", "- The service is verified, but Cordia could not finish your original request. Please submit it again.")
            return {"status": "failed", "artifact": None}
        if resumed is not None:
            return {"status": resumed["run"]["status"], **resumed}
        pending = agent_runs.latest(user_id)
        if pending and pending["status"] == "waiting_connection":
            return {"status": "waiting_connection", "artifact": None}
        connector = resolve_connector(connector_id)
        if not connector:
            return {"status": "not_configured", "artifact": None}
        operation_id = connector.get("post_connect_operation")
        if not operation_id:
            store.add_message(
                user_id,
                "assistant",
                f"{connector['name']} is connected and ready.",
                kind="agent",
            )
            return {"status": "not_configured", "artifact": None}
        try:
            artifact = create_operation_artifact(user_id, connector_id, operation_id)
        except WorkspaceMCPError:
            store.add_message(
                user_id,
                "assistant",
                f"{connector['name']} is connected, but its first workspace view could not be loaded yet.",
                kind="agent",
            )
            return {"status": "failed", "artifact": None}
        store.add_message(
            user_id,
            "assistant",
            f"{connector['name']} is connected and ready. I updated your workspace automatically.",
            kind="agent",
        )
        return {"status": "updated", "artifact": artifact}

    @app.errorhandler(PermissionError)
    def permission_error(exc):
        return jsonify({"ok": False, "error": str(exc)}), 401

    @app.errorhandler(AgentBusy)
    def agent_busy(exc):
        return jsonify({"ok": False, "error": str(exc), **state_payload()}), 409

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

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
        try:
            with agent_runs.lock(user_id):
                store.complete_onboarding(user_id, CONNECTORS)
                prepare_selected_setup(user_id)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "onboarding": onboarding_payload(user_id)}), 409
        except OSError:
            app.logger.exception("onboarding workspace installation failed")
            return jsonify({"ok": False, "error": "Cordia could not safely create your workspace. Your survey is saved."}), 500
        except WorkspaceMCPError:
            return jsonify({"ok": False, "error": "Workspace created, but app setup could not be prepared. Ask Cordia to connect it again.", **state_payload(user_id)}), 502
        return jsonify({"ok": True, **state_payload(user_id)})

    @app.post("/api/chat")
    def chat():
        user_id = require_user()
        if not store.survey_complete(user_id):
            return jsonify({"ok": False, "error": "complete Surveyor first"}), 409
        message = str((request.get_json(silent=True) or {}).get("message", "")).strip()
        if not message:
            return jsonify({"ok": False, "error": "message is required"}), 400
        try:
            result = agent_runs.start(user_id, message)
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
            prepare_selected_setup(user_id)
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
            try:
                connection = runtime.finish_connection(user_id, connector_id, credentials)
            except ConnectorError as exc:
                return jsonify({"ok": False, "error": str(exc), **state_payload(user_id)}), 422
            if (store.setup_card(user_id) or {}).get("connector_id") == connector_id:
                store.clear_setup_card(user_id)
            workspace_update = continue_after_connection(user_id, connector_id)
            prepare_selected_setup(user_id)
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
