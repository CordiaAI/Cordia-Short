import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from cordia.agent import Agent
from cordia.connectors import CONNECTORS
from cordia.connector_runtime import ConnectorRuntime
from cordia.store import Store
from tests.test_app import RecordingWorkspaceClient


def valid_part_one_payload():
    return {"answers": {f"p1_{number:02d}": 3 for number in range(1, 21)}}


def valid_part_two_payload():
    return {
        "domains": ["technology_software"],
        "ratings": {"technology_software": 4},
        "familiarity": {
            "technology_software": {
                "cloud storage": "familiar",
                "two-factor authentication": "familiar",
                "adaptive port throttling": "not_familiar",
                "browser cache": "familiar",
                "API": "familiar",
            }
        },
    }


def valid_part_three_payload():
    return {
        "briefing_style": "requirements_upfront",
        "reply_preference": "literal_narrow",
        "most": "logical",
        "least": "imaginative",
        "flawed_plan": "state_plainly",
        "answer_order": "reasoning_first",
        "background_assumption": "spell_out_background",
        "edit_boundary": "only_requested_edits",
        "bad_idea": "say_so_directly",
    }


def valid_part_four_payload():
    return {
        "request_1": "Help me plan today.",
        "request_2": "Review this project outline.",
        "request_3": "",
    }


def valid_discovery_payload():
    return {
        "outcome": "Publish a weekly project status report.",
        "success_criteria": "The report is ready every Friday.",
        "current_workflow": "I collect notes and write the report manually.",
        "applications": [
            {
                "application_id": "google_drive",
                "name": "Google Drive",
                "already_uses": True,
                "wants_added": True,
                "current_activities": "Store weekly notes.",
                "desired_activities": "Collect the source notes.",
                "inputs_outputs": "Notes in, report draft out.",
                "control_level": "prepare_for_approval",
            }
        ],
        "inputs": "Weekly notes.",
        "outputs": "A status report.",
        "control_level": "prepare_for_approval",
        "first_workspace": "A report drafting workspace.",
    }


def complete_onboarding_payloads():
    return dict((
        ("assessment_part_1", valid_part_one_payload()),
        ("assessment_part_2", valid_part_two_payload()),
        ("assessment_part_3", valid_part_three_payload()),
        ("assessment_part_4", valid_part_four_payload()),
        ("workspace_discovery", valid_discovery_payload()),
    ))


def save_all_stages(store, user_id):
    for stage, payload in complete_onboarding_payloads().items():
        store.save_onboarding_stage(user_id, stage, payload)


def complete_all_stages(store):
    user_id = store.register("complete@example.com", "correct-horse-battery")
    save_all_stages(store, user_id)
    return user_id


class StoreJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = root / "cordia.db"
        self.store = Store(self.db_path, root / "workspaces")

    def tearDown(self):
        self.temp.cleanup()

    def test_onboarding_stage_round_trips_as_validated_json(self):
        user_id = self.store.register("person@example.com", "correct-horse-battery")

        saved = self.store.save_onboarding_stage(
            user_id, "assessment_part_1", valid_part_one_payload()
        )

        self.assertEqual(2, saved["schema_version"])
        self.assertEqual(saved, self.store.onboarding_stages(user_id)["assessment_part_1"])

    def test_onboarding_resumes_first_incomplete_stage(self):
        user_id = self.store.register("person@example.com", "correct-horse-battery")
        self.store.save_onboarding_stage(user_id, "assessment_part_1", valid_part_one_payload())

        state = self.store.onboarding_state(user_id)

        self.assertEqual("assessment_part_2", state["current_stage"])
        self.assertEqual(["assessment_part_1"], state["completed_stages"])

    def test_onboarding_treats_malformed_saved_stage_as_incomplete(self):
        user_id = self.store.register("person@example.com", "correct-horse-battery")
        self.store.save_onboarding_stage(user_id, "assessment_part_1", valid_part_one_payload())
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "INSERT INTO survey_answers(user_id, field, value) VALUES (?, ?, ?)",
                (user_id, "assessment_part_2", "not-json"),
            )
            connection.commit()

        state = self.store.onboarding_state(user_id)

        self.assertEqual("assessment_part_2", state["current_stage"])
        self.assertNotIn("assessment_part_2", state["answers"])

    def test_onboarding_rejects_later_stage_and_computed_stage_writes(self):
        user_id = self.store.register("person@example.com", "correct-horse-battery")

        with self.assertRaisesRegex(ValueError, "complete assessment_part_1 first"):
            self.store.save_onboarding_stage(
                user_id, "assessment_part_2", valid_part_two_payload()
            )
        with self.assertRaisesRegex(ValueError, "unknown onboarding stage"):
            self.store.save_onboarding_stage(user_id, "profile_snapshot", {})

        self.assertNotIn("profile_snapshot", self.store.survey_answers(user_id))

    def test_completion_atomically_installs_three_files_and_preserves_runtime_state(self):
        user_id = complete_all_stages(self.store)
        self.store.add_message(user_id, "user", "Make this more direct.")
        response_id = self.store.add_message(
            user_id, "assistant", "Here is the report plan.", kind="agent"
        )
        self.store.adjust_operator(user_id, response_id, "directness", 1, "Be more direct")
        artifact_id = self.store.save_artifact(
            user_id,
            {
                "type": "table",
                "title": "Existing work",
                "columns": ["name"],
                "rows": [["Plan.md"]],
                "source": "google_drive",
            },
        )
        self.store.save_connection(
            user_id, "google_drive", "verified", {"access_token": "encrypted"}
        )

        documents = self.store.complete_onboarding(user_id, CONNECTORS)

        workspace = self.store.workspace_root / str(user_id)
        self.assertEqual(documents["operator.md"], (workspace / "operator.md").read_text(encoding="utf-8"))
        self.assertTrue((workspace / "connectors.md").exists())
        self.assertTrue((workspace / "fde.md").exists())
        self.assertEqual("verified", self.store.connection_status(user_id, "google_drive"))
        self.assertEqual(artifact_id, self.store.artifacts(user_id)[0]["id"])
        self.assertTrue(self.store.survey_complete(user_id))

    def test_completion_write_failure_preserves_existing_files_and_incomplete_state(self):
        user_id = complete_all_stages(self.store)
        workspace = self.store.workspace_root / str(user_id)
        workspace.mkdir(parents=True, exist_ok=True)
        before = {
            "operator.md": b"legacy operator\n",
            "connectors.md": b"legacy connectors\n",
            "fde.md": b"legacy fde\n",
        }
        for name, contents in before.items():
            (workspace / name).write_bytes(contents)
        original_write_text = Path.write_text
        temporary_writes = 0

        def fail_third_temporary_write(path, contents, *args, **kwargs):
            nonlocal temporary_writes
            if path.parent.name.startswith(".onboarding-"):
                temporary_writes += 1
                if temporary_writes == 3:
                    raise OSError("disk full")
            return original_write_text(path, contents, *args, **kwargs)

        with patch.object(Path, "write_text", new=fail_third_temporary_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.store.complete_onboarding(user_id, CONNECTORS)

        self.assertEqual(before, {name: (workspace / name).read_bytes() for name in before})
        self.assertFalse(self.store.survey_complete(user_id))
        self.assertEqual("workspace_review", self.store.onboarding_state(user_id)["current_stage"])

    def test_completion_replacement_failure_restores_preexisting_files(self):
        user_id = complete_all_stages(self.store)
        workspace = self.store.workspace_root / str(user_id)
        workspace.mkdir(parents=True, exist_ok=True)
        before = {
            "operator.md": b"legacy operator\n",
            "connectors.md": b"legacy connectors\n",
            "fde.md": b"legacy fde\n",
        }
        for name, contents in before.items():
            (workspace / name).write_bytes(contents)
        original_replace = Path.replace

        def fail_connector_replacement(path, target):
            if path.parent.name.startswith(".onboarding-") and path.name == "connectors.md":
                raise OSError("replace failed")
            return original_replace(path, target)

        with patch.object(Path, "replace", new=fail_connector_replacement):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.store.complete_onboarding(user_id, CONNECTORS)

        self.assertEqual(before, {name: (workspace / name).read_bytes() for name in before})
        self.assertFalse(self.store.survey_complete(user_id))

    def test_completion_marker_failure_restores_preexisting_files_and_incomplete_state(self):
        user_id = complete_all_stages(self.store)
        workspace = self.store.workspace_root / str(user_id)
        workspace.mkdir(parents=True, exist_ok=True)
        before = {
            "operator.md": b"legacy operator\n",
            "connectors.md": b"legacy connectors\n",
            "fde.md": b"legacy fde\n",
        }
        for name, contents in before.items():
            (workspace / name).write_bytes(contents)

        with patch.object(self.store, "_save_survey_value", side_effect=OSError("database down")):
            with self.assertRaisesRegex(OSError, "database down"):
                self.store.complete_onboarding(user_id, CONNECTORS)

        self.assertEqual(before, {name: (workspace / name).read_bytes() for name in before})
        self.assertNotIn("survey_schema_version", self.store.survey_answers(user_id))
        self.assertFalse(self.store.survey_complete(user_id))

    def test_staging_failure_never_rewrites_existing_destinations(self):
        user_id = complete_all_stages(self.store)
        workspace = self.store.workspace_root / str(user_id)
        workspace.mkdir(parents=True, exist_ok=True)
        before = {
            "operator.md": b"legacy operator\n",
            "connectors.md": b"legacy connectors\n",
            "fde.md": b"legacy fde\n",
        }
        for name, contents in before.items():
            (workspace / name).write_bytes(contents)
        original_write_text = Path.write_text
        original_write_bytes = Path.write_bytes
        temporary_writes = 0
        destination_writes = []

        def fail_third_temporary_write(path, contents, *args, **kwargs):
            nonlocal temporary_writes
            if path.parent.name.startswith(".onboarding-"):
                temporary_writes += 1
                if temporary_writes == 3:
                    raise OSError("disk full")
            return original_write_text(path, contents, *args, **kwargs)

        def reject_destination_rewrite(path, contents, *args, **kwargs):
            if path.parent == workspace:
                destination_writes.append(path)
                raise AssertionError("staging failure rewrote a destination")
            return original_write_bytes(path, contents, *args, **kwargs)

        with patch.object(Path, "write_text", new=fail_third_temporary_write):
            with patch.object(Path, "write_bytes", new=reject_destination_rewrite):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.store.complete_onboarding(user_id, CONNECTORS)

        self.assertEqual([], destination_writes)
        self.assertEqual(before, {name: (workspace / name).read_bytes() for name in before})

    def test_completion_marker_requires_every_stage_to_remain_valid(self):
        user_id = complete_all_stages(self.store)
        self.store.complete_onboarding(user_id, CONNECTORS)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE survey_answers SET value = ? WHERE user_id = ? AND field = ?",
                ("not-json", user_id, "assessment_part_2"),
            )
            connection.commit()

        self.assertFalse(self.store.survey_complete(user_id))
        self.assertEqual("assessment_part_2", self.store.onboarding_state(user_id)["current_stage"])

    def test_completed_onboarding_keeps_compiled_profile_for_legacy_writes_and_adjustments(self):
        user_id = complete_all_stages(self.store)
        documents = self.store.complete_onboarding(user_id, CONNECTORS)
        self.store.save_survey_answer(user_id, "name", "Legacy overwrite attempt")

        self.assertEqual(documents["operator.md"], self.store.operator_markdown(user_id))
        self.store.add_message(user_id, "user", "Make this more direct.")
        response_id = self.store.add_message(
            user_id, "assistant", "Here is the report plan.", kind="agent"
        )
        self.store.adjust_operator(user_id, response_id, "directness", 1, "Be more direct")

        operator = self.store.operator_markdown(user_id)
        self.assertIn("# Cordia operator profile", operator)
        self.assertIn("## Human-facing profile summary", operator)
        self.assertIn(f"Response {response_id}: Be more direct", operator)
        self.assertNotIn("# Operator profile\n", operator)

    def test_agent_context_supersedes_connection_snapshots_without_rewriting_user_content(self):
        user_id = complete_all_stages(self.store)
        self.store.complete_onboarding(user_id, CONNECTORS)
        response_id = self.store.add_message(user_id, "assistant", "A plan.", kind="agent")
        self.store.adjust_operator(user_id, response_id, "context", 1, "Infer context")
        workspace = self.store.workspace_root / str(user_id)
        for name in ("operator.md", "connectors.md", "fde.md"):
            path = workspace / name
            path.write_text(path.read_text(encoding="utf-8") + "\nUser-authored workflow clarification.\n", encoding="utf-8")
        before = {name: (workspace / name).read_bytes() for name in ("operator.md", "connectors.md", "fde.md")}

        # Real Store transitions using disposable test data, not provider verification.
        for status in ("verified", "needs_attention", "verified"):
            with self.subTest(status=status):
                self.store.save_connection(user_id, "google_drive", status, {})
                context = self.store.agent_context(user_id)
                self.assertIn("## Current runtime connection status", context)
                current = context.split("## Current runtime connection status", 1)[1]
                self.assertIn("supersede", current)
                self.assertIn("connectors.md", current)
                self.assertIn("fde.md", current)
                self.assertIn(f"Google Drive (google_drive): {status}", current)
                self.assertIn(f"Response {response_id}: Infer context", context)
                self.assertEqual(3, context.count("User-authored workflow clarification."))
                self.assertEqual(before, {name: (workspace / name).read_bytes() for name in before})

    def test_agent_context_downgrades_a_verified_completion_snapshot(self):
        user_id = complete_all_stages(self.store)
        self.store.save_connection(user_id, "google_drive", "verified", {})
        self.store.complete_onboarding(user_id, CONNECTORS)
        self.store.save_connection(user_id, "google_drive", "needs_attention", {})

        context = self.store.agent_context(user_id)

        self.assertIn("## Current runtime connection status", context)
        current = context.split("## Current runtime connection status", 1)[1]
        self.assertIn("Google Drive (google_drive): needs_attention", current)
        self.assertNotIn(": verified", current)

    def test_agent_context_current_status_is_user_scoped_and_defaults_to_setup_required(self):
        user_id = complete_all_stages(self.store)
        other_user = self.store.register("other@example.com", "correct-horse-battery")
        self.store.save_connection(other_user, "google_drive", "verified", {})
        self.store.complete_onboarding(user_id, CONNECTORS)

        context = self.store.agent_context(user_id)

        self.assertIn("## Current runtime connection status", context)
        current = context.split("## Current runtime connection status", 1)[1]
        self.assertIn("Google Drive (google_drive): setup_required", current)
        self.assertNotIn(": verified", current)
        self.assertIn("historical snapshots", context)

    def test_explicit_feedback_recompiles_guidance_for_effective_axis(self):
        user_id = complete_all_stages(self.store)
        self.store.complete_onboarding(user_id, CONNECTORS)
        response_id = self.store.add_message(user_id, "assistant", "A plan.", kind="agent")
        self.assertIn("Explain the reasoning before", self.store.operator_markdown(user_id))
        for expected in ("Pair the answer with a brief rationale", "Give the answer or proposed next step first"):
            self.store.adjust_operator(user_id, response_id, "implementation", 1, "Answer first")
            operator = self.store.operator_markdown(user_id)
            self.assertIn(expected, operator)
            self.assertNotIn("Explain the reasoning before", operator)
            self.assertIn("assessment_part_3.answer_order=reasoning_first", operator)

    def test_legacy_adjustment_keeps_legacy_operator_rendering(self):
        user_id = self.store.register("legacy@example.com", "correct-horse-battery")
        self.store.save_survey_answer(user_id, "name", "Jordan")
        self.store.add_message(user_id, "user", "Make this more direct.")
        response_id = self.store.add_message(
            user_id, "assistant", "Here is the report plan.", kind="agent"
        )

        self.store.adjust_operator(user_id, response_id, "directness", 1, "Be more direct")

        self.assertIn("# Operator profile", self.store.operator_markdown(user_id))

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
        self.assertTrue(self.store.legacy_survey_complete(user_id))
        self.assertFalse(self.store.survey_complete(user_id))

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

    def test_repeated_connector_operation_updates_one_artifact_window(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        first = {
            "type": "table",
            "title": "Recent files",
            "columns": ["Name"],
            "rows": [["First.md"]],
            "source": "google_drive",
            "operation_id": "list_recent_files",
        }
        updated = {**first, "rows": [["Updated.md"]]}

        first_id = self.store.save_artifact(user_id, first)
        updated_id = self.store.save_artifact(user_id, updated)

        artifacts = self.store.artifacts(user_id)
        self.assertEqual(first_id, updated_id)
        self.assertEqual(1, len(artifacts))
        self.assertEqual("Updated.md", artifacts[0]["rows"][0][0])

        second_id = self.store.save_artifact(
            user_id,
            {**first, "title": "Search results", "operation_id": "search_files"},
        )
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(2, len(self.store.artifacts(user_id)))

    def test_current_operation_replaces_matching_legacy_artifact_window(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        legacy_id = self.store.save_artifact(
            user_id,
            {
                "type": "table",
                "title": "Recent Google Drive files",
                "columns": ["Name"],
                "rows": [["Old.md"]],
                "source": "google_drive",
            },
        )

        current_id = self.store.save_artifact(
            user_id,
            {
                "type": "table",
                "title": "Recent Google Drive files",
                "columns": ["Name"],
                "rows": [["Current.md"]],
                "source": "google_drive",
                "operation_id": "list_recent_files",
            },
        )

        artifacts = self.store.artifacts(user_id)
        self.assertEqual(legacy_id, current_id)
        self.assertEqual(1, len(artifacts))
        self.assertEqual("Current.md", artifacts[0]["rows"][0][0])

    def test_existing_legacy_and_current_rows_render_as_one_window(self):
        user_id = self.store.register("person@example.com", "correct horse battery")
        legacy = {
            "type": "table",
            "title": "Recent Google Drive files",
            "columns": ["Name"],
            "rows": [["Old.md"]],
            "source": "google_drive",
        }
        current = {
            **legacy,
            "rows": [["Current.md"]],
            "operation_id": "list_recent_files",
        }
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "INSERT INTO artifacts(user_id, payload, created_at) VALUES (?, ?, ?)",
                (user_id, json.dumps(legacy), "2026-08-26T10:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO artifacts(user_id, payload, created_at) VALUES (?, ?, ?)",
                (user_id, json.dumps(current), "2026-08-27T10:00:00+00:00"),
            )
            connection.commit()

        artifacts = self.store.artifacts(user_id)
        self.assertEqual(1, len(artifacts))
        self.assertEqual("Current.md", artifacts[0]["rows"][0][0])


class OnboardingServiceJourneyTests(unittest.TestCase):
    """Real API/Store/compiler/Agent; model transport and workspace MCP are doubles."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.model_requests = []
        self.workspace = RecordingWorkspaceClient()
        agent = Agent("test-model-key", transport=self.model_transport)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "cordia.db",
                "WORKSPACE_ROOT": root / "workspaces",
                "SESSION_COOKIE_SECURE": False,
            },
            agent=agent,
            workspace_client=self.workspace,
        )
        self.store = self.app.extensions["cordia_store"]
        self.workspace.store = self.store
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def model_transport(self, url, headers, payload, timeout):
        self.model_requests.append(payload)
        connecting = "connect" in payload["input"][-1]["content"].lower()
        return {"output_text": json.dumps({
            "action": "propose_connector" if connecting else "speak",
            "message": "Authorize Google Drive in the setup card." if connecting else "Review the report plan.",
            "connector_id": "google_drive" if connecting else None,
            "operation_id": None,
        })}

    def register_and_complete(self):
        registered = self.client.post("/api/register", json={
            "email": "journey@example.com", "password": "correct-horse-battery",
        })
        self.assertEqual(201, registered.status_code)
        self.assertEqual("onboarding", registered.json["state"])
        return self.complete_via_api()

    def complete_via_api(self):
        for stage, payload in complete_onboarding_payloads().items():
            saved = self.client.put(f"/api/onboarding/{stage}", json=payload)
            self.assertEqual(200, saved.status_code, saved.json)
        self.assertEqual([], self.model_requests)
        self.assertEqual([], self.workspace.calls)
        completed = self.client.post("/api/onboarding/complete")
        self.assertEqual(200, completed.status_code, completed.json)
        self.assertEqual("workspace", completed.json["state"])
        self.assertEqual([], self.model_requests)
        self.assertEqual([], self.workspace.calls)
        return completed.json

    def test_register_to_compiled_workspace_to_connector_proposal(self):
        completed = self.register_and_complete()
        workspace = Path(self.temp.name) / "workspaces" / "1"
        documents = {name: (workspace / name).read_text(encoding="utf-8")
                     for name in ("operator.md", "connectors.md", "fde.md")}
        self.assertIn("Prompt examples", documents["operator.md"])
        self.assertIn("Help me plan today.", documents["operator.md"])
        self.assertIn("Google Drive", documents["connectors.md"])
        self.assertIn("Status: setup_required", documents["connectors.md"])
        self.assertIn("Smallest valuable workspace slice", documents["fde.md"])
        self.assertIsNone(completed["setup_card"])
        self.assertEqual("setup_required", completed["selected_applications"][0]["status"])
        self.assertIsNone(self.store.connection_status(1, "google_drive"))
        self.assertIsNone(self.store.connection_credentials(1, "google_drive"))

        chat = self.client.post("/api/chat", json={"message": "Connect Google Drive"})

        self.assertEqual(200, chat.status_code, chat.json)
        self.assertEqual("google_drive", chat.json["setup_card"]["connector_id"])
        self.assertEqual("oauth_redirect", chat.json["setup_card"]["type"])
        self.assertTrue(chat.json["setup_card"]["action_url"].startswith("https://accounts.google.com/"))
        self.assertEqual(chat.json["setup_card"], self.client.get("/api/state").json["setup_card"])
        self.assertEqual([(1, "connector_start", {"connector_id": "google_drive"})], self.workspace.calls)
        self.assertEqual(1, len(self.model_requests))
        model_context = "\n".join(item["content"] for item in self.model_requests[0]["input"] if item["role"] == "developer")
        for document in documents.values():
            self.assertIn(document, model_context)
        self.assertIsNone(self.store.connection_status(1, "google_drive"))
        self.assertIsNone(self.store.connection_credentials(1, "google_drive"))

    def test_legacy_migration_preserves_runtime_records_and_explicit_override(self):
        user_id = self.store.register("legacy@example.com", "correct-horse-battery")
        for field, value in {"name": "Jordan", "role": "Operator", "goal": "Weekly reports", "apps": "Google Drive", "communication": "Direct"}.items():
            self.store.save_survey_answer(user_id, field, value)
        self.store.add_message(user_id, "user", "Use more context.")
        response_id = self.store.add_message(user_id, "assistant", "Review the report plan.", kind="agent")
        self.store.adjust_operator(user_id, response_id, "context", 1, "Use more context")
        self.store.save_artifact(user_id, {"type": "table", "title": "Existing work", "columns": ["Name"], "rows": [["Plan.md"]], "source": "google_drive"})
        self.store.save_connection(user_id, "google_drive", "verified", {"access_token": "legacy-drive-token"})
        self.store.save_connection(user_id, "openai_api", "verified", {"api_key": "legacy-model-key"})
        self.store.save_connection_setting(user_id, "openai_api", "model", "gpt-5-mini")
        self.store.save_connection_setting(user_id, "__runtime__", "agent_model", "openai_api")
        tables = ("messages", "operator_adjustments", "operator_profiles", "artifacts", "connections", "connection_settings")
        with closing(sqlite3.connect(self.store.db_path)) as connection:
            before = {table: connection.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)).fetchall() for table in tables}

        logged_in = self.client.post("/api/signin", json={"email": "legacy@example.com", "password": "correct-horse-battery"})
        self.assertEqual(200, logged_in.status_code)
        self.assertEqual("onboarding", logged_in.json["state"])
        self.assertEqual(2, logged_in.json["onboarding"]["schema_version"])
        self.assertEqual("assessment_part_1", logged_in.json["onboarding"]["current_stage"])
        completed = self.complete_via_api()

        with closing(sqlite3.connect(self.store.db_path)) as connection:
            after = {table: connection.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)).fetchall() for table in tables}
        self.assertEqual(before, after)
        self.assertEqual("Jordan", self.store.survey_answers(user_id)["name"])
        self.assertEqual({"provider": "OpenAI API", "model": "gpt-5-mini", "source": "connector"}, completed["agent_runtime"])
        self.assertEqual("verified", completed["selected_applications"][0]["status"])
        operator = self.store.operator_markdown(user_id)
        self.assertIn("Context interpretation: Implicit / high-context (1)", operator)
        self.assertIn(f"Response {response_id}: Use more context", operator)
        self.assertIn("Scope preference: Detail-first (-1)", operator)
        self.assertEqual({"context": 1, "scope": -1, "directness": 1, "implementation": -1}, self.store.operator_profile(user_id))
        connectors = (self.store.workspace_root / str(user_id) / "connectors.md").read_text(encoding="utf-8")
        self.assertIn("Status: verified", connectors)
        self.assertNotIn("legacy-drive-token", connectors)
        self.assertNotIn("legacy-model-key", json.dumps(completed))

    def test_first_feedback_steps_from_survey_baseline_and_retry_receives_effective_axes(self):
        self.register_and_complete()
        original = self.client.post("/api/chat", json={"message": "Plan my report"})
        response_id = original.json["messages"][-1]["id"]
        self.assertIn("Context interpretation: Explicit / literal (-1)", original.json["operator"])

        adjusted = self.client.post(f"/api/responses/{response_id}/adjust", json={"axis": "context", "target": 1})

        self.assertEqual(200, adjusted.status_code, adjusted.json)
        self.assertEqual(-1, adjusted.json["adjustment"]["previous"])
        self.assertEqual(0, adjusted.json["adjustment"]["current"])
        self.assertEqual(0, self.store.operator_profile(1)["context"])
        self.assertIn("Context interpretation: Balanced (0)", adjusted.json["operator"])
        self.assertIn("Context interpretation: Balanced (0)", self.model_requests[-1]["input"][2]["content"])
        self.assertEqual("Plan my report", self.model_requests[-1]["input"][-1]["content"])
        for previous, current in ((0, 1), (1, 1)):
            followup = self.client.post(f"/api/responses/{response_id}/adjust", json={"axis": "context", "target": 1})
            self.assertEqual(200, followup.status_code, followup.json)
            self.assertEqual((previous, current), (followup.json["adjustment"]["previous"], followup.json["adjustment"]["current"]))

    def test_feedback_on_older_response_wins_by_adjustment_chronology(self):
        self.register_and_complete()
        older = self.client.post("/api/chat", json={"message": "Plan my report"}).json["messages"][-1]["id"]
        newer = self.client.post("/api/chat", json={"message": "Review my report"}).json["messages"][-1]["id"]
        for response_id, target, previous, current in ((older, 1, 1, 1), (newer, -1, 1, 0), (older, -1, 0, -1)):
            adjusted = self.client.post(f"/api/responses/{response_id}/adjust", json={"axis": "directness", "target": target})
            self.assertEqual(200, adjusted.status_code, adjusted.json)
            self.assertEqual((previous, current), (adjusted.json["adjustment"]["previous"], adjusted.json["adjustment"]["current"]))

        self.assertEqual(-1, adjusted.json["adjustment"]["current"])
        self.assertIn("Directness preference: Measured / indirect (-1)", adjusted.json["operator"])
        self.assertEqual(-1, self.store.operator_profile(1)["directness"])
        self.assertIn("Directness preference: Measured / indirect (-1)", self.model_requests[-1]["input"][2]["content"])
        self.store.complete_onboarding(1, CONNECTORS)
        self.assertEqual(adjusted.json["operator"], self.store.operator_markdown(1))


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
        for stage, payload in complete_onboarding_payloads().items():
            self.assertEqual(200, self.client.put(f"/api/onboarding/{stage}", json=payload).status_code)
        self.assertEqual(200, self.client.post("/api/onboarding/complete").status_code)

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
