import tempfile
import unittest
from pathlib import Path

from app import create_app


class FakeAgent:
    def respond(self, memory, messages):
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


class ApplicationJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.runtime = FakeRuntime()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "cordia.db",
                "WORKSPACE_ROOT": root / "workspaces",
                "SESSION_COOKIE_SECURE": False,
            },
            agent=FakeAgent(),
            connector_runtime=self.runtime,
        )
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
        self.assertIn("Google Drive, Slack", state["memory"])
        self.assertGreaterEqual(len(state["messages"]), 10)

        response = self.client.post("/api/chat", json={"message": "Connect Google Drive"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("oauth_redirect", response.json["setup_card"]["type"])
        self.assertEqual("workspace", response.json["state"])

    def test_agent_operation_saves_visible_artifact(self):
        self.register()
        self.complete_survey()

        response = self.client.post("/api/chat", json={"message": "Show my recent files"})

        self.assertEqual(200, response.status_code)
        self.assertEqual("Plan.md", response.json["artifact"]["rows"][0][0])
        state = self.client.get("/api/state").json
        self.assertEqual("Plan.md", state["artifacts"][0]["rows"][0][0])

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
