import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

from cordia.agent import Agent
from cordia.agent_runs import AgentRuns, format_agent_response
from cordia.store import Store
from tests.agent_helpers import ScriptedModel


class AgentRunContractTests(unittest.TestCase):
    def test_workspace_action_starter_is_fresh_and_cannot_reuse_prior_inputs(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = Store(root / "cordia.db", root / "workspaces")
        user = store.register("fresh-action@example.com", "correct-horse-battery")
        store.add_message(user, "user", "Send test to person-1")
        store.add_message(user, "assistant", 'Sent "test" to person-1.')
        model = ScriptedModel(replies=[
            AIMessage(content="Who should receive the message, and what should it say?")
        ])
        agent = Agent("fixture-key", "fixture-model", chat_model=model)

        class NoToolsWorkspace:
            def call(self, *_args, **_kwargs):
                raise AssertionError("an underspecified fresh action must not execute a tool")

        service = AgentRuns(store, NoToolsWorkspace(), lambda _user: agent)

        result = service.start(
            user,
            "Send message in Team Chat Alpha.",
            action_starter={
                "connector_id": "app_alpha",
                "application_name": "Team Chat Alpha",
                "action_id": "send-message",
                "label": "Send message",
                "prompt": "Send message in Team Chat Alpha.",
            },
        )

        system = model.requests[0][0].content.lower()
        self.assertIn("fresh action request", system)
        self.assertIn("do not reuse", system)
        self.assertIn("recipient", system)
        self.assertEqual("Send message in Team Chat Alpha.", model.requests[0][-1].content)
        self.assertEqual(
            "Who should receive the message, and what should it say?",
            result["assistant"],
        )

    def test_artifact_context_reaches_the_model_without_changing_the_visible_message(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = Store(root / "cordia.db", root / "workspaces")
        user = store.register("artifact@example.com", "correct-horse-battery")
        model = ScriptedModel(replies=[AIMessage(content="I used the workspace view.")])
        agent = Agent("fixture-key", "fixture-model", chat_model=model)

        class NoToolsWorkspace:
            def call(self, *_args, **_kwargs):
                raise AssertionError("no workspace tool expected")

        service = AgentRuns(store, NoToolsWorkspace(), lambda _user: agent)

        service.start(
            user,
            "Draft the update",
            context='{"title":"Team chat","source":"chat_app","rows":[["Launch","Ready"]]}',
        )

        self.assertEqual("Draft the update", store.messages(user)[0]["content"])
        self.assertIn("Team chat", model.requests[0][-1].content)
        self.assertIn("not user-authored", model.requests[0][-1].content)

    def test_workspace_build_uses_fde_without_persisting_a_user_chat_message(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = Store(root / "cordia.db", root / "workspaces")
        user = store.register("builder@example.com", "correct-horse-battery")
        store.fde_markdown = lambda _user: "# Forward Deployed Engineer workspace build"
        store.agent_context = lambda _user: "# Forward Deployed Engineer workspace build"
        model = ScriptedModel(replies=[AIMessage(content="The initial workspace is ready.")])
        agent = Agent("fixture-key", "fixture-model", chat_model=model)

        class NoToolsWorkspace:
            def call(self, *_args, **_kwargs):
                raise AssertionError("no workspace tool expected")

        service = AgentRuns(store, NoToolsWorkspace(), lambda _user: agent)

        result = service.start_workspace_build(user)

        self.assertEqual("completed", result["run"]["status"])
        self.assertFalse(any(message["role"] == "user" for message in store.messages(user)))
        self.assertIn("Execute the compiled fde.md", model.requests[0][-1].content)
        self.assertIn("Forward Deployed Engineer workspace build", model.requests[0][0].content)

    def test_discovered_application_tools_are_compacted_before_agent_context(self):
        tools = [
            {
                "id": f"app_alpha-operation-{index}",
                "name": f"Operation {index}",
                "description": "provider description " * 100,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string", "description": "detail " * 100},
                        "optional_note": {"type": "string", "description": "detail " * 100},
                    },
                    "required": ["record_id"],
                },
                "annotations": {"read_only_hint": True},
            }
            for index in range(160)
        ]

        safe = AgentRuns._safe_result({"tools": tools})

        self.assertEqual(160, safe["tool_count"])
        self.assertEqual(160, len(safe["tools"]))
        self.assertEqual(
            {
                "id": "app_alpha-operation-159",
                "required": {"record_id": "string"},
                "read_only": True,
            },
            safe["tools"][-1],
        )
        self.assertLess(len(json.dumps(safe)), 20_000)

    def test_visible_agent_response_is_one_outcome_sentence(self):
        response = format_agent_response(
            "The catalog request failed. I can retry it. Evidence: provider timeout. "
            "https://provider.example/trace/123"
        )

        self.assertEqual("The catalog request failed.", response)
        self.assertNotIn("http", response)

    def test_completed_action_copy_drops_provider_evidence_noise(self):
        response = format_agent_response(
            "Sent a message to Jude. "
            "- Permalink: https://provider.example/message/123. "
            "- Evidence: channel ABC123, ts 456."
        )

        self.assertEqual("Sent a message to Jude.", response)

    def test_full_reply_is_retained_for_revision_while_visible_copy_is_bounded(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = Store(root / "cordia.db", root / "workspaces")
        user = store.register("agent@example.com", "correct-horse-battery")
        full = "First fact. Second fact. Third fact. Fourth internal detail remains available."
        model = ScriptedModel(replies=[AIMessage(content=full), AIMessage(content="Revised response.")])
        agent = Agent("fixture-key", "fixture-model", chat_model=model)

        class NoToolsWorkspace:
            def call(self, *_args, **_kwargs):
                raise AssertionError("no workspace tool expected")

        service = AgentRuns(store, NoToolsWorkspace(), lambda _user: agent)
        original = service.start(user, "Summarize")
        response_id = store.messages(user)[-1]["id"]
        with store._connection() as database:
            saved = database.execute("SELECT assistant FROM agent_runs WHERE response_id = ?", (response_id,)).fetchone()["assistant"]

        self.assertNotIn("Fourth internal detail", original["assistant"])
        self.assertEqual(full, saved)
        service.revise(user, response_id)
        self.assertIn("Fourth internal detail", model.requests[-1][0].content)


if __name__ == "__main__":
    unittest.main()
