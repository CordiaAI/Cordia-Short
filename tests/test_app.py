import tempfile
import unittest
from pathlib import Path

from app import create_app
from cordia.connectors import CONNECTORS
from cordia.workspace_mcp import WorkspaceMCPError


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.model = "server-default"

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
        self.provider = None
        self.live_view_status = "granted"

    def start_connection(self, user_id, connector_id, requested_scopes=None):
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

    def live_view_access(self, user_id, connector_id):
        return {
            "status": self.live_view_status,
            "connector_id": connector_id,
            "connector_name": "Google Drive",
            "operation": "list_recent_files",
            "logo": "/static/assets/google-drive.png",
            "required_scopes": ["https://www.googleapis.com/auth/drive.metadata.readonly"],
            "missing_scopes": [],
            "permission": {
                "summary": "Read-only Drive view",
                "data": ["File metadata"],
                "actions": ["Refresh files"],
                "revocation": "Remove access in Google Account settings.",
                "authorize_label": "Continue with Google",
            },
        }

    def finish_connection(self, user_id, connector_id, setup_result):
        self.finished.append((user_id, connector_id, setup_result))
        return {"connector_id": connector_id, "status": "verified"}

    def select_value(self, user_id, connector_id, value):
        self.provider = {"credential": "user-secret", "model": value}
        return {"connector_id": connector_id, "setting": "model", "value": value}

    def agent_provider(self, user_id):
        return self.provider

    def agent_runtime(self, user_id):
        if not self.provider:
            return None
        return {
            "provider": "OpenAI API",
            "model": self.provider["model"],
            "source": "connector",
        }

    def decorate_artifact(self, user_id, artifact):
        if artifact.get("source") != "google_drive":
            return artifact
        return {
            **artifact,
            "connector_name": "Google Drive",
            "live_view": self.live_view_access(user_id, "google_drive"),
        }


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
                    "operation_id": arguments["operation_id"],
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
        self.agent_factory_calls = []

        def agent_factory(api_key, model):
            self.agent_factory_calls.append((api_key, model))
            return self.agent

        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "cordia.db",
                "WORKSPACE_ROOT": root / "workspaces",
                "SESSION_COOKIE_SECURE": False,
            },
            agent=self.agent,
            agent_factory=agent_factory,
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
        store = self.app.extensions["cordia_store"]
        user_id = store.authenticate("person@example.com", "correct horse battery")
        stages = (
            ("assessment_part_1", {"answers": {f"p1_{number:02d}": 3 for number in range(1, 21)}}),
            (
                "assessment_part_2",
                {
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
                },
            ),
            (
                "assessment_part_3",
                {
                    "briefing_style": "requirements_upfront",
                    "reply_preference": "literal_narrow",
                    "most": "logical",
                    "least": "imaginative",
                    "flawed_plan": "state_plainly",
                    "answer_order": "reasoning_first",
                    "background_assumption": "spell_out_background",
                    "edit_boundary": "only_requested_edits",
                    "bad_idea": "say_so_directly",
                },
            ),
            (
                "assessment_part_4",
                {
                    "request_1": "Help me plan today.",
                    "request_2": "Review this project outline.",
                    "request_3": "",
                },
            ),
            (
                "workspace_discovery",
                {
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
                },
            ),
        )
        for stage, payload in stages:
            store.save_onboarding_stage(user_id, stage, payload)
        store.complete_onboarding(user_id, CONNECTORS)

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
        self.assertIn("# Cordia operator profile", state["operator"])
        self.assertGreaterEqual(len(state["messages"]), 10)
        self.assertEqual(
            {"provider": "Cordia", "model": "server-default", "source": "server"},
            state["agent_runtime"],
        )

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
        self.assertIn("Implementation preference: Answer/action-first (1)", retried.json["operator"])
        retry_operator, retry_messages = self.agent.calls[-1]
        self.assertIn("Implementation preference: Answer/action-first (1)", retry_operator)
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
        self.assertTrue(
            response.location.endswith(
                "/?connected=google_drive&workspace_update=updated"
            )
        )
        self.assertEqual("google_drive", self.runtime.finished[0][1])
        state = self.client.get("/api/state").json
        self.assertEqual(1, len(state["artifacts"]))
        self.assertEqual("Plan.md", state["artifacts"][0]["rows"][0][0])
        self.assertEqual(
            ["connector_call", "artifact_create"],
            [call[1] for call in self.workspace.calls[-2:]],
        )
        self.assertIn("Google Drive is connected", state["messages"][-1]["content"])

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

    def test_api_key_setup_is_authenticated_and_never_echoes_secret(self):
        unauthorized = self.client.post(
            "/api/connectors/setup",
            json={"connector_id": "openai_api", "credentials": {"api_key": "user-secret"}},
        )
        self.assertEqual(401, unauthorized.status_code)

        self.register()
        response = self.client.post(
            "/api/connectors/setup",
            json={"connector_id": "openai_api", "credentials": {"api_key": "user-secret"}},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("verified", response.json["connection"]["status"])
        self.assertEqual("user-secret", self.runtime.finished[-1][2]["api_key"])
        self.assertNotIn("user-secret", response.get_data(as_text=True))

    def test_api_key_setup_reports_failed_initial_workspace_update_truthfully(self):
        self.register()
        self.workspace.fail_tool = "connector_call"

        response = self.client.post(
            "/api/connectors/setup",
            json={"connector_id": "openai_api", "credentials": {"api_key": "user-secret"}},
        )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json["ok"])
        self.assertEqual("verified", response.json["connection"]["status"])
        self.assertEqual("failed", response.json["workspace_update"]["status"])
        self.assertIsNone(response.json["workspace_update"]["artifact"])
        self.assertIn("could not be loaded", response.json["messages"][-1]["content"])

    def test_oauth_callback_reports_failed_initial_workspace_update_truthfully(self):
        self.register()
        store = self.app.extensions["cordia_store"]
        state = store.create_oauth_state(1, "google_drive")
        self.workspace.fail_tool = "connector_call"

        response = self.client.get(
            "/api/connectors/oauth/callback", query_string={"state": state, "code": "code"}
        )

        self.assertEqual(302, response.status_code)
        self.assertIn("connected=google_drive", response.location)
        self.assertIn("workspace_update=failed", response.location)

    def test_model_button_selection_changes_the_agent_used_for_next_message(self):
        unauthorized = self.client.post(
            "/api/connectors/select",
            json={"connector_id": "openai_api", "value": "gpt-5-mini"},
        )
        self.assertEqual(401, unauthorized.status_code)

        self.register()
        selected = self.client.post(
            "/api/connectors/select",
            json={"connector_id": "openai_api", "value": "gpt-5-mini"},
        )

        self.assertEqual(200, selected.status_code)
        self.assertEqual("gpt-5-mini", selected.json["selection"]["value"])
        self.assertEqual(
            {"provider": "OpenAI API", "model": "gpt-5-mini", "source": "connector"},
            selected.json["agent_runtime"],
        )
        self.assertNotIn("user-secret", selected.get_data(as_text=True))

        self.complete_survey()
        response = self.client.post("/api/chat", json={"message": "Help me plan this"})

        self.assertEqual(200, response.status_code)
        self.assertEqual([("user-secret", "gpt-5-mini")], self.agent_factory_calls)

    def test_live_view_refreshes_a_verified_connector_artifact(self):
        self.register()
        self.app.extensions["cordia_store"].save_connection(
            1,
            "google_drive",
            "verified",
            {
                "access_token": "provider-access-token",
                "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
            },
        )

        response = self.client.post(
            "/api/connectors/live-view", json={"connector_id": "google_drive"}
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("granted", response.json["live_view"]["status"])
        self.assertEqual("Plan.md", response.json["artifact"]["rows"][0][0])

    def test_live_view_returns_setup_instead_of_artifact_when_authorization_is_missing(self):
        self.register()
        self.runtime.live_view_status = "needs_authorization"

        response = self.client.post(
            "/api/connectors/live-view", json={"connector_id": "google_drive"}
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("needs_authorization", response.json["live_view"]["status"])
        self.assertEqual("oauth_redirect", response.json["setup_card"]["type"])
        self.assertNotIn("artifact", response.json)


if __name__ == "__main__":
    unittest.main()
