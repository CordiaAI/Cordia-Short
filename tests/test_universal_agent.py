import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

from cordia.agent import Agent
from cordia.agent_runs import AgentRuns
from cordia.store import Store
from cordia.workspace_mcp import WorkspaceMCPError
from tests.agent_helpers import ScriptedModel, call


class DynamicWorkspace:
    def __init__(self, store, *, read_only, annotation_key="readOnlyHint", fail_tools=()):
        self.store = store
        self.read_only = read_only
        self.annotation_key = annotation_key
        self.fail_tools = set(fail_tools)
        self.calls = []

    def call(self, user_id, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if tool_name == "connectors_search":
            return {"status": "ready", "connectors": [{"id": "app_alpha", "name": "Team Chat Alpha", "logo": "https://example.com/alpha.png"}]}
        if tool_name == "connector_tools":
            return {"tools": [
                {
                    "id": "opaque_action",
                    "name": "Send message",
                    "description": "A long provider description that should not be user-visible.",
                    "annotations": {self.annotation_key: self.read_only},
                },
                {
                    "id": "fallback_action",
                    "name": "Post message",
                    "description": "Another provider description that should stay internal.",
                    "annotations": {self.annotation_key: self.read_only},
                },
            ]}
        if tool_name == "connector_call":
            if arguments["tool_id"] in self.fail_tools:
                raise WorkspaceMCPError("provider action failed")
            artifact = {
                "type": "table", "title": "Provider result", "columns": ["status"],
                "rows": [["done"]], "source": "app_alpha", "operation_id": arguments["tool_id"],
            }
            artifact_id = self.store.save_artifact(user_id, artifact)
            return {"result": {"status": "done"}, "artifact": {**artifact, "id": artifact_id}}
        if tool_name == "connector_status":
            return {"connector_id": "app_alpha", "status": "verified"}
        raise AssertionError(tool_name)


class UniversalAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = Store(root / "cordia.db", root / "workspaces")
        self.user = self.store.register("agent@example.com", "correct-horse-battery")
        self.store.save_connection(self.user, "app_alpha", "verified", {"account_id": "account-1"})

    def service(self, workspace, replies):
        model = ScriptedModel(replies=replies)
        agent = Agent("fixture-key", "fixture-model", chat_model=model)
        return AgentRuns(self.store, workspace, lambda _user: agent)

    def test_read_only_discovered_tool_executes_without_static_operation_mapping(self):
        workspace = DynamicWorkspace(
            self.store, read_only=True, annotation_key="read_only_hint"
        )
        service = self.service(workspace, [
            call("run_application_tool", connector_id="app_alpha", tool_name="opaque_action", arguments={}),
            AIMessage(content="The provider returned the requested result."),
        ])

        result = service.start(self.user, "Read the latest provider data")

        self.assertEqual("completed", result["run"]["status"])
        self.assertTrue(any(name == "connector_call" for name, _ in workspace.calls))
        self.assertEqual("app_alpha", result["artifact"]["source"])

    def test_consequential_discovered_tool_waits_for_explicit_approval(self):
        workspace = DynamicWorkspace(self.store, read_only=False)
        service = self.service(workspace, [
            call("run_application_tool", connector_id="app_alpha", tool_name="opaque_action", arguments={"target": "person-1"}),
            AIMessage(content="The approved provider action completed."),
        ])

        paused = service.start(self.user, "Perform the provider action for person-1")

        self.assertEqual("waiting_connection", paused["run"]["status"])
        self.assertEqual("action_approval", paused["setup_card"]["type"])
        self.assertEqual("Send message in Team Chat Alpha", paused["setup_card"]["title"])
        self.assertEqual([{"label": "To", "value": "person-1"}], paused["setup_card"]["details"])
        self.assertEqual("Send", paused["setup_card"]["confirm_label"])
        self.assertNotIn("provider description", str(paused["setup_card"]).lower())
        self.assertEqual(["user"], [message["role"] for message in self.store.messages(self.user)])
        self.assertFalse(any(name == "connector_call" for name, _ in workspace.calls))

        completed = service.approve(self.user, "app_alpha", True)

        self.assertEqual("completed", completed["run"]["status"])
        self.assertEqual("Sent a message to person-1.", completed["assistant"])
        self.assertTrue(any(name == "connector_call" for name, _ in workspace.calls))

    def test_successful_action_retry_finishes_as_completed(self):
        workspace = DynamicWorkspace(
            self.store,
            read_only=False,
            fail_tools={"opaque_action"},
        )
        service = self.service(workspace, [
            call("run_application_tool", connector_id="app_alpha", tool_name="opaque_action", arguments={"target": "person-1"}),
            call("run_application_tool", connector_id="app_alpha", tool_name="fallback_action", arguments={"target": "person-1"}),
            AIMessage(content="Done. The requested message was delivered."),
        ])

        first = service.start(self.user, "Send the message to person-1")
        self.assertEqual("waiting_connection", first["run"]["status"])
        second = service.approve(self.user, "app_alpha", True)
        self.assertEqual("waiting_connection", second["run"]["status"])
        completed = service.approve(self.user, "app_alpha", True)

        self.assertEqual("completed", completed["run"]["status"])
        self.assertEqual("Sent a message to person-1.", completed["assistant"])


if __name__ == "__main__":
    unittest.main()
