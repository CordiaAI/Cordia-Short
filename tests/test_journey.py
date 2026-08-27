import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import create_app
from cordia.connector_runtime import ConnectorRuntime
from cordia.store import Store


class StoreJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = root / "cordia.db"
        self.store = Store(self.db_path, root / "workspaces")

    def tearDown(self):
        self.temp.cleanup()

    def test_register_authenticate_and_session_ownership(self):
        user_id = self.store.register(" Person@Example.com ", "correct horse battery")

        self.assertEqual(user_id, self.store.authenticate("person@example.com", "correct horse battery"))
        self.assertIsNone(self.store.authenticate("person@example.com", "wrong password"))

        token = self.store.create_session(user_id)
        self.assertEqual(user_id, self.store.user_for_session(token))
        self.assertIsNone(self.store.user_for_session("not-a-session"))

        with closing(sqlite3.connect(self.db_path)) as connection:
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()[0]
        self.assertNotIn("correct horse battery", password_hash)

    def test_duplicate_email_is_rejected(self):
        self.store.register("person@example.com", "correct horse battery")

        with self.assertRaisesRegex(ValueError, "already registered"):
            self.store.register("PERSON@example.com", "another password")

    def test_connector_setting_is_scoped_to_user_and_connector(self):
        first_user = self.store.register("first@example.com", "correct horse battery")
        second_user = self.store.register("second@example.com", "correct horse battery")

        self.store.save_connection_setting(first_user, "openai_api", "model", "gpt-5-mini")

        self.assertEqual(
            "gpt-5-mini",
            self.store.connection_setting(first_user, "openai_api", "model"),
        )
        self.assertIsNone(self.store.connection_setting(second_user, "openai_api", "model"))
        self.assertIsNone(self.store.connection_setting(first_user, "google_drive", "model"))

    def test_survey_answers_write_readable_ordered_operator_profile(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        self.store.save_survey_answer(user_id, "name", "Jordan")
        self.store.save_survey_answer(user_id, "role", "Operations lead")
        self.store.save_survey_answer(user_id, "goal", "Find client documents quickly")
        self.store.save_survey_answer(user_id, "apps", "Google Drive, Slack")
        self.store.save_survey_answer(user_id, "communication", "Big picture first")

        operator = self.store.operator_markdown(user_id)

        self.assertIn("# Operator profile", operator)
        self.assertLess(operator.index("## Name"), operator.index("## Role"))
        self.assertIn("Google Drive, Slack", operator)
        self.assertIn("Context interpretation: Balanced (0)", operator)
        self.assertIn("Implementation preference: Balanced (0)", operator)
        operator_path = Path(self.temp.name) / "workspaces" / str(user_id) / "operator.md"
        self.assertEqual(operator, operator_path.read_text(encoding="utf-8"))
        self.assertFalse((operator_path.parent / "memory.md").exists())
        self.assertTrue(self.store.survey_complete(user_id))

    def test_response_correction_moves_one_ternary_coordinate_and_records_evidence(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        self.store.add_message(user_id, "user", "Give me the plan.")
        response_id = self.store.add_message(
            user_id, "assistant", "Here is a conceptual overview.", kind="agent"
        )

        result = self.store.adjust_operator(
            user_id,
            response_id=response_id,
            axis="implementation",
            target=1,
            label="Give me the implementation",
        )

        self.assertEqual(0, result["previous"])
        self.assertEqual(1, result["current"])
        self.assertEqual(1, self.store.operator_profile(user_id)["implementation"])
        operator = self.store.operator_markdown(user_id)
        self.assertIn("Implementation preference: Implementation-first (1)", operator)
        self.assertIn(f"Response {response_id}", operator)
        self.assertIn('User selected “Give me the implementation.”', operator)

    def test_response_correction_moves_toward_the_selected_endpoint_and_clamps(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        self.store.add_message(user_id, "user", "Give me the plan.")
        response_id = self.store.add_message(
            user_id, "assistant", "Here is a response.", kind="agent"
        )

        self.store.adjust_operator(user_id, response_id, "scope", 1, "Show the bigger picture")
        clamped = self.store.adjust_operator(
            user_id, response_id, "scope", 1, "Show the bigger picture"
        )
        balanced = self.store.adjust_operator(
            user_id, response_id, "scope", -1, "Focus on the details"
        )

        self.assertEqual(1, clamped["current"])
        self.assertEqual(0, balanced["current"])

    def test_response_correction_rejects_invalid_axis_target_and_foreign_response(self):
        first_user = self.store.register("first@example.com", "correct horse battery")
        second_user = self.store.register("second@example.com", "correct horse battery")
        self.store.add_message(second_user, "user", "Help me.")
        foreign_response = self.store.add_message(
            second_user, "assistant", "Of course.", kind="agent"
        )

        with self.assertRaisesRegex(ValueError, "unknown operator axis"):
            self.store.adjust_operator(first_user, foreign_response, "tone", 1, "Be direct")
        with self.assertRaisesRegex(ValueError, "target must be -1 or 1"):
            self.store.adjust_operator(first_user, foreign_response, "directness", 0, "Balanced")
        with self.assertRaisesRegex(LookupError, "assistant response not found"):
            self.store.adjust_operator(
                first_user, foreign_response, "directness", 1, "Be more direct"
            )

    def test_conversation_continues_and_artifacts_persist(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        self.store.add_message(user_id, "user", "I use Google Drive.")
        self.store.add_message(user_id, "assistant", "I can help connect it.")

        messages = self.store.messages(user_id)
        self.assertEqual(
            [("user", "I use Google Drive."), ("assistant", "I can help connect it.")],
            [(message["role"], message["content"]) for message in messages],
        )

        artifact_id = self.store.save_artifact(
            user_id,
            {
                "type": "table",
                "title": "Recent Drive files",
                "columns": ["name"],
                "rows": [["Plan.md"]],
                "source": "google_drive",
            },
        )
        artifacts = self.store.artifacts(user_id)
        self.assertEqual(artifact_id, artifacts[0]["id"])
        self.assertEqual("Plan.md", artifacts[0]["rows"][0][0])


class ScriptedConnectorAgent:
    def respond(self, memory, messages):
        if "connect" in messages[-1]["content"].lower():
            return {
                "action": "propose_connector",
                "message": "Google Drive is ready for authorization.",
                "connector_id": "google_drive",
                "operation_id": None,
            }
        return {
            "action": "run_operation",
            "message": "I added your recent Drive files to the workspace.",
            "connector_id": "google_drive",
            "operation_id": "list_recent_files",
        }


class RealMCPConnectorJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.calls = []
        env = {
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "CORDIA_BASE_URL": "http://localhost",
        }
        store = Store(root / "cordia.db", root / "workspaces")
        runtime = ConnectorRuntime(store, env=env, transport=self.transport)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "cordia.db",
                "WORKSPACE_ROOT": root / "workspaces",
                "SESSION_COOKIE_SECURE": False,
            },
            agent=ScriptedConnectorAgent(),
            connector_runtime=runtime,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, method, url, headers, data, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "data": data})
        if url == "https://oauth2.googleapis.com/token":
            return {
                "access_token": "provider-access-token",
                "refresh_token": "provider-refresh-token",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
                "token_type": "Bearer",
            }
        if url.startswith("https://www.googleapis.com/drive/v3/files"):
            return {
                "files": [
                    {
                        "id": "file-1",
                        "name": "Plan.md",
                        "mimeType": "text/markdown",
                        "modifiedTime": "2026-08-25T12:00:00Z",
                        "webViewLink": "https://drive.google.com/file-1",
                    }
                ]
            }
        raise AssertionError(f"unexpected request: {method} {url}")

    def test_google_oauth_to_mcp_operation_creates_provider_derived_artifact(self):
        register = self.client.post(
            "/api/register",
            json={"email": "person@example.com", "password": "correct horse battery"},
        )
        self.assertEqual(201, register.status_code)
        for answer in [
            "Jordan",
            "Operations lead",
            "Find documents",
            "Google Drive",
            "Big picture first",
        ]:
            self.assertEqual(200, self.client.post("/api/survey", json={"answer": answer}).status_code)

        setup = self.client.post("/api/chat", json={"message": "Connect Google Drive"})
        state = parse_qs(urlparse(setup.json["setup_card"]["action_url"]).query)["state"][0]
        callback = self.client.get(
            "/api/connectors/oauth/callback", query_string={"state": state, "code": "real-code"}
        )
        operation = self.client.post("/api/chat", json={"message": "Show recent Drive files"})

        self.assertEqual(302, callback.status_code)
        self.assertEqual(200, operation.status_code)
        self.assertEqual("Plan.md", operation.json["artifact"]["rows"][0][0])
        self.assertEqual("Plan.md", operation.json["artifacts"][0]["rows"][0][0])
        serialized = json.dumps(operation.json)
        self.assertNotIn("provider-access-token", serialized)
        self.assertNotIn("provider-refresh-token", serialized)
        self.assertGreaterEqual(
            len([call for call in self.calls if "/drive/v3/files" in call["url"]]), 2
        )


if __name__ == "__main__":
    unittest.main()
