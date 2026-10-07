"""The same Store, AgentRuns and app journey on Postgres, as production runs them on Vercel.

Runs when CORDIA_TEST_DATABASE_URL points at a disposable Postgres database (CI starts one);
each test gets its own schema, so nothing leaks between tests.
"""

import os
import threading
import unittest
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet

DATABASE_URL = os.getenv("CORDIA_TEST_DATABASE_URL", "")

if DATABASE_URL:
    import psycopg

    from app import create_app
    from cordia.agent_runs import AgentBusy, AgentRuns
    from cordia.store import Store
    from tests.connector_fixtures import CONNECTORS
    from tests.test_app import FakeRuntime, RecordingWorkspaceClient
    from tests.test_journey import complete_all_stages, complete_onboarding_payloads


@unittest.skipUnless(DATABASE_URL, "set CORDIA_TEST_DATABASE_URL to run the Postgres suite")
class PostgresTestCase(unittest.TestCase):
    def setUp(self):
        self.schema = f"cordia_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(f"CREATE SCHEMA {self.schema}")
        separator = "&" if "?" in DATABASE_URL else "?"
        self.url = f"{DATABASE_URL}{separator}options=-csearch_path%3D{self.schema}"
        self.env = patch.dict(os.environ, {"CORDIA_VAULT_KEY": Fernet.generate_key().decode()})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(f"DROP SCHEMA {self.schema} CASCADE")


class PostgresStoreTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.url)

    def test_schema_is_created_once_and_reopening_keeps_data(self):
        user_id = self.store.register("first@example.com", "correct-horse-battery")
        reopened = Store(self.url)
        self.assertEqual(user_id, reopened.authenticate("first@example.com", "correct-horse-battery"))
        self.assertIsNone(reopened.workspace_root)
        self.assertIsNone(reopened.db_path)

    def test_accounts_sessions_and_duplicate_email(self):
        user_id = self.store.register("Person@Example.com", "correct-horse-battery")
        self.assertIsInstance(user_id, int)
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.store.register("person@example.com", "correct-horse-battery")
        token = self.store.create_session(user_id)
        self.assertEqual(user_id, self.store.user_for_session(token))
        self.store.end_session(token)
        self.assertIsNone(self.store.user_for_session(token))

    def test_rate_limits_count_and_reset_in_postgres(self):
        self.assertFalse(self.store.rate_limited("signin_email:pg@example.com", 2, 60))
        self.assertFalse(self.store.rate_limited("signin_email:pg@example.com", 2, 60))
        self.assertTrue(self.store.rate_limited("signin_email:pg@example.com", 2, 60))
        self.assertFalse(self.store.rate_limited("signin_email:pg@example.com", 2, 0))

    def test_completed_survey_writes_workspace_documents_to_postgres(self):
        user_id = complete_all_stages(self.store)
        documents = self.store.complete_onboarding(user_id, CONNECTORS)

        self.assertTrue(self.store.survey_complete(user_id))
        self.assertTrue(self.store.has_workspace_documents(user_id))
        self.assertEqual(documents["fde.md"], self.store.fde_markdown(user_id))
        self.assertEqual(documents["surveyor.md"], self.store.surveyor_markdown(user_id))
        with psycopg.connect(self.url) as connection:
            names = {row[0] for row in connection.execute(
                "SELECT name FROM workspace_documents WHERE user_id = %s", (user_id,))}
        self.assertEqual({"surveyor.md", "connectors.md", "fde.md"}, names)

    def test_failed_completion_marker_restores_documents(self):
        user_id = complete_all_stages(self.store)
        self.store._save_document(user_id, "fde.md", "previous fde\n")
        with patch.object(self.store, "_save_survey_value", side_effect=OSError("database down")):
            with self.assertRaisesRegex(OSError, "database down"):
                self.store.complete_onboarding(user_id, CONNECTORS)
        self.assertEqual("previous fde\n", self.store._document(user_id, "fde.md"))
        self.assertIsNone(self.store._document(user_id, "surveyor.md"))
        self.assertFalse(self.store.survey_complete(user_id))

    def test_missing_documents_are_recompiled_on_read(self):
        user_id = complete_all_stages(self.store)
        self.store.complete_onboarding(user_id, CONNECTORS)
        self.store._save_document(user_id, "fde.md", None)
        self.assertFalse(self.store.has_workspace_documents(user_id))
        self.assertIn("Smallest valuable workspace slice", self.store.fde_markdown(user_id))

    def test_credentials_are_encrypted_at_rest(self):
        user_id = self.store.register("vault@example.com", "correct-horse-battery")
        self.store.save_connection(user_id, "app_alpha", "verified", {"account_id": "acct-secret"})
        self.assertEqual({"account_id": "acct-secret"}, self.store.connection_credentials(user_id, "app_alpha"))
        with psycopg.connect(self.url) as connection:
            stored = connection.execute("SELECT credentials FROM connections").fetchone()[0]
        self.assertNotIn("acct-secret", stored)

    def test_generated_ids_and_single_use_oauth_state(self):
        user_id = self.store.register("ids@example.com", "correct-horse-battery")
        first = self.store.add_message(user_id, "assistant", "One.", kind="agent")
        second = self.store.add_message(user_id, "assistant", "Two.", kind="agent")
        self.assertEqual(first + 1, second)
        state = self.store.create_oauth_state(user_id, "app_alpha")
        self.assertTrue(self.store.consume_oauth_state(user_id, "app_alpha", state))
        self.assertFalse(self.store.consume_oauth_state(user_id, "app_alpha", state))

    def test_literal_percent_signs_are_stored_unchanged(self):
        user_id = self.store.register("percent@example.com", "correct-horse-battery")
        message_id = self.store.add_message(user_id, "user", "Grow revenue 20% by Q4?")
        self.assertIn("Grow revenue 20% by Q4?", [m["content"] for m in self.store.messages(user_id) if m["id"] == message_id])

    def test_vault_key_is_required(self):
        with patch.dict(os.environ, {"CORDIA_VAULT_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "CORDIA_VAULT_KEY"):
                Store(self.url)


class PostgresAgentRunTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.url)
        self.runs = AgentRuns(self.store, workspace=None, agent_for_user=lambda user_id: None)
        self.user_id = self.store.register("agent@example.com", "correct-horse-battery")

    def test_one_request_at_a_time_per_workspace(self):
        other = self.store.register("other@example.com", "correct-horse-battery")
        with self.runs.lock(self.user_id):
            outcome = {}

            def contend(user_id, key):
                try:
                    with self.runs.lock(user_id):
                        outcome[key] = "acquired"
                except AgentBusy:
                    outcome[key] = "busy"

            for user_id, key in ((self.user_id, "same"), (other, "other")):
                thread = threading.Thread(target=contend, args=(user_id, key))
                thread.start()
                thread.join()
        self.assertEqual({"same": "busy", "other": "acquired"}, outcome)
        with self.runs.lock(self.user_id):
            pass  # released when the holder finished

    def test_latest_run_and_checkpoint_tables(self):
        for index, status in enumerate(("completed", "waiting_connection")):
            with self.store._connection() as db:
                db.execute(
                    "INSERT INTO agent_runs(id,user_id,status,model,source,created_at) VALUES (?,?,?,?,?,?)",
                    (f"run-{index}", self.user_id, status, "m", "server", f"2026-10-05T00:00:0{index}+00:00"),
                )
        self.assertEqual("run-1", self.runs.latest(self.user_id)["id"])
        with self.runs._checkpointer() as saver:
            self.assertIsNone(saver.get_tuple({"configurable": {"thread_id": "missing"}}))


class PostgresAppJourneyTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.runtime = FakeRuntime()
        self.app = create_app(
            {"TESTING": True, "DATABASE": self.url, "SESSION_COOKIE_SECURE": False},
            connector_runtime=self.runtime,
            workspace_client=RecordingWorkspaceClient(),
        )
        self.client = self.app.test_client()

    def test_register_survey_and_results_without_local_files(self):
        registered = self.client.post("/api/register", json={
            "email": "journey@example.com", "password": "correct-horse-battery",
        })
        self.assertEqual(201, registered.status_code, registered.json)
        for stage, payload in complete_onboarding_payloads().items():
            saved = self.client.put(f"/api/onboarding/{stage}", json=payload)
            self.assertEqual(200, saved.status_code, saved.json)
        completed = self.client.post("/api/onboarding/complete")
        self.assertEqual(200, completed.status_code, completed.json)
        self.assertEqual("results", completed.json["state"])
        store = self.app.extensions["cordia_store"]
        self.assertTrue(store.has_workspace_documents(1))
        self.assertEqual("results", self.client.get("/api/state").json["state"])


if __name__ == "__main__":
    unittest.main()
