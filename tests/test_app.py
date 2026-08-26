import tempfile
import unittest
from pathlib import Path

from app import create_app
from cordia.workspace_mcp import WorkspaceMCPError


class FakeAgent:
    def __init__(self):
        self.calls = []

    def respond(self, memory, messages):
        self.calls.append((memory, list(messages)))
        latest = messages[-1]["content"].lower()
        if "connect" in latest:
            return {
                "action": "propose_connector",
                "message": "I can set up Google Drive.",
                "connector_id": "google_drive",
                "operation_id": None,
            }
        if "recent" in latest:
            return {
                "action": "run_operation",
                "message": "I checked your recent files.",
                "connector_id": "google_drive",
                "operation_id": "list_recent_files",
            }
        return {
            "action": "speak",
            "message": "Tell me what you want the workspace to do.",
            "connector_id": None,
            "operation_id": None,
        }


class FakeRuntime:
    def __init__(self):
        self.finished = []

    def start_connection(self, user_id, connector_id):
        return {
            "type": "oauth_redirect",
            "connector_id": connector_id,
            "title": "Connect Google Drive",
            "status": "ready",
            "message": "Continue securely.",
            "action_url": "https://accounts.google.com/example",
        }

    def call_operation(self, user_id, connector_id, operation_id, inputs):
        return {
            "type": "table",
            "title": "Recent Google Drive files",
            "columns": ["Name"],
            "rows": [["Plan.md"]],
            "source": connector_id,
        }

    def finish_connection(self, user_id, connector_id, setup_result):
        self.finished.append((user_id, connector_id, setup_result))
        return {"connector_id": connector_id, "status": "verified"}


class RecordingWorkspaceClient:
    def __init__(self):
        self.calls = []
        self.store = None
        self.fail_tool = None

    def call(self, user_id, tool_name, arguments):
        self.calls.append((user_id, tool_name, arguments))
        if tool_name == self.fail_tool:
            raise WorkspaceMCPError("provider operation failed")
        if tool_name == "connector_start":
            return {
                "type": "oauth_redirect",
                "connector_id": arguments["connector_id"],
                "title": "Connect Google Drive",
                "status": "ready",
                "message": "Continue securely.",
                "action_url": "https://accounts.google.com/example",
            }
        if tool_name == "connector_call":
            return {
                "artifact": {
                    "type": "table",
                    "title": "Recent Google Drive files",
                    "columns": ["Name"],
                    "rows": [["Plan.md"]],
                    "source": arguments["connector_id"],
                }
            }
        if tool_name == "artifact_create":
            artifact = arguments["payload"]
            artifact_id = self.store.save_artifact(user_id, artifact)
            return {"artifact": {**artifact, "id": artifact_id}}
        raise AssertionError(f"unexpected workspace tool: {tool_name}")


class ApplicationJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.runtime = FakeRuntime()
        self.workspace = RecordingWorkspaceClient()
        self.agent = FakeAgent()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "cordia.db",
                "WORKSPACE_ROOT": root / "workspaces",
                "SESSION_COOKIE_SECURE": False,
            },
            agent=self.agent,
            connector_runtime=self.runtime,
            workspace_client=self.workspace,
        )
        self.workspace.store = self.app.extensions["cordia_store"]
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def register(self):
        response = self.client.post(
            "/api/register",
            json={"email": "person@example.com", "password": "correct horse battery"},
        )
        self.assertEqual(201, response.status_code)

    def complete_survey(self):
        for answer in [
            "Jordan",
            "Operations lead",
            "Find client documents quickly",
            "Google Drive, Slack",
            "Big picture first",
        ]:
            response = self.client.post("/api/survey", json={"answer": answer})
            self.assertEqual(200, response.status_code)

    def test_unauthenticated_state_is_explicit(self):
        response = self.client.get("/api/state")
        self.assertEqual(200, response.status_code)
        self.assertEqual("signed_out", response.json["state"])

    def test_register_survey_and_chat_are_one_continuous_workspace(self):
        self.register()
        state = self.client.get("/api/state").json
        self.assertEqual("survey", state["state"])
        self.assertEqual("name", state["survey"]["field"])

        self.complete_survey()
        state = self.client.get("/api/state").json
        self.assertEqual("workspace", state["state"])
        self.assertIn("Google Drive, Slack", state["operator"])
        self.assertGreaterEqual(len(state["messages"]), 10)

        response = self.client.post("/api/chat", json={"message": "Connect Google Drive"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("oauth_redirect", response.json["setup_card"]["type"])
        self.assertEqual("workspace", response.json["state"])
        refreshed = self.client.get("/api/state").json
        self.assertEqual("oauth_redirect", refreshed["setup_card"]["type"])
        self.assertEqual(
            [(1, "connector_start", {"connector_id": "google_drive"})],
            self.workspace.calls,
        )

    def test_adjusting_response_updates_operator_and_retries_the_original_request(self):
        self.register()
        self.complete_survey()
        first = self.client.post("/api/chat", json={"message": "Give me the plan"})
        response_id = first.json["messages"][-1]["id"]

        retried = self.client.post(
            f"/api/responses/{response_id}/adjust",
            json={"axis": "implementation", "target": 1},
        )

        self.assertEqual(200, retried.status_code)
        self.assertEqual("implementation", retried.json["adjustment"]["axis"])
        self.assertEqual(1, retried.json["adjustment"]["current"])
        self.assertIn("Implementation preference: Implementation-first (1)", retried.json["operator"])
        retry_operator, retry_messages = self.agent.calls[-1]
        self.assertIn("Implementation preference: Implementation-first (1)", retry_operator)
        self.assertEqual("Give me the plan", retry_messages[-1]["content"])

    def test_adjusting_unknown_response_is_rejected_without_calling_agent(self):
        self.register()
        self.complete_survey()
        prior_calls = len(self.agent.calls)

        response = self.client.post(
            "/api/responses/9999/adjust",
            json={"axis": "directness", "target": 1},
        )

        self.assertEqual(404, response.status_code)
        self.assertEqual(prior_calls, len(self.agent.calls))

    def test_only_agent_responses_are_eligible_for_operator_adjustment(self):
        self.register()
        self.complete_survey()
        survey_messages = self.client.get("/api/state").json["messages"]
        survey_response_id = next(
            message["id"] for message in survey_messages if message["role"] == "assistant"
        )

        rejected = self.client.post(
            f"/api/responses/{survey_response_id}/adjust",
            json={"axis": "scope", "target": 1},
        )
        chat = self.client.post("/api/chat", json={"message": "Help me plan this"})

        self.assertEqual(404, rejected.status_code)
        self.assertTrue(all(message["kind"] == "survey" for message in survey_messages))
        self.assertEqual("agent", chat.json["messages"][-1]["kind"])

    def test_agent_operation_saves_visible_artifact(self):
        self.register()
        self.complete_survey()

        response = self.client.post("/api/chat", json={"message": "Show my recent files"})

        self.assertEqual(200, response.status_code)
        self.assertEqual("Plan.md", response.json["artifact"]["rows"][0][0])
        state = self.client.get("/api/state").json
        self.assertEqual("Plan.md", state["artifacts"][0]["rows"][0][0])
        self.assertEqual(
            ["connector_call", "artifact_create"],
            [call[1] for call in self.workspace.calls],
        )

    def test_workspace_tool_failure_is_explicit_and_creates_no_artifact(self):
        self.register()
        self.complete_survey()
        self.workspace.fail_tool = "connector_call"

        response = self.client.post("/api/chat", json={"message": "Show my recent files"})

        self.assertEqual(502, response.status_code)
        self.assertIn("provider operation failed", response.json["error"])
        self.assertEqual([], response.json["artifacts"])

    def test_signout_ends_session(self):
        self.register()
        self.assertEqual(200, self.client.post("/api/signout").status_code)
        self.assertEqual("signed_out", self.client.get("/api/state").json["state"])

    def test_oauth_callback_resolves_state_and_finishes_connection(self):
        self.register()
        store = self.app.extensions["cordia_store"]
        state = store.create_oauth_state(1, "google_drive")

        response = self.client.get(
            "/api/connectors/oauth/callback", query_string={"state": state, "code": "code"}
        )

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.location.endswith("/?connected=google_drive"))
        self.assertEqual("google_drive", self.runtime.finished[0][1])

    def test_oauth_denial_does_not_attempt_token_exchange(self):
        self.register()
        store = self.app.extensions["cordia_store"]
        state = store.create_oauth_state(1, "google_drive")

        response = self.client.get(
            "/api/connectors/oauth/callback",
            query_string={"state": state, "error": "access_denied"},
        )

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.location.endswith("/?error=oauth_denied"))
        self.assertEqual([], self.runtime.finished)


if __name__ == "__main__":
    unittest.main()
