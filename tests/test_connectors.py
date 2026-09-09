import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cordia.connector_runtime import ConnectorError, ConnectorRuntime
from cordia.connectors import public_application, public_tool, resolve_application
from cordia.store import Store


APP_ALPHA = {
    "id": "app_alpha",
    "name": "Team Chat Alpha",
    "logo": "https://cdn.example.test/alpha.png",
    "description": "Team communication",
    "categories": ["Communication"],
    "auth_kind": "oauth",
}
APP_BETA = {
    "id": "app_beta",
    "name": "Cloud Files Beta",
    "logo": "https://cdn.example.test/beta.png",
    "description": "Cloud files",
    "categories": ["Files"],
    "auth_kind": "oauth",
}


class ProviderRecordTests(unittest.TestCase):
    def test_provider_application_is_normalized_without_static_contract_data(self):
        application = public_application(
            {
                "name_slug": "app_alpha",
                "name": "Team Chat Alpha",
                "img_src": "https://cdn.example.test/alpha.png",
                "auth_type": "oauth",
                "categories": ["Communication"],
            }
        )

        self.assertEqual("app_alpha", application["id"])
        self.assertEqual("Team Chat Alpha", application["name"])
        self.assertNotIn("authorize_url", json.dumps(application))
        self.assertNotIn("operations", application)

    def test_two_unrelated_opaque_applications_resolve_from_runtime_catalog(self):
        self.assertEqual("app_alpha", resolve_application("Team Chat Alpha", [APP_ALPHA, APP_BETA])["id"])
        self.assertEqual("app_beta", resolve_application("app_beta", [APP_ALPHA, APP_BETA])["id"])
        self.assertIsNone(resolve_application("not present", [APP_ALPHA, APP_BETA]))

    def test_exact_current_display_name_wins_over_a_legacy_identifier(self):
        applications = [
            {**APP_ALPHA, "id": "work", "name": "Work (legacy)"},
            {**APP_BETA, "id": "work_v2", "name": "Work"},
        ]

        self.assertEqual("work_v2", resolve_application("work", applications)["id"])

    def test_provider_tool_schema_and_safety_annotations_are_preserved(self):
        tool = public_tool(
            {
                "name": "opaque_action",
                "title": "Opaque action",
                "inputSchema": {"type": "object", "properties": {"target": {"type": "string"}}},
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            }
        )

        self.assertEqual("opaque_action", tool["id"])
        self.assertTrue(tool["annotations"]["destructiveHint"])
        self.assertIn("target", tool["input_schema"]["properties"])


class UniversalConnectorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(root / "cordia.db", root / "workspaces")
        self.user_id = self.store.register("person@example.com", "correct horse battery")
        self.calls = []
        self.env = {
            "PIPEDREAM_CLIENT_ID": "provider-client",
            "PIPEDREAM_CLIENT_SECRET": "provider-secret",
            "PIPEDREAM_PROJECT_ID": "project-123",
            "PIPEDREAM_ENVIRONMENT": "development",
            "CORDIA_BASE_URL": "http://127.0.0.1:5050",
        }

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, method, url, headers, data, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "data": data})
        if url.endswith("/oauth/token"):
            return {"access_token": "developer-token", "expires_in": 3600}
        if url.endswith("/connect/apps"):
            records = [
                {"name_slug": "app_alpha", "name": "Team Chat Alpha", "img_src": APP_ALPHA["logo"], "auth_type": "oauth"},
                {"name_slug": "app_beta", "name": "Cloud Files Beta", "img_src": APP_BETA["logo"], "auth_type": "oauth"},
            ]
            query = str((data or {}).get("q", "")).lower()
            if query:
                records = [item for item in records if query in item["name"].lower() or query == item["name_slug"]]
            return {"data": records}
        if url.endswith("/connect/project-123/tokens"):
            return {"connect_link_url": "https://connect.example.test/session-token"}
        if url.endswith("/connect/project-123/accounts"):
            return {"data": [{"id": "account-456", "dead": False, "app": {"name_slug": data["app"]}}]}
        raise AssertionError(f"unexpected request: {method} {url}")

    def runtime(self, env=None):
        return ConnectorRuntime(self.store, env=self.env if env is None else env, transport=self.transport)

    def test_catalog_is_dynamic_and_preserves_two_unrelated_provider_apps(self):
        state = self.runtime().catalog_state()

        self.assertEqual("ready", state["status"])
        self.assertEqual(["app_alpha", "app_beta"], [item["id"] for item in state["applications"]])
        apps_call = next(call for call in self.calls if call["url"].endswith("/connect/apps"))
        self.assertEqual("Bearer developer-token", apps_call["headers"]["Authorization"])

    def test_missing_provider_configuration_is_truthful_and_has_no_fallback_catalog(self):
        state = self.runtime(env={}).catalog_state()

        self.assertEqual("needs_configuration", state["status"])
        self.assertEqual([], state["applications"])
        self.assertIn("PIPEDREAM_PROJECT_ID", state["message"])
        self.assertEqual([], self.calls)

    def test_start_connection_uses_customer_scoped_managed_auth(self):
        setup = self.runtime().start_connection(self.user_id, "app_alpha")

        self.assertEqual("oauth_redirect", setup["type"])
        self.assertEqual("app_alpha", parse_qs(urlparse(setup["action_url"]).query)["app"][0])
        token_call = next(call for call in self.calls if call["url"].endswith("/tokens"))
        self.assertEqual(f"cordia:{self.user_id}", token_call["data"]["external_user_id"])
        self.assertIn("state=", token_call["data"]["success_redirect_uri"])
        self.assertNotIn("provider-secret", json.dumps(setup))

    def test_callback_verifies_provider_account_and_persists_only_account_identity(self):
        runtime = self.runtime()
        setup = runtime.start_connection(self.user_id, "app_beta")

        result = runtime.finish_connection(self.user_id, "app_beta", {"state": setup["state"]})

        self.assertEqual({"connector_id": "app_beta", "status": "verified"}, result)
        self.assertEqual("verified", self.store.connection_status(self.user_id, "app_beta"))
        self.assertEqual({"account_id": "account-456"}, self.store.connection_credentials(self.user_id, "app_beta"))

    def test_mcp_configuration_is_scoped_to_user_project_and_dynamic_app(self):
        runtime = self.runtime()
        setup = runtime.start_connection(self.user_id, "app_alpha")
        runtime.finish_connection(self.user_id, "app_alpha", {"state": setup["state"]})

        config = runtime.mcp_configuration(self.user_id, "app_alpha")

        self.assertEqual("https://remote.mcp.pipedream.net/v3", config["endpoint"])
        self.assertEqual("app_alpha", config["headers"]["x-pd-app-slug"])
        self.assertEqual(f"cordia:{self.user_id}", config["headers"]["x-pd-external-user-id"])
        self.assertNotIn("provider-secret", json.dumps(config))

    def test_unknown_application_is_not_invented_locally(self):
        with self.assertRaisesRegex(ConnectorError, "not found"):
            self.runtime().start_connection(self.user_id, "invented_app")


if __name__ == "__main__":
    unittest.main()
