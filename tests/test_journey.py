import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

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

    def test_survey_answers_write_readable_ordered_memory(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        self.store.save_survey_answer(user_id, "name", "Jordan")
        self.store.save_survey_answer(user_id, "role", "Operations lead")
        self.store.save_survey_answer(user_id, "goal", "Find client documents quickly")
        self.store.save_survey_answer(user_id, "apps", "Google Drive, Slack")
        self.store.save_survey_answer(user_id, "communication", "Big picture first")

        memory = self.store.memory_markdown(user_id)

        self.assertIn("# Workspace memory", memory)
        self.assertLess(memory.index("## Name"), memory.index("## Role"))
        self.assertIn("Google Drive, Slack", memory)
        memory_path = Path(self.temp.name) / "workspaces" / str(user_id) / "memory.md"
        self.assertEqual(memory, memory_path.read_text(encoding="utf-8"))
        self.assertTrue(self.store.survey_complete(user_id))

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


if __name__ == "__main__":
    unittest.main()
