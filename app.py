from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory

from cordia.agent import Agent, AgentUnavailable, InvalidAgentAction
from cordia.connector_runtime import ConnectorError, ConnectorRuntime
from cordia.store import SURVEY_FIELDS, Store


ROOT = Path(__file__).resolve().parent
SESSION_COOKIE = "cordia_session"
SURVEY_QUESTIONS = {
    "name": "What should I call you?",
    "role": "What kind of work or role should this workspace support?",
    "goal": "What is the first meaningful outcome you want Cordia to help with?",
    "apps": "Which apps or services are already part of that work?",
    "communication": "How should I explain things to you: big picture first, detail first, visual, or another way?",
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


def create_app(config: dict | None = None, agent=None, connector_runtime=None) -> Flask:
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
    runtime = connector_runtime or ConnectorRuntime(store)
    app.extensions["cordia_store"] = store
    app.extensions["cordia_agent"] = cordia_agent
    app.extensions["connector_runtime"] = runtime

    def current_user() -> int | None:
        return store.user_for_session(request.cookies.get(SESSION_COOKIE))

    def require_user() -> int:
        user_id = current_user()
        if not user_id:
            raise PermissionError("sign in required")
        return user_id

    def next_survey(user_id: int) -> dict | None:
        answers = store.survey_answers(user_id)
        for field in SURVEY_FIELDS:
            if not answers.get(field):
                return {"field": field, "question": SURVEY_QUESTIONS[field]}
        return None

    def state_payload(user_id: int | None = None) -> dict:
        user_id = current_user() if user_id is None else user_id
        if not user_id:
            return {"state": "signed_out"}
        survey = next_survey(user_id)
        return {
            "state": "survey" if survey else "workspace",
            "survey": survey,
            "memory": store.memory_markdown(user_id),
            "messages": store.messages(user_id),
            "artifacts": store.artifacts(user_id),
            "setup_card": store.setup_card(user_id),
        }

    @app.errorhandler(PermissionError)
    def permission_error(exc):
        return jsonify({"ok": False, "error": str(exc)}), 401

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
        current = next_survey(user_id)
        if not current:
            return jsonify({"ok": False, "error": "Surveyor is already complete"}), 409
        answer = str((request.get_json(silent=True) or {}).get("answer", "")).strip()
        if not answer:
            return jsonify({"ok": False, "error": "answer is required"}), 400
        store.add_message(user_id, "user", answer)
        store.save_survey_answer(user_id, current["field"], answer)
        upcoming = next_survey(user_id)
        assistant_message = (
            upcoming["question"]
            if upcoming
            else "I saved that understanding. We can keep talking here and build your workspace together."
        )
        store.add_message(user_id, "assistant", assistant_message)
        return jsonify({"ok": True, "assistant": assistant_message, **state_payload(user_id)})

    @app.post("/api/chat")
    def chat():
        user_id = require_user()
        if not store.survey_complete(user_id):
            return jsonify({"ok": False, "error": "complete Surveyor first"}), 409
        message = str((request.get_json(silent=True) or {}).get("message", "")).strip()
        if not message:
            return jsonify({"ok": False, "error": "message is required"}), 400
        store.add_message(user_id, "user", message)
        try:
            action = cordia_agent.respond(store.memory_markdown(user_id), store.messages(user_id))
            setup_card = None
            artifact = None
            if action["action"] == "propose_connector":
                setup_card = runtime.start_connection(user_id, action["connector_id"])
                store.save_setup_card(user_id, setup_card)
            elif action["action"] == "run_operation":
                artifact = runtime.call_operation(
                    user_id, action["connector_id"], action["operation_id"], {}
                )
                artifact_id = store.save_artifact(user_id, artifact)
                artifact = {**artifact, "id": artifact_id}
            store.add_message(user_id, "assistant", action["message"])
            return jsonify(
                {
                    "ok": True,
                    "assistant": action["message"],
                    "setup_card": setup_card,
                    "artifact": artifact,
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

    @app.get("/api/connectors/oauth/callback")
    def oauth_callback():
        user_id = require_user()
        state = request.args.get("state", "")
        connector_id = store.oauth_connector_for_state(user_id, state)
        if not connector_id:
            return redirect("/?error=invalid_oauth_state")
        if request.args.get("error"):
            store.consume_oauth_state(user_id, connector_id, state)
            store.clear_setup_card(user_id)
            return redirect("/?error=oauth_denied")
        try:
            runtime.finish_connection(
                user_id,
                connector_id,
                {"state": state, "code": request.args.get("code", "")},
            )
        except ConnectorError:
            return redirect("/?error=connector_verification_failed")
        store.clear_setup_card(user_id)
        return redirect(f"/?connected={connector_id}")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
