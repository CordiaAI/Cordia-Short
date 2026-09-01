import asyncio
import json
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.server import MCPServer
import uvicorn

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

    def test_generic_remote_server_is_discovered_called_and_saved_as_an_artifact(self):
        remote = MCPServer("Example Work Server")

        @remote.tool(structured_output=True)
        def list_work_items() -> dict[str, Any]:
            """Return provider-owned work items."""
            return {
                "items": [
                    {"title": "Prepare launch", "status": "open"},
                    {"title": "Verify release", "status": "done"},
                ]
            }

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        server = uvicorn.Server(
            uvicorn.Config(
                remote.streamable_http_app(stateless_http=True, json_response=True),
                host="127.0.0.1",
                port=port,
                log_level="critical",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 5
        while not server.started and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(server.started)

        try:
            client = WorkspaceMCPClient(self.runtime, self.store)
            installed = client.install_server(
                self.user_id,
                {
                    "name": "com.example/work",
                    "title": "Example Work",
                    "version": "1.0.0",
                    "remotes": [
                        {
                            "type": "streamable-http",
                            "url": f"http://127.0.0.1:{port}/mcp",
                        }
                    ],
                },
            )

            self.assertEqual("com.example/work", installed["server_id"])
            tools = client.discover_server(self.user_id, "com.example/work")
            self.assertEqual(["list_work_items"], [item["name"] for item in tools])

            called = client.call_server_tool(
                self.user_id, "com.example/work", "list_work_items", {}
            )

            self.assertEqual("Prepare launch", called["result"]["items"][0]["title"])
            self.assertEqual("Example Work", called["artifact"]["connector_name"])
            self.assertEqual(
                [["Prepare launch", "open"], ["Verify release", "done"]],
                called["artifact"]["rows"],
            )
            self.assertEqual(1, len(self.store.artifacts(self.user_id)))
            self.assertNotIn("example", json.dumps(self.store.mcp_servers(self.other_user_id)))
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    def test_official_registry_shape_installs_a_remote_without_provider_branches(self):
        registry_payload = {
            "servers": [
                {
                    "server": {
                        "name": "com.example/work",
                        "title": "Example Work",
                        "version": "2.0.0",
                        "remotes": [
                            {
                                "type": "streamable-http",
                                "url": "https://mcp.example.com/mcp",
                            }
                        ],
                    },
                    "_meta": {
                        "io.modelcontextprotocol.registry/official": {
                            "status": "active",
                            "isLatest": True,
                        }
                    },
                }
            ],
            "metadata": {"count": 1},
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(registry_payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        registry = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=registry.serve_forever, daemon=True)
        thread.start()
        try:
            client = WorkspaceMCPClient(
                self.runtime,
                self.store,
                registry_base_url=f"http://127.0.0.1:{registry.server_port}",
            )

            matches = client.search_registry("work")
            installed = client.install_registry_server(self.user_id, "com.example/work")

            self.assertEqual(["com.example/work"], [item["server_id"] for item in matches])
            self.assertEqual("streamable-http", installed["transport"])
            self.assertEqual(
                "https://mcp.example.com/mcp",
                self.store.mcp_server(self.user_id, "com.example/work")["endpoint"],
            )
        finally:
            registry.shutdown()
            registry.server_close()
            thread.join(timeout=5)

    def test_registry_declared_secret_header_uses_generic_setup_card_and_encrypted_store(self):
        client = WorkspaceMCPClient(self.runtime, self.store)
        installed = client.install_server(
            self.user_id,
            {
                "name": "com.example/private",
                "title": "Private Work",
                "version": "1.0.0",
                "remotes": [
                    {
                        "type": "streamable-http",
                        "url": "https://private.example.com/mcp",
                        "headers": [
                            {
                                "name": "X-API-Key",
                                "description": "Workspace API key",
                                "isRequired": True,
                                "isSecret": True,
                            }
                        ],
                    }
                ],
            },
        )

        card = client.server_setup_card(self.user_id, installed["server_id"])

        self.assertEqual("credential_form", card["type"])
        self.assertEqual("/api/connectors/setup", card["submit_url"])
        self.assertEqual("mcp:com.example/private", card["connector_id"])
        self.assertEqual("X-API-Key", card["fields"][0]["name"])
        self.assertNotIn("secret-value", json.dumps(card))

    def test_generic_header_setup_is_verified_by_the_real_remote_server(self):
        remote = MCPServer("Protected Work")

        @remote.tool(structured_output=True)
        def list_items() -> dict[str, Any]:
            """Return protected provider data."""
            return {"items": [{"name": "Private item"}]}

        mcp_app = remote.streamable_http_app(stateless_http=True, json_response=True)

        async def protected_app(scope, receive, send):
            headers = dict(scope.get("headers", []))
            if scope.get("type") == "http" and headers.get(b"x-api-key") != b"correct-key":
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
            await mcp_app(scope, receive, send)

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        server = uvicorn.Server(
            uvicorn.Config(protected_app, host="127.0.0.1", port=port, log_level="critical")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 5
        while not server.started and time.time() < deadline:
            time.sleep(0.01)
        try:
            client = WorkspaceMCPClient(self.runtime, self.store)
            client.install_server(
                self.user_id,
                {
                    "name": "com.example/protected",
                    "title": "Protected Work",
                    "version": "1.0.0",
                    "remotes": [
                        {
                            "type": "streamable-http",
                            "url": f"http://127.0.0.1:{port}/mcp",
                            "headers": [
                                {
                                    "name": "X-API-Key",
                                    "isRequired": True,
                                    "isSecret": True,
                                }
                            ],
                        }
                    ],
                },
            )

            verified = client.finish_server_setup(
                self.user_id, "com.example/protected", {"X-API-Key": "correct-key"}
            )

            self.assertEqual("verified", verified["status"])
            self.assertEqual(["list_items"], [item["name"] for item in verified["tools"]])
            with self.store._connection() as db:
                encrypted = db.execute(
                    "SELECT credentials FROM connections WHERE user_id=? AND connector_id=?",
                    (self.user_id, "mcp:com.example/protected"),
                ).fetchone()["credentials"]
            self.assertNotIn("correct-key", encrypted)
        finally:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
