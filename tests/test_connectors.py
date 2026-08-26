import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cordia.connector_runtime import ConnectorError, ConnectorRuntime
from cordia.connectors import CONNECTORS, resolve_connector, validate_registry
from cordia.store import Store


class ConnectorRegistryTests(unittest.TestCase):
    def test_google_drive_aliases_resolve_to_one_record(self):
        self.assertEqual("google_drive", resolve_connector("Google Drive")["id"])
        self.assertEqual("google_drive", resolve_connector("drive")["id"])
        self.assertEqual("google_drive", resolve_connector("gdrive")["id"])

    def test_unknown_connector_returns_none(self):
        self.assertIsNone(resolve_connector("imaginary service"))

    def test_api_key_connector_aliases_resolve_to_one_declarative_record(self):
        connector = resolve_connector("OpenAI")

        self.assertEqual("openai_api", connector["id"])
        self.assertEqual("api_key", connector["auth"]["kind"])
        self.assertEqual(["list_models"], list(connector["operations"]))

    def test_malformed_record_is_rejected(self):
        malformed = {
            "broken": {
                "id": "broken",
                "name": "Broken",
                "aliases": [],
                "auth": {"kind": "oauth2"},
            }
        }
        with self.assertRaisesRegex(ValueError, "operations"):
            validate_registry(malformed)

    def test_registry_contains_no_runtime_callable(self):
        self.assertNotIn("handler", json.dumps(CONNECTORS))
        self.assertEqual("oauth2", CONNECTORS["google_drive"]["auth"]["kind"])

    def test_api_key_record_requires_https_fields_header_and_verification_operation(self):
        base = {
            "id": "custom",
            "name": "Custom",
            "aliases": [],
            "auth": {
                "kind": "api_key",
                "fields": [{"name": "api_key", "label": "API key", "type": "password"}],
                "header": {"name": "Authorization", "template": "Bearer {api_key}"},
                "verify_operation": "list_items",
            },
            "operations": {
                "list_items": {
                    "method": "GET",
                    "url": "https://api.example.com/items",
                    "result_key": "items",
                    "artifact": {"fields": ["name"]},
                }
            },
        }

        missing_header = json.loads(json.dumps(base))
        del missing_header["auth"]["header"]
        with self.assertRaisesRegex(ValueError, "header"):
            validate_registry({"custom": missing_header})

        visible_field = json.loads(json.dumps(base))
        visible_field["auth"]["fields"][0]["type"] = "text"
        with self.assertRaisesRegex(ValueError, "password"):
            validate_registry({"custom": visible_field})

        missing_label = json.loads(json.dumps(base))
        del missing_label["auth"]["fields"][0]["label"]
        with self.assertRaisesRegex(ValueError, "label"):
            validate_registry({"custom": missing_label})

        insecure_url = json.loads(json.dumps(base))
        insecure_url["operations"]["list_items"]["url"] = "http://api.example.com/items"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_registry({"custom": insecure_url})

        unknown_verification = json.loads(json.dumps(base))
        unknown_verification["auth"]["verify_operation"] = "missing"
        with self.assertRaisesRegex(ValueError, "verification"):
            validate_registry({"custom": unknown_verification})


class ConnectorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = root / "cordia.db"
        self.store = Store(self.db_path, root / "workspaces")
        self.user_id = self.store.register("person@example.com", "correct horse battery")
        self.calls = []
        self.env = {
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "CORDIA_BASE_URL": "http://127.0.0.1:5050",
        }

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, method, url, headers, data, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "data": data, "timeout": timeout}
        )
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
                        "modifiedTime": "2026-08-24T12:00:00Z",
                        "webViewLink": "https://drive.google.com/file-1",
                    }
                ]
            }
        if url == "https://api.openai.com/v1/models":
            if headers.get("Authorization") != "Bearer user-openai-key":
                raise OSError("invalid API key")
            return {
                "data": [
                    {"id": "gpt-5-mini", "owned_by": "openai"},
                    {"id": "gpt-4.1-mini", "owned_by": "system"},
                ]
            }
        raise AssertionError(f"unexpected request: {method} {url}")

    def runtime(self):
        return ConnectorRuntime(self.store, env=self.env, transport=self.transport)

    def test_start_connection_returns_owner_bound_google_redirect(self):
        setup = self.runtime().start_connection(self.user_id, "drive")

        self.assertEqual("oauth_redirect", setup["type"])
        query = parse_qs(urlparse(setup["action_url"]).query)
        self.assertEqual(["google-client-id"], query["client_id"])
        self.assertEqual(
            ["http://127.0.0.1:5050/api/connectors/oauth/callback"], query["redirect_uri"]
        )
        self.assertEqual(
            ["https://www.googleapis.com/auth/drive.metadata.readonly"], query["scope"]
        )
        self.assertEqual(["offline"], query["access_type"])
        self.assertEqual(["false"], query["include_granted_scopes"])
        self.assertTrue(query["state"][0])
        self.assertTrue(self.store.consume_oauth_state(self.user_id, "google_drive", query["state"][0]))
        self.assertFalse(self.store.consume_oauth_state(self.user_id, "google_drive", query["state"][0]))

    def test_missing_oauth_configuration_is_explicit(self):
        setup = ConnectorRuntime(self.store, env={}, transport=self.transport).start_connection(
            self.user_id, "google_drive"
        )
        self.assertEqual("needs_configuration", setup["status"])
        self.assertIn("GOOGLE_CLIENT_ID", setup["message"])
        self.assertNotIn("action_url", setup)

    def test_api_key_start_returns_generic_secure_credential_form(self):
        setup = self.runtime().start_connection(self.user_id, "openai")

        self.assertEqual("credential_form", setup["type"])
        self.assertEqual("openai_api", setup["connector_id"])
        self.assertEqual("/api/connectors/setup", setup["submit_url"])
        self.assertEqual(
            [{"name": "api_key", "label": "OpenAI API key", "type": "password", "required": True}],
            setup["fields"],
        )
        self.assertNotIn("user-openai-key", json.dumps(setup))

    def test_api_key_finish_verifies_provider_and_encrypts_credentials(self):
        runtime = self.runtime()

        connection = runtime.finish_connection(
            self.user_id, "openai_api", {"api_key": "user-openai-key"}
        )

        self.assertEqual({"connector_id": "openai_api", "status": "verified"}, connection)
        self.assertEqual("Bearer user-openai-key", self.calls[0]["headers"]["Authorization"])
        with closing(sqlite3.connect(self.db_path)) as database:
            encrypted = database.execute(
                "SELECT credentials FROM connections WHERE user_id = ? AND connector_id = ?",
                (self.user_id, "openai_api"),
            ).fetchone()[0]
        self.assertNotIn("user-openai-key", encrypted)

    def test_api_key_provider_failure_never_marks_connection_verified(self):
        def failing_transport(method, url, headers, data, timeout):
            raise OSError("provider rejected credential")

        runtime = ConnectorRuntime(self.store, env=self.env, transport=failing_transport)

        with self.assertRaisesRegex(ConnectorError, "verification failed"):
            runtime.finish_connection(
                self.user_id, "openai_api", {"api_key": "invalid-user-key"}
            )

        self.assertNotEqual("verified", self.store.connection_status(self.user_id, "openai_api"))
        self.assertEqual({}, self.store.connection_credentials(self.user_id, "openai_api"))

    def test_api_key_malformed_success_response_never_marks_connection_verified(self):
        def malformed_transport(method, url, headers, data, timeout):
            return {"error": "credential rejected"}

        runtime = ConnectorRuntime(self.store, env=self.env, transport=malformed_transport)

        with self.assertRaisesRegex(ConnectorError, "verification failed"):
            runtime.finish_connection(
                self.user_id, "openai_api", {"api_key": "invalid-user-key"}
            )

        self.assertNotEqual("verified", self.store.connection_status(self.user_id, "openai_api"))
        self.assertEqual({}, self.store.connection_credentials(self.user_id, "openai_api"))

    def test_api_key_operation_uses_declared_header_and_returns_artifact(self):
        runtime = self.runtime()
        runtime.finish_connection(self.user_id, "openai_api", {"api_key": "user-openai-key"})

        artifact = runtime.call_operation(self.user_id, "openai_api", "list_models", {})

        self.assertEqual("Available OpenAI models", artifact["title"])
        self.assertEqual("openai_api", artifact["source"])
        self.assertEqual(["gpt-5-mini", "openai"], artifact["rows"][0])
        self.assertNotIn("user-openai-key", json.dumps(artifact))

    def test_finish_connection_exchanges_code_verifies_provider_and_encrypts_tokens(self):
        runtime = self.runtime()
        setup = runtime.start_connection(self.user_id, "google_drive")
        state = parse_qs(urlparse(setup["action_url"]).query)["state"][0]

        connection = runtime.finish_connection(
            self.user_id, "google_drive", {"state": state, "code": "authorization-code"}
        )

        self.assertEqual("verified", connection["status"])
        self.assertTrue(any(call["url"] == "https://oauth2.googleapis.com/token" for call in self.calls))
        self.assertTrue(any("/drive/v3/files" in call["url"] for call in self.calls))
        with closing(sqlite3.connect(self.db_path)) as database:
            encrypted = database.execute(
                "SELECT credentials FROM connections WHERE user_id = ? AND connector_id = ?",
                (self.user_id, "google_drive"),
            ).fetchone()[0]
        self.assertNotIn("provider-access-token", encrypted)
        self.assertNotIn("provider-refresh-token", encrypted)

    def test_oauth_state_cannot_be_finished_by_another_user_or_reused(self):
        runtime = self.runtime()
        setup = runtime.start_connection(self.user_id, "google_drive")
        state = parse_qs(urlparse(setup["action_url"]).query)["state"][0]
        other_user = self.store.register("other@example.com", "correct horse battery")

        with self.assertRaisesRegex(ConnectorError, "state"):
            runtime.finish_connection(
                other_user, "google_drive", {"state": state, "code": "authorization-code"}
            )
        runtime.finish_connection(
            self.user_id, "google_drive", {"state": state, "code": "authorization-code"}
        )
        with self.assertRaisesRegex(ConnectorError, "state"):
            runtime.finish_connection(
                self.user_id, "google_drive", {"state": state, "code": "authorization-code"}
            )

    def test_operation_uses_declared_endpoint_and_returns_provider_derived_artifact(self):
        runtime = self.runtime()
        setup = runtime.start_connection(self.user_id, "google_drive")
        state = parse_qs(urlparse(setup["action_url"]).query)["state"][0]
        runtime.finish_connection(
            self.user_id, "google_drive", {"state": state, "code": "authorization-code"}
        )

        artifact = runtime.call_operation(self.user_id, "google_drive", "list_recent_files", {})

        self.assertEqual("table", artifact["type"])
        self.assertEqual("google_drive", artifact["source"])
        self.assertEqual("Plan.md", artifact["rows"][0][0])
        self.assertEqual("https://drive.google.com/file-1", artifact["rows"][0][3])
        self.assertNotIn("provider-access-token", json.dumps(artifact))

    def test_provider_failure_never_marks_connection_verified(self):
        def failing_transport(method, url, headers, data, timeout):
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "token", "expires_in": 3600}
            raise OSError("provider unavailable")

        runtime = ConnectorRuntime(self.store, env=self.env, transport=failing_transport)
        setup = runtime.start_connection(self.user_id, "google_drive")
        state = parse_qs(urlparse(setup["action_url"]).query)["state"][0]

        with self.assertRaisesRegex(ConnectorError, "verification failed"):
            runtime.finish_connection(
                self.user_id, "google_drive", {"state": state, "code": "authorization-code"}
            )
        self.assertNotEqual("verified", self.store.connection_status(self.user_id, "google_drive"))

    def test_expired_access_token_is_refreshed_before_provider_operation(self):
        calls = []

        def refresh_transport(method, url, headers, data, timeout):
            calls.append({"method": method, "url": url, "headers": headers, "data": data})
            if url == "https://oauth2.googleapis.com/token":
                self.assertEqual("refresh_token", data["grant_type"])
                self.assertEqual("provider-refresh-token", data["refresh_token"])
                return {
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
                    "token_type": "Bearer",
                }
            if url.startswith("https://www.googleapis.com/drive/v3/files"):
                self.assertEqual("Bearer new-access-token", headers["Authorization"])
                return {"files": []}
            raise AssertionError(f"unexpected request: {method} {url}")

        self.store.save_connection(
            self.user_id,
            "google_drive",
            "verified",
            {
                "access_token": "expired-access-token",
                "refresh_token": "provider-refresh-token",
                "expires_at": 0,
                "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
                "token_type": "Bearer",
            },
        )
        runtime = ConnectorRuntime(self.store, env=self.env, transport=refresh_transport)

        artifact = runtime.call_operation(
            self.user_id, "google_drive", "list_recent_files", {}
        )

        self.assertEqual([], artifact["rows"])
        self.assertEqual("new-access-token", self.store.connection_credentials(
            self.user_id, "google_drive"
        )["access_token"])
        self.assertEqual("provider-refresh-token", self.store.connection_credentials(
            self.user_id, "google_drive"
        )["refresh_token"])
        self.assertEqual(2, len(calls))


if __name__ == "__main__":
    unittest.main()
