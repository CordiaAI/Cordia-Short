"""Opt-in real-provider journey. Uses a disposable local workspace, never production data.

Run from the repository: python scripts/verify_agent.py --live --env-file PATH
This makes billable model calls and read-only OpenAI models requests. No mocks.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def stages():
    return {
        "assessment_part_1": {"answers": {f"p1_{n:02d}": 3 for n in range(1, 21)}},
        "assessment_part_2": {
            "domains": ["technology_software"], "ratings": {"technology_software": 4},
            "familiarity": {"technology_software": {
                "cloud storage": "familiar", "two-factor authentication": "familiar",
                "adaptive port throttling": "not_familiar", "browser cache": "familiar", "API": "familiar",
            }},
        },
        "assessment_part_3": {
            "briefing_style": "requirements_upfront", "reply_preference": "literal_narrow",
            "most": "logical", "least": "imaginative", "flawed_plan": "state_plainly",
            "answer_order": "answer_first", "background_assumption": "spell_out_background",
            "edit_boundary": "only_requested_edits", "bad_idea": "say_so_directly",
        },
        "assessment_part_4": {
            "request_1": "List the models available in my OpenAI account.",
            "request_2": "Refresh that same model window.", "request_3": "",
        },
        "workspace_discovery": {
            "outcome": "Inspect the models available in my account.",
            "success_criteria": "A window shows models returned by OpenAI.",
            "current_workflow": "I manually check the provider model list.",
            "applications": [{
                "application_id": "openai_api", "name": "OpenAI API", "already_uses": True,
                "wants_added": True, "current_activities": "Inspect available models.",
                "desired_activities": "List models in the workspace.",
                "inputs_outputs": "My account in, available model names out.",
                "control_level": "prepare_for_approval",
            }],
            "inputs": "My OpenAI account.", "outputs": "Model catalog window.",
            "control_level": "prepare_for_approval", "first_workspace": "Model catalog workspace.",
        },
    }


def checked(response, label):
    body = response.get_json()
    if not response.is_json or response.status_code >= 400 or body.get("ok") is False:
        # Never dump request, credentials, arbitrary provider exceptions or the full workspace.
        raise RuntimeError(f"{label}: HTTP {response.status_code}; {body.get('error', 'invalid response') if isinstance(body, dict) else 'invalid response'}")
    return body


def require_current_artifact(result, expected_id):
    artifact = result.get("artifact")
    assert artifact and artifact.get("id") == expected_id and artifact.get("rows"), "The current run did not produce the expected nonempty artifact"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize this billable, real-provider test")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--serve", action="store_true", help="Serve the disposable QA workspace on loopback port 5059")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize real API requests; this is not a simulated test")
    # Load privately before importing the app; never emit environment values.
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip('\"').strip("'"))
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is missing; no requests made")
    os.environ["OPENAI_MODEL"] = args.model
    from app import create_app
    from cordia.agent import redact_secrets

    with tempfile.TemporaryDirectory(prefix="cordia-real-provider-") as folder:
        root = Path(folder)
        config = {"TESTING": True, "DATABASE": root / "cordia.db",
                  "WORKSPACE_ROOT": root / "workspaces", "SESSION_COOKIE_SECURE": False}
        app = create_app(config)
        client = app.test_client()
        report = {"model": args.model, "external_services": "real OpenAI model and models endpoint", "steps": []}
        try:
            checked(client.post("/api/register", json={"email": "agent-proof@example.invalid", "password": "local-qa-only-password" if args.serve else secrets.token_urlsafe(24)}), "register")
            for stage, payload in stages().items():
                checked(client.put(f"/api/onboarding/{stage}", json=payload), stage)
            state = checked(client.post("/api/onboarding/complete"), "complete onboarding")
            assert state["state"] == "workspace", "Workspace was not created"
            assert all((root / "workspaces" / "1" / name).exists() for name in ("operator.md", "connectors.md", "fde.md"))
            report["steps"].append("registration, all assessment/discovery stages, three memory files")

            if args.serve:
                print("Disposable local QA: http://127.0.0.1:5059/ (not beta)", flush=True)
                app.run(host="127.0.0.1", port=5059, debug=False, use_reloader=False)
                return 0

            started = time.monotonic()
            connect = checked(client.post("/api/chat", json={"message": "Connect OpenAI API and list the models available in my account in a workspace window."}), "agent connection request")
            card = connect.get("setup_card")
            assert card and card["connector_id"] == "openai_api", "Agent did not produce a setup card"
            assert card["type"] == "credential_form", "Setup did not request secure credential entry"
            run = connect.get("run") or connect.get("agent_run") or {}
            assert run.get("status") == "waiting_connection", "No persistent agent wait was established"
            pending_id = run["id"]
            report["steps"].append("real model requested secure connector setup")

            # Reconstruct app before credential entry to exercise durable pending execution.
            cookie = client.get_cookie("cordia_session")
            app = create_app(config)
            client = app.test_client()
            client.set_cookie("cordia_session", cookie.value)
            connected = checked(client.post("/api/connectors/setup", json={"connector_id": "openai_api", "credentials": {"api_key": os.environ["OPENAI_API_KEY"]}}), "verify and resume")
            artifacts = [a for a in connected["artifacts"] if a.get("source") == "openai_api"]
            run = connected.get("run") or connected.get("agent_run") or {}
            assert run.get("id") == pending_id and run.get("status") == "completed", "Authorization did not resume the original agent run"
            assert len(artifacts) == 1 and artifacts[0]["rows"], "No single provider-derived artifact after authorization"
            first_id = artifacts[0]["id"]
            report["steps"].append("verified API-key connection and continuation after app reconstruction")
            report["first_flow_seconds"] = round(time.monotonic() - started, 2)

            selected = checked(client.post("/api/connectors/select", json={"connector_id": "openai_api", "value": args.model}), "select model")
            assert selected["agent_runtime"]["model"] == args.model and selected["agent_runtime"]["source"] == "connector", "Model selection was not persisted"
            refreshed = checked(client.post("/api/chat", json={"message": "Refresh the same OpenAI model window using the connector, and tell me how many models the tool returned. Do not create a second window."}), "refresh")
            artifacts = [a for a in refreshed["artifacts"] if a.get("source") == "openai_api"]
            assert len(artifacts) == 1 and artifacts[0]["id"] == first_id, "Refresh duplicated the artifact"
            require_current_artifact(refreshed, first_id)
            run = refreshed.get("run") or refreshed.get("agent_run") or {}
            assert run.get("status") == "completed" and run.get("model_calls", 0) >= 2, "Refresh did not complete a model/tool/result/model loop"
            assert run.get("source") == "connector" and run.get("model") == args.model, "Agent ignored user-selected provider"
            report["steps"].append("user-selected provider model refreshed the same persisted artifact")
            report["artifact_rows"] = len(artifacts[0]["rows"])
            report["assistant"] = redact_secrets(refreshed.get("assistant", ""))
            report["agent_run"] = run
            report["status"] = "passed"
        except Exception as exc:
            report["status"] = "failed"
            report["error"] = redact_secrets(str(exc)).replace(os.environ["OPENAI_API_KEY"], "[REDACTED]")
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
