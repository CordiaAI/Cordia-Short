import os
import tempfile
import unittest
from pathlib import Path

from app import create_app, load_local_env, resolve_action_starter
from cordia.agent import Agent
from tests.agent_helpers import ScriptedModel


APPLICATIONS = [
    {"id": "app_alpha", "name": "Team Chat Alpha", "logo": "https://cdn.example.test/alpha.png", "description": "Team communication", "categories": ["Communication"], "auth_kind": "oauth"},
    {"id": "app_beta", "name": "Cloud Files Beta", "logo": "https://cdn.example.test/beta.png", "description": "Cloud files", "categories": ["Files"], "auth_kind": "oauth"},
]


class WorkspaceActionStarterTests(unittest.TestCase):
    def test_action_starter_resolves_only_from_server_selected_actions(self):
        applications = [{
            "application_id": "app_alpha",
            "registry_id": "app_alpha",
            "name": "Team Chat Alpha",
            "actions": [{
                "id": "send-message",
                "label": "Send message",
                "prompt": "Send message in Team Chat Alpha.",
            }],
        }]

        resolved = resolve_action_starter(
            applications,
            {"connector_id": "app_alpha", "action_id": "send-message"},
        )

        self.assertEqual("Team Chat Alpha", resolved["application_name"])
        self.assertEqual("Send message", resolved["label"])
        self.assertEqual("Send message in Team Chat Alpha.", resolved["prompt"])

    def test_action_starter_rejects_client_invented_action(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            resolve_action_starter(
                [{
                    "application_id": "app_alpha",
                    "registry_id": "app_alpha",
                    "name": "Team Chat Alpha",
                    "actions": [],
                }],
                {"connector_id": "app_alpha", "action_id": "invented-action"},
            )


class LocalEnvironmentLoadingTests(unittest.TestCase):
    def test_configured_file_replaces_blank_inherited_value(self):
        name = "CORDIA_TEST_LOCAL_ENV"
        previous = os.environ.get(name)
        try:
            os.environ[name] = ""
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / ".env.local"
                path.write_text(f"{name}=configured\n", encoding="utf-8")
                load_local_env(path)
            self.assertEqual("configured", os.environ[name])
        finally:
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


class FakeRuntime:
    def __init__(self, configured=True):
        self.configured = configured
        self.store = None
        self.finished = []

    def catalog_state(self, query="", limit=100):
        del limit
        if not self.configured:
            return {"status": "needs_configuration", "applications": [], "message": "Universal connector provider configuration missing"}
        query = str(query).lower()
        applications = [item for item in APPLICATIONS if not query or query in item["id"] or query in item["name"].lower()]
        return {"status": "ready", "applications": applications}

    def start_connection(self, user_id, connector_id, requested_scopes=None):
        del requested_scopes
        return {"type": "oauth_redirect", "connector_id": connector_id, "title": "Connect application", "status": "ready", "message": "Continue securely.", "action_url": "https://connect.example.test/session"}

    def finish_connection(self, user_id, connector_id, setup_result):
        self.finished.append((user_id, connector_id, setup_result))
        self.store.save_connection(user_id, connector_id, "verified", {"account_id": "account-1"})
        return {"connector_id": connector_id, "status": "verified"}

    def application(self, connector_id):
        return next(item for item in APPLICATIONS if item["id"] == connector_id)

    def decorate_artifact(self, user_id, artifact):
        del user_id
        return artifact

    def live_view_access(self, user_id, connector_id):
        del user_id
        return {"status": "unsupported", "connector_id": connector_id}

    def select_value(self, user_id, connector_id, value):
        del user_id, connector_id, value
        raise RuntimeError("unsupported")


class FakeWorkspace:
    def __init__(self, runtime):
        self.runtime = runtime

    def call(self, user_id, tool_name, arguments):
        if tool_name == "connector_start":
            return self.runtime.start_connection(user_id, arguments["connector_id"])
        if tool_name == "connectors_search":
            state = self.runtime.catalog_state(arguments.get("query", ""), 20)
            return {"status": state["status"], "connectors": state["applications"]}
        raise AssertionError(tool_name)


class RecordingWorkspaceClient:
    """Legacy journey harness; app names here are non-normative fixtures."""
    def __init__(self):
        self.calls = []
        self.store = None
        self.fail_tool = None
        self.mcp_setups = []

    def finish_server_setup(self, user_id, server_id, credentials):
        self.mcp_setups.append((user_id, server_id, credentials))
        return {"server_id": server_id, "status": "verified", "tools": []}

    def call(self, user_id, tool_name, arguments):
        self.calls.append((user_id, tool_name, arguments))
        if tool_name == self.fail_tool:
            from cordia.workspace_mcp import WorkspaceMCPError
            raise WorkspaceMCPError("provider operation failed")
        if tool_name == "connector_start":
            return {"type": "oauth_redirect", "connector_id": arguments["connector_id"], "title": "Connect application", "status": "ready", "message": "Continue securely.", "action_url": "https://connect.example.test/session"}
        if tool_name == "connectors_search":
            query = str(arguments.get("query") or "google_drive")
            return {"status": "ready", "connectors": [{"id": query, "name": query.replace("_", " ").title()}]}
        if tool_name == "connector_call":
            return {"artifact": {"type": "table", "title": "Provider results", "columns": ["Name"], "rows": [["Plan.md"]], "source": arguments["connector_id"], "operation_id": arguments.get("operation_id") or arguments.get("tool_id")}}
        if tool_name == "artifact_create":
            artifact = arguments["payload"]
            artifact_id = self.store.save_artifact(user_id, artifact)
            return {"artifact": {**artifact, "id": artifact_id}}
        raise AssertionError(tool_name)


class UniversalApplicationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.runtime = FakeRuntime()
        agent = Agent("fixture-key", "fixture-model", chat_model=ScriptedModel(replies=[]))
        self.app = create_app(
            {"TESTING": True, "DATABASE": root / "cordia.db", "WORKSPACE_ROOT": root / "workspaces", "SESSION_COOKIE_SECURE": False},
            agent=agent,
            connector_runtime=self.runtime,
            workspace_client=FakeWorkspace(self.runtime),
        )
        self.runtime.store = self.app.extensions["cordia_store"]
        self.client = self.app.test_client()

    def register(self):
        response = self.client.post("/api/register", json={"email": "person@example.com", "password": "correct horse battery"})
        self.assertEqual(201, response.status_code)
        return response

    def test_register_exposes_provider_owned_catalog_without_static_operation_data(self):
        state = self.register().json

        self.assertEqual("onboarding", state["state"])
        self.assertEqual(["app_alpha", "app_beta"], [item["id"] for item in state["onboarding"]["application_catalog"]])
        self.assertNotIn("operations", state["onboarding"]["application_catalog"][0])

    def test_authenticated_search_queries_runtime_catalog(self):
        self.register()

        response = self.client.get("/api/connectors/search?q=files")

        self.assertEqual(200, response.status_code)
        self.assertEqual(["app_beta"], [item["id"] for item in response.json["applications"]])

    def test_search_requires_workspace_authentication(self):
        response = self.client.get("/api/connectors/search?q=files")
        self.assertEqual(401, response.status_code)

    def test_missing_catalog_configuration_is_visible_not_simulated(self):
        self.runtime.configured = False
        state = self.register().json["onboarding"]

        self.assertEqual("needs_configuration", state["application_catalog_status"])
        self.assertEqual([], state["application_catalog"])
        self.assertIn("configuration", state["application_catalog_message"])

    def test_managed_auth_callback_resolves_owner_bound_state(self):
        self.register()
        state = self.runtime.store.create_oauth_state(1, "app_alpha")

        response = self.client.get(f"/api/connectors/oauth/callback?state={state}")

        self.assertEqual(302, response.status_code)
        self.assertIn("connected=app_alpha", response.location)
        self.assertEqual("verified", self.runtime.store.connection_status(1, "app_alpha"))


if __name__ == "__main__":
    unittest.main()
