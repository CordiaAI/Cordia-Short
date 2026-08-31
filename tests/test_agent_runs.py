import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from langchain_core.messages import AIMessage, ToolMessage

from cordia import agent as agent_module
from cordia.agent_runs import AgentRuns
from cordia.connector_runtime import ConnectorRuntime
from cordia.connectors import CONNECTORS
from cordia.store import Store
from cordia.workspace_mcp import WorkspaceMCPClient
from tests.agent_helpers import ScriptedModel, call


class AgentRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "cordia.db", self.root / "workspaces")
        self.user = self.store.register("agent@example.com", "correct-horse-battery")
        self.http_calls = []
        self.rows = [{"id": "gpt-test-model", "owned_by": "provider-fixture"}]
        self.runtime = ConnectorRuntime(self.store, env={}, transport=self.transport)
        self.workspace = WorkspaceMCPClient(self.runtime, self.store)

    def transport(self, method, url, headers, data, timeout):
        self.http_calls.append((method, url))
        self.assertEqual(("GET", "https://api.openai.com/v1/models"), (method, url))
        self.assertEqual("Bearer fixture-secret", headers["Authorization"])
        self.assertLessEqual(timeout, 30)
        return {"object": "list", "data": self.rows}

    def service(self, replies, **limits):
        model = ScriptedModel(replies=replies)
        agent = agent_module.Agent("fixture-model-key", chat_model=model)
        service = AgentRuns(
            self.store, self.workspace, lambda user: agent, **limits,
        )
        return service, model

    def verify(self):
        self.runtime.finish_connection(self.user, "openai_api", {"api_key": "fixture-secret"})

    def test_operation_result_reaches_model_and_reuses_real_artifact_identity(self):
        self.verify()
        service, model = self.service([
            call("run_operation", connector_id="openai_api", operation_id="list_models"),
            AIMessage(content="- Available: gpt-test-model."),
            call("run_operation", connector_id="openai_api", operation_id="list_models"),
            AIMessage(content="- Updated model list."),
        ])
        first = service.start(self.user, "List my available OpenAI models")
        result = json.loads(next(m.content for m in model.requests[1] if isinstance(m, ToolMessage)))
        self.assertEqual("gpt-test-model", result["artifact"]["rows"][0][0])
        self.assertEqual("completed", first["run"]["status"])
        self.rows.append({"id": "gpt-second", "owned_by": "provider-fixture"})
        second = service.start(self.user, "Refresh them")
        self.assertEqual(first["artifact"]["id"], second["artifact"]["id"])
        self.assertEqual(1, len(self.store.artifacts(self.user)))
        self.assertEqual(2, len(self.store.artifacts(self.user)[0]["rows"]))

    def test_pause_survives_reconstruction_and_verified_resume_keeps_original_task(self):
        service, model = self.service([
            call("run_operation", connector_id="openai_api", operation_id="list_models"),
        ])
        paused = service.start(self.user, "Which models can I use for my report?")
        self.assertEqual("waiting_connection", paused["run"]["status"])
        self.assertEqual("credential_form", paused["setup_card"]["type"])
        self.assertEqual([], self.http_calls)
        replacement, model = self.service([AIMessage(content="- You can use gpt-test-model.")])
        with self.assertRaisesRegex(PermissionError, "verified"):
            replacement.resume(self.user, "openai_api", run_id=paused["run"]["id"])
        other = self.store.register("other@example.com", "correct-horse-battery")
        with self.assertRaises(LookupError):
            replacement.resume(other, "openai_api", run_id=paused["run"]["id"])
        self.verify()
        result = replacement.resume(self.user, "openai_api", run_id=paused["run"]["id"])
        self.assertEqual("completed", result["run"]["status"])
        self.assertIn("Which models can I use for my report?", str(model.requests[0]))
        self.assertTrue(any(isinstance(m, ToolMessage) for m in model.requests[0]))
        before = (len(self.http_calls), len(self.store.messages(self.user)))
        repeated = replacement.resume(self.user, "openai_api", run_id=paused["run"]["id"])
        self.assertEqual(result["run"]["id"], repeated["run"]["id"])
        self.assertEqual(before, (len(self.http_calls), len(self.store.messages(self.user))))

    def test_setup_configuration_failure_is_terminal_and_not_success(self):
        service, model = self.service([call("connect_service", connector_id="google_drive")])
        result = service.start(self.user, "Connect Drive")
        self.assertEqual("needs_configuration", result["run"]["status"])
        self.assertEqual("needs_configuration", result["setup_card"]["status"])
        self.assertNotIn("connected", result["assistant"].lower())
        self.assertEqual(1, len(model.requests))

    def test_denied_setup_finishes_without_model_or_provider_calls(self):
        service, model = self.service([call("connect_service", connector_id="openai_api")])
        paused = service.start(self.user, "Connect OpenAI")
        denied = service.deny(self.user, "openai_api")
        self.assertEqual("denied", denied["run"]["status"])
        self.assertIsNone(self.store.setup_card(self.user))
        self.assertEqual(1, len(model.requests))
        self.assertEqual([], self.http_calls)
        self.assertEqual(paused["run"]["id"], denied["run"]["id"])

    def test_invalid_tool_and_unknown_connector_do_not_execute(self):
        for tool_call in [call("shell", command="anything"),
                          call("connect_service", connector_id="unsupported"),
                          call("run_operation", connector_id="openai_api", operation_id="delete")]:
            with self.subTest(tool_call=tool_call):
                service, _ = self.service([tool_call])
                with self.assertRaises(agent_module.InvalidAgentAction):
                    service.start(self.user, "Do the task")
        self.assertEqual([], self.http_calls)

    def test_write_operation_is_rejected_before_authorization(self):
        service, _ = self.service([call("run_operation", connector_id="openai_api", operation_id="list_models")])
        with patch.dict(CONNECTORS["openai_api"]["operations"]["list_models"], method="POST"):
            with self.assertRaisesRegex(agent_module.InvalidAgentAction, "read-only"):
                service.start(self.user, "List models")
        self.assertEqual([], self.http_calls)
        self.assertIsNone(self.store.setup_card(self.user))

    def test_model_failure_releases_workspace_lock(self):
        service, _ = self.service([OSError("provider secret error"), AIMessage(content="Recovered")])
        with self.assertRaisesRegex(agent_module.AgentUnavailable, "model request failed"):
            service.start(self.user, "Help")
        self.assertEqual("completed", service.start(self.user, "Try again")["run"]["status"])

    def test_tool_failure_is_returned_to_model_without_fake_artifact(self):
        self.verify()
        service, model = self.service([
            call("run_operation", connector_id="openai_api", operation_id="list_models"),
            AIMessage(content="- The provider request failed."),
        ])
        with patch.object(self.runtime, "transport", side_effect=OSError("fixture-secret")):
            result = service.start(self.user, "List models")
        tool_result = json.loads(next(m.content for m in model.requests[1] if isinstance(m, ToolMessage)))
        self.assertFalse(tool_result["ok"])
        self.assertEqual("failed", result["run"]["status"])
        self.assertIsNone(result["artifact"])
        self.assertEqual([], self.store.artifacts(self.user))
        self.assertNotIn("fixture-secret", str(model.requests))

    def test_model_iteration_and_tool_call_limits_stop_external_work(self):
        service, model = self.service([call("connector_status", connector_id="openai_api")] * 8,
                                      max_model_calls=2, max_tool_calls=1)
        with self.assertRaisesRegex(agent_module.InvalidAgentAction, "limit"):
            service.start(self.user, "Keep checking")
        self.assertLessEqual(len(model.requests), 2)
        self.assertEqual([], self.http_calls)

    def test_same_user_is_busy_across_service_instances(self):
        service, _ = self.service([AIMessage(content="One")])
        other, _ = self.service([AIMessage(content="Two")])
        with service.lock(self.user):
            with self.assertRaisesRegex(agent_module.AgentBusy, "already"):
                other.start(self.user, "Must not be stored")
        self.assertEqual([], self.store.messages(self.user))
        self.assertEqual("completed", other.start(self.user, "Allowed")["run"]["status"])

    def test_waiting_run_blocks_new_chat_without_losing_original(self):
        service, _ = self.service([call("connect_service", connector_id="openai_api")])
        paused = service.start(self.user, "Original task")
        with self.assertRaises(agent_module.AgentBusy):
            service.start(self.user, "Overwrite original")
        self.assertEqual(paused["run"]["id"], service.latest(self.user)["id"])
        self.assertNotIn("Overwrite original", str(self.store.messages(self.user)))

    def test_credentials_and_oauth_urls_are_absent_from_model_and_checkpoints(self):
        self.runtime.env.update(GOOGLE_CLIENT_ID="client", GOOGLE_CLIENT_SECRET="server-secret")
        service, model = self.service([call("connect_service", connector_id="google_drive")])
        result = service.start(self.user, "Connect Drive token=do-not-retain https://accounts.google.com/o/oauth2/auth?code=secret-code&state=private-state")
        self.assertEqual("oauth_redirect", result["setup_card"]["type"])
        secret_url = result["setup_card"]["action_url"]
        serialized = str(model.requests)
        for db in self.root.glob("*checkpoint*.sqlite"):
            serialized += db.read_bytes().decode("latin1")
        for secret in ("do-not-retain", "secret-code", "private-state", "server-secret", secret_url):
            self.assertNotIn(secret, serialized)

    def test_adjustment_uses_saved_result_without_repeating_connector_side_effects(self):
        self.verify()
        service, model = self.service([
            call("run_operation", connector_id="openai_api", operation_id="list_models"),
            AIMessage(content="Initial explanation"), AIMessage(content="- gpt-test-model."),
        ])
        result = service.start(self.user, "List models")
        response_id = self.store.messages(self.user)[-1]["id"]
        before = len(self.http_calls)
        revised = service.revise(self.user, response_id)
        self.assertEqual(before, len(self.http_calls))
        self.assertIn("gpt-test-model", str(model.requests[-1]))
        self.assertEqual("completed", revised["run"]["status"])

    def test_oversized_tool_rows_are_compacted_and_usage_and_reply_are_bounded(self):
        self.verify()
        self.rows = [{"id": "gpt-" + "x" * 1000, "owned_by": "provider"}] * 100
        service, model = self.service([
            call("run_operation", connector_id="openai_api", operation_id="list_models"),
            AIMessage(content="answer " * 2000, usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}),
        ])
        result = service.start(self.user, "List models")
        evidence = json.loads(next(m.content for m in model.requests[1] if isinstance(m, ToolMessage)))
        self.assertEqual(20, len(evidence["artifact"]["rows"]))
        self.assertTrue(evidence["preview_truncated"])
        self.assertEqual(100, evidence["artifact_total_rows"])
        self.assertLessEqual(len(evidence["artifact"]["rows"][0][0]), 300)
        self.assertEqual({"input_tokens": 120, "output_tokens": 30}, result["run"]["usage"])
        self.assertLessEqual(len(result["assistant"]), 6000)
        self.assertEqual(100, len(self.store.artifacts(self.user)[0]["rows"]))

    def test_model_call_limit_stops_before_another_request(self):
        service, model = self.service([call("connector_status", connector_id="openai_api")] * 5,
                                      max_model_calls=1)
        with self.assertRaisesRegex(agent_module.InvalidAgentAction, "model_calls limit"):
            service.start(self.user, "Check status repeatedly")
        self.assertEqual(1, len(model.requests))

    def test_model_cannot_supply_user_credentials_or_parallel_tool_calls(self):
        parallel = call("connect_service", connector_id="openai_api")
        parallel.tool_calls.append({"name": "connect_service", "args": {"connector_id": "google_drive"}, "id": "call2", "type": "tool_call"})
        for reply in [parallel, call("connector_status", connector_id="openai_api", user_id=99),
                      call("connect_service", connector_id="openai_api", api_key="sensitive")]:
            with self.subTest(reply=reply):
                service, _ = self.service([reply])
                with self.assertRaises(agent_module.InvalidAgentAction):
                    service.start(self.user, "Do it")
        self.assertEqual([], self.http_calls)
        self.assertIsNone(self.store.setup_card(self.user))

    def test_another_process_is_excluded_and_termination_releases_lock(self):
        service, _ = self.service([AIMessage(content="Allowed")])
        lock_path = service.lock_dir / f"{self.user}.sqlite"
        program = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1],timeout=0); c.execute('BEGIN IMMEDIATE'); print('locked',flush=True); sys.stdin.read()"
        child = subprocess.Popen([sys.executable, "-c", program, str(lock_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertEqual("locked", child.stdout.readline().strip())
        with self.assertRaises(agent_module.AgentBusy):
            service.start(self.user, "Blocked")
        child.kill()
        child.wait(timeout=5)
        child.stdout.close()
        child.stdin.close()
        self.assertEqual("completed", service.start(self.user, "Allowed")["run"]["status"])

    def test_configuration_can_be_fixed_and_new_request_offers_authorization(self):
        service, _ = self.service([call("connect_service", connector_id="google_drive")] * 2)
        first = service.start(self.user, "Connect Drive")
        self.assertEqual("needs_configuration", first["run"]["status"])
        self.runtime.env.update(GOOGLE_CLIENT_ID="client", GOOGLE_CLIENT_SECRET="secret")
        second = service.start(self.user, "Try connecting again")
        self.assertEqual("waiting_connection", second["run"]["status"])
        self.assertEqual("oauth_redirect", second["setup_card"]["type"])

    def test_revised_answer_retains_prior_evidence_for_another_revision(self):
        self.verify()
        service, model = self.service([call("run_operation", connector_id="openai_api", operation_id="list_models"),
                                      AIMessage(content="Original"), AIMessage(content="Revision"), AIMessage(content="Second revision")])
        service.start(self.user, "List models")
        response_id = self.store.messages(self.user)[-1]["id"]
        service.revise(self.user, response_id)
        service.revise(self.user, self.store.messages(self.user)[-1]["id"])
        self.assertIn("gpt-test-model", model.requests[-1][0].content)


class AgentRouteTests(unittest.TestCase):
    setUp = AgentRunTests.setUp
    transport = AgentRunTests.transport
    def app(self, replies):
        from app import create_app
        from tests.test_journey import save_all_stages
        save_all_stages(self.store, self.user)
        self.store.complete_onboarding(self.user, CONNECTORS)
        model = ScriptedModel(replies=replies)
        app = create_app({"TESTING": True, "DATABASE": self.store.db_path,
                          "WORKSPACE_ROOT": self.store.workspace_root},
                         agent=agent_module.Agent("model-fixture", chat_model=model),
                         connector_runtime=self.runtime)
        client = app.test_client()
        client.set_cookie("cordia_session", self.store.create_session(self.user))
        return app, client, model

    def test_chat_and_credential_callback_use_persisted_graph_once(self):
        app, client, model = self.app([call("run_operation", connector_id="openai_api", operation_id="list_models")])
        paused = client.post("/api/chat", json={"message": "List my OpenAI models"})
        self.assertEqual(200, paused.status_code, paused.json)
        self.assertEqual("waiting_connection", paused.json["run"]["status"])
        app, client, model = self.app([AIMessage(content="- Available: gpt-test-model.")])
        resumed = client.post("/api/connectors/setup", json={"connector_id": "openai_api", "credentials": {"api_key": "fixture-secret"}})
        self.assertEqual(200, resumed.status_code, resumed.json)
        self.assertEqual("completed", resumed.json["agent_run"]["status"])
        self.assertEqual("gpt-test-model", resumed.json["artifact"]["rows"][0][0])
        before = len(self.store.messages(self.user))
        repeated = client.post("/api/connectors/setup", json={"connector_id": "openai_api", "credentials": {"api_key": "fixture-secret"}})
        self.assertEqual(200, repeated.status_code)
        self.assertEqual(before, len(self.store.messages(self.user)))
        self.assertNotIn("fixture-secret", str(model.requests) + resumed.get_data(as_text=True))

    def test_concurrent_chat_is_rejected_before_storing_request(self):
        app, client, _ = self.app([AIMessage(content="Unused")])
        with app.extensions["agent_runs"].lock(self.user):
            rejected = client.post("/api/chat", json={"message": "Do not save me"})
        self.assertEqual(409, rejected.status_code)
        self.assertEqual([], self.store.messages(self.user))

    def test_cancel_endpoint_clears_pending_run(self):
        _, client, _ = self.app([call("connect_service", connector_id="openai_api")])
        client.post("/api/chat", json={"message": "Connect OpenAI"})
        canceled = client.post("/api/connectors/cancel", json={"connector_id": "openai_api"})
        self.assertEqual(200, canceled.status_code)
        self.assertEqual("denied", canceled.json["agent_run"]["status"])

    def test_onboarding_selected_supported_app_prepares_real_setup_without_model(self):
        _, client, model = self.app([])
        completed = client.post("/api/onboarding/complete")
        self.assertEqual(200, completed.status_code)
        self.assertEqual("google_drive", completed.json["setup_card"]["connector_id"])
        self.assertEqual("needs_configuration", completed.json["setup_card"]["status"])
        self.assertEqual([], model.requests)
        self.assertEqual([], self.http_calls)

    def test_failed_callback_after_verified_provider_never_says_task_completed(self):
        app, client, _ = self.app([call("run_operation", connector_id="openai_api", operation_id="list_models"), OSError("model down")])
        client.post("/api/chat", json={"message": "List models"})
        result = client.post("/api/connectors/setup", json={"connector_id": "openai_api", "credentials": {"api_key": "fixture-secret"}})
        self.assertEqual(200, result.status_code)
        self.assertEqual("verified", result.json["connection"]["status"])
        self.assertEqual("failed", result.json["workspace_update"]["status"])
        self.assertEqual("failed", result.json["agent_run"]["status"])
        self.assertIn("could not finish", result.json["messages"][-1]["content"])

    def test_live_view_cannot_overwrite_pending_authorization(self):
        app, client, _ = self.app([call("connect_service", connector_id="openai_api")])
        paused = client.post("/api/chat", json={"message": "Connect OpenAI"})
        blocked = client.post("/api/connectors/live-view", json={"connector_id": "google_drive"})
        self.assertEqual(409, blocked.status_code)
        self.assertEqual(paused.json["setup_card"], self.store.setup_card(self.user))

    def test_cancel_invalidates_pending_oauth_state(self):
        self.runtime.env.update(GOOGLE_CLIENT_ID="client", GOOGLE_CLIENT_SECRET="secret")
        _, client, _ = self.app([call("connect_service", connector_id="google_drive")])
        paused = client.post("/api/chat", json={"message": "Connect Drive"})
        state = parse_qs(urlparse(paused.json["setup_card"]["action_url"]).query)["state"][0]
        canceled = client.post("/api/connectors/cancel", json={"connector_id": "google_drive"})
        callback = client.get("/api/connectors/oauth/callback", query_string={"state": state, "code": "unused"})
        self.assertIn("invalid_oauth_state", callback.location)
        self.assertIsNone(self.store.connection_status(self.user, "google_drive"))
        self.assertEqual([], self.http_calls)

    def test_missing_selected_provider_credentials_never_falls_back_to_server(self):
        _, client, model = self.app([AIMessage(content="Must not use server provider")])
        self.store.save_connection(self.user, "openai_api", "verified", {})
        self.store.save_connection_setting(self.user, "__runtime__", "agent_model", "openai_api")
        self.store.save_connection_setting(self.user, "openai_api", "model", "gpt-5-mini")
        result = client.post("/api/chat", json={"message": "Help me"})
        self.assertEqual(503, result.status_code)
        self.assertEqual([], model.requests)
        self.assertEqual("connector", result.json["agent_runtime"]["source"])
        self.assertIn("unavailable", result.json["agent_runtime"]["provider"])

    def test_revoked_selected_provider_never_falls_back_to_server(self):
        _, client, model = self.app([AIMessage(content="Must not use server provider")])
        self.store.save_connection(self.user, "openai_api", "needs_attention", {})
        self.store.save_connection_setting(self.user, "__runtime__", "agent_model", "openai_api")
        self.store.save_connection_setting(self.user, "openai_api", "model", "gpt-5-mini")
        result = client.post("/api/chat", json={"message": "Help me"})
        self.assertEqual(503, result.status_code)
        self.assertEqual([], model.requests)
        self.assertEqual("connector", result.json["agent_runtime"]["source"])
        self.assertIn("unavailable", result.json["agent_runtime"]["provider"])
