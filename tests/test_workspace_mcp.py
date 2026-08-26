import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from mcp import Client

from cordia.connector_runtime import ConnectorRuntime
from cordia.store import SURVEY_FIELDS, Store
from cordia.workspace_mcp import WorkspaceMCPClient, create_workspace_server


class WorkspaceMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(root / "cordia.db", root / "workspaces")
        self.user_id = self.store.register("person@example.com", "correct horse battery")
        self.other_user_id = self.store.register("other@example.com", "correct horse battery")
        for field, value in zip(
            SURVEY_FIELDS,
            ["Jordan", "Operations lead", "Find documents", "Google Drive", "Big picture"],
        ):
            self.store.save_survey_answer(self.user_id, field, value)
        self.store.save_connection(
            self.user_id,
            "google_drive",
            "verified",
            {"access_token": "never-expose-this-token"},
        )
        self.runtime = ConnectorRuntime(self.store, env={})

    def tearDown(self):
        self.temp.cleanup()

    def test_server_lists_only_the_bounded_workspace_tools(self):
        async def exercise():
            server = create_workspace_server(self.user_id, self.runtime, self.store)
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {
                        "connectors_search",
                        "connector_start",
                        "connector_status",
                        "connector_call",
                        "artifact_create",
                    },
                    {tool.name for tool in tools.tools},
                )
                result = await client.call_tool("connectors_search", {"query": "drive"})
                self.assertFalse(result.is_error)
                self.assertEqual(
                    "google_drive", result.structured_content["connectors"][0]["id"]
                )

        asyncio.run(exercise())

    def test_resources_are_bound_to_one_user_and_exclude_credentials(self):
        self.store.save_artifact(
            self.user_id,
            {"type": "table", "title": "Mine", "columns": ["Name"], "rows": [["Plan"]]},
        )
        self.store.save_artifact(
            self.other_user_id,
            {"type": "table", "title": "Not mine", "columns": ["Name"], "rows": [["Secret"]]},
        )

        async def exercise():
            server = create_workspace_server(self.user_id, self.runtime, self.store)
            async with Client(server) as client:
                operator = (await client.read_resource("cordia://operator")).contents[0].text
                connectors = (await client.read_resource("cordia://connectors")).contents[0].text
                artifacts = (await client.read_resource("cordia://artifacts")).contents[0].text
                self.assertIn("Jordan", operator)
                self.assertEqual("verified", json.loads(connectors)[0]["status"])
                self.assertNotIn("never-expose-this-token", connectors)
                self.assertIn("Mine", artifacts)
                self.assertNotIn("Not mine", artifacts)

        asyncio.run(exercise())

    def test_embedded_client_invokes_real_server_and_persists_artifact(self):
        client = WorkspaceMCPClient(self.runtime, self.store)
        artifact = {
            "type": "table",
            "title": "Recent files",
            "columns": ["Name"],
            "rows": [["Plan.md"]],
            "source": "google_drive",
        }

        result = client.call(self.user_id, "artifact_create", {"payload": artifact})

        self.assertEqual("Plan.md", result["artifact"]["rows"][0][0])
        self.assertEqual(result["artifact"]["id"], self.store.artifacts(self.user_id)[0]["id"])


if __name__ == "__main__":
    unittest.main()
