from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
import httpx2

from .connectors import CONNECTORS, resolve_connector


class WorkspaceMCPError(RuntimeError):
    pass


_SERVER_ID = re.compile(r"^[A-Za-z0-9._:/-]{3,200}$")


def _public_connector(connector: dict, status: str | None = None) -> dict:
    return {
        "id": connector["id"],
        "name": connector["name"],
        "aliases": list(connector["aliases"]),
        "auth_kind": connector["auth"]["kind"],
        "operations": list(connector["operations"]),
        "status": status or "not_connected",
    }


def _validate_artifact(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("artifact payload must be an object")
    required = {"type", "title", "columns", "rows"}
    if not required.issubset(payload):
        raise ValueError("artifact payload is incomplete")
    if payload["type"] != "table":
        raise ValueError("artifact type is not supported")
    if not isinstance(payload["title"], str) or not payload["title"].strip():
        raise ValueError("artifact title is required")
    if not isinstance(payload["columns"], list) or not isinstance(payload["rows"], list):
        raise ValueError("artifact columns and rows must be lists")
    return dict(payload)


def create_workspace_server(user_id: int, runtime, store) -> MCPServer:
    server = MCPServer(
        "Cordia Workspace",
        instructions="Private tools and resources for one authenticated Cordia workspace.",
    )

    @server.tool(structured_output=True)
    def connectors_search(query: str) -> dict[str, Any]:
        """Find a supported connector without exposing credentials or server configuration."""
        connector = resolve_connector(query)
        return {"connectors": [_public_connector(connector)] if connector else []}

    @server.tool(structured_output=True)
    def connector_start(connector_id: str) -> dict[str, Any]:
        """Prepare the real authorization flow for a supported connector."""
        return runtime.start_connection(user_id, connector_id)

    @server.tool(structured_output=True)
    def connector_status(connector_id: str) -> dict[str, Any]:
        """Read the verified connection state for a supported connector."""
        connector = resolve_connector(connector_id)
        if not connector:
            raise ValueError(f"connector is not supported: {connector_id}")
        return {
            "connector_id": connector["id"],
            "status": store.connection_status(user_id, connector["id"]) or "not_connected",
        }

    @server.tool(structured_output=True)
    def connector_call(
        connector_id: str, operation_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one declared operation on a verified connector."""
        return {"artifact": runtime.call_operation(user_id, connector_id, operation_id, inputs)}

    @server.tool(structured_output=True)
    def artifact_create(payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one validated DashView artifact in this workspace."""
        artifact = _validate_artifact(payload)
        artifact_id = store.save_artifact(user_id, artifact)
        return {"artifact": {**artifact, "id": artifact_id}}

    @server.resource("cordia://operator")
    def operator_resource() -> str:
        """The workspace's current human-readable operator profile."""
        return store.operator_markdown(user_id)

    @server.resource("cordia://connectors")
    def connectors_resource() -> str:
        """Supported connectors and this workspace's non-secret connection states."""
        return json.dumps(
            [
                _public_connector(
                    connector, store.connection_status(user_id, connector["id"])
                )
                for connector in CONNECTORS.values()
            ]
        )

    @server.resource("cordia://artifacts")
    def artifacts_resource() -> str:
        """Saved artifacts belonging to this workspace."""
        return json.dumps(store.artifacts(user_id))

    return server


class WorkspaceMCPClient:
    def __init__(
        self,
        runtime,
        store,
        *,
        registry_base_url: str = "https://registry.modelcontextprotocol.io",
    ):
        self.runtime = runtime
        self.store = store
        self.registry_base_url = registry_base_url.rstrip("/")

    def call(self, user_id: int, tool_name: str, arguments: dict) -> dict:
        async def invoke() -> dict:
            server = create_workspace_server(user_id, self.runtime, self.store)
            async with Client(server) as client:
                result = await client.call_tool(tool_name, arguments)
            if result.is_error:
                message = "workspace tool failed"
                if result.content and hasattr(result.content[0], "text"):
                    message = result.content[0].text
                raise WorkspaceMCPError(message)
            if not isinstance(result.structured_content, dict):
                raise WorkspaceMCPError("workspace tool returned no structured result")
            return result.structured_content

        try:
            return asyncio.run(invoke())
        except WorkspaceMCPError:
            raise
        except Exception as exc:
            raise WorkspaceMCPError("workspace tool unavailable") from exc

    @staticmethod
    def _remote_definition(definition: dict) -> dict:
        server_id = str(definition.get("name", "")).strip()
        if not _SERVER_ID.fullmatch(server_id):
            raise ValueError("MCP server name is invalid")
        title = str(definition.get("title") or server_id).strip()
        version = str(definition.get("version", "")).strip()
        if not version:
            raise ValueError("MCP server version is required")
        remote = next(
            (
                item
                for item in definition.get("remotes", [])
                if isinstance(item, dict) and item.get("type") == "streamable-http"
            ),
            None,
        )
        if not remote:
            raise ValueError("MCP server has no supported remote transport")
        endpoint = str(remote.get("url", "")).strip()
        parsed = urlparse(endpoint)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("MCP server endpoint must use HTTPS")
        if not parsed.netloc:
            raise ValueError("MCP server endpoint is invalid")
        headers = []
        for item in remote.get("headers", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", name):
                raise ValueError("MCP server header name is invalid")
            headers.append(
                {
                    "name": name,
                    "description": str(item.get("description") or name).strip()[:200],
                    "is_required": bool(item.get("isRequired", False)),
                    "is_secret": bool(item.get("isSecret", False)),
                }
            )
        return {
            "server_id": server_id,
            "title": title[:200],
            "version": version[:100],
            "transport": "streamable-http",
            "endpoint": endpoint,
            "headers": headers,
        }

    def install_server(self, user_id: int, definition: dict) -> dict:
        server = self._remote_definition(definition)
        payload = {
            key: server[key]
            for key in ("title", "version", "transport", "endpoint", "headers")
        }
        self.store.save_mcp_server(user_id, server["server_id"], payload, "installed")
        return {**server, "status": "installed"}

    def search_registry(self, query: str) -> list[dict]:
        clean = str(query).strip()
        if not clean or len(clean) > 200:
            raise ValueError("registry query is invalid")
        url = f"{self.registry_base_url}/v0.1/servers?{urlencode({'search': clean, 'version': 'latest'})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "Cordia/1"})
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read(1_000_001))
        except Exception as exc:
            raise WorkspaceMCPError("MCP registry search failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("servers"), list):
            raise WorkspaceMCPError("MCP registry returned an invalid response")
        matches = []
        for record in payload["servers"][:50]:
            if not isinstance(record, dict) or not isinstance(record.get("server"), dict):
                continue
            official = record.get("_meta", {}).get(
                "io.modelcontextprotocol.registry/official", {}
            )
            if official.get("status") not in {None, "active"}:
                continue
            try:
                server = self._remote_definition(record["server"])
            except ValueError:
                continue
            matches.append(server)
        return matches

    def install_registry_server(self, user_id: int, server_id: str) -> dict:
        exact = next(
            (
                item
                for item in self.search_registry(server_id)
                if item["server_id"] == server_id
            ),
            None,
        )
        if not exact:
            raise WorkspaceMCPError("MCP server was not found in the registry")
        return self.install_server(
            user_id,
            {
                "name": exact["server_id"],
                "title": exact["title"],
                "version": exact["version"],
                "remotes": [
                    {
                        "type": exact["transport"],
                        "url": exact["endpoint"],
                        "headers": [
                            {
                                "name": item["name"],
                                "description": item["description"],
                                "isRequired": item["is_required"],
                                "isSecret": item["is_secret"],
                            }
                            for item in exact.get("headers", [])
                        ],
                    }
                ],
            },
        )

    def server_setup_card(self, user_id: int, server_id: str) -> dict:
        server = self._server(user_id, server_id)
        fields = [
            {
                "name": item["name"],
                "label": item["description"],
                "type": "password" if item["is_secret"] else "text",
                "required": item["is_required"],
            }
            for item in server.get("headers", [])
        ]
        if not fields:
            raise WorkspaceMCPError("MCP server requires no credential setup")
        return {
            "type": "credential_form",
            "connector_id": f"mcp:{server_id}",
            "title": f"Connect {server['title']}",
            "message": "Enter only the values this MCP server requires. Cordia stores secrets encrypted and sends them only to this server.",
            "fields": fields,
            "submit_url": "/api/connectors/setup",
            "status": "authorization_required",
        }

    def _server(self, user_id: int, server_id: str) -> dict:
        server = self.store.mcp_server(user_id, server_id)
        if not server:
            raise WorkspaceMCPError("MCP server is not installed")
        if server.get("transport") != "streamable-http":
            raise WorkspaceMCPError("MCP server transport is not supported")
        return server

    @asynccontextmanager
    async def _remote_client(self, user_id: int, server: dict):
        credentials = self.store.connection_credentials(
            user_id, f"mcp:{server['server_id']}"
        ) or {}
        headers = credentials.get("headers") or {}
        if headers:
            async with httpx2.AsyncClient(headers=headers, timeout=30) as http_client:
                transport = streamable_http_client(
                    server["endpoint"], http_client=http_client
                )
                async with Client(transport) as client:
                    yield client
        else:
            async with Client(server["endpoint"]) as client:
                yield client

    def discover_server(self, user_id: int, server_id: str) -> list[dict]:
        server = self._server(user_id, server_id)

        async def discover() -> list[dict]:
            async with self._remote_client(user_id, server) as client:
                result = await client.list_tools()
            return [
                {
                    "name": item.name,
                    "title": item.title,
                    "description": item.description,
                    "input_schema": item.input_schema,
                    "annotations": item.annotations.model_dump(mode="json")
                    if item.annotations
                    else {},
                }
                for item in result.tools
            ]

        try:
            tools = asyncio.run(discover())
        except Exception as exc:
            raise WorkspaceMCPError("MCP server discovery failed") from exc
        payload = {
            key: server[key]
            for key in ("title", "version", "transport", "endpoint", "headers")
        }
        payload["tools"] = tools
        self.store.save_mcp_server(user_id, server_id, payload, "verified")
        return tools

    def finish_server_setup(
        self, user_id: int, server_id: str, values: dict
    ) -> dict:
        server = self._server(user_id, server_id)
        declared = {item["name"]: item for item in server.get("headers", [])}
        if not declared:
            raise WorkspaceMCPError("MCP server requires no credential setup")
        if set(values) - set(declared):
            raise ValueError("MCP setup contains an undeclared field")
        headers = {}
        for name, item in declared.items():
            value = str(values.get(name, "")).strip()
            if item["is_required"] and not value:
                raise ValueError(f"{name} is required")
            if value:
                headers[name] = value
        self.store.save_connection(
            user_id, f"mcp:{server_id}", "verification_pending", {"headers": headers}
        )
        try:
            tools = self.discover_server(user_id, server_id)
        except Exception:
            self.store.save_connection(user_id, f"mcp:{server_id}", "failed", {})
            raise
        self.store.save_connection(user_id, f"mcp:{server_id}", "verified")
        return {"server_id": server_id, "status": "verified", "tools": tools}

    @staticmethod
    def _artifact(server: dict, tool_name: str, result: dict) -> dict:
        collection = next(
            (value for value in result.values() if isinstance(value, list)), None
        )
        if collection is not None and all(isinstance(item, dict) for item in collection):
            columns = list(dict.fromkeys(key for item in collection for key in item))
            rows = [
                [
                    item.get(column)
                    if isinstance(item.get(column), (str, int, float, bool, type(None)))
                    else json.dumps(item.get(column), sort_keys=True)
                    for column in columns
                ]
                for item in collection
            ]
        else:
            columns = ["Field", "Value"]
            rows = [
                [
                    key,
                    value
                    if isinstance(value, (str, int, float, bool, type(None)))
                    else json.dumps(value, sort_keys=True),
                ]
                for key, value in result.items()
            ]
        return {
            "type": "table",
            "title": server["title"],
            "connector_name": server["title"],
            "source": f"mcp:{server['server_id']}",
            "operation_id": tool_name,
            "columns": columns,
            "rows": rows,
        }

    def call_server_tool(
        self, user_id: int, server_id: str, tool_name: str, arguments: dict
    ) -> dict:
        server = self._server(user_id, server_id)

        async def invoke() -> dict:
            async with self._remote_client(user_id, server) as client:
                result = await client.call_tool(tool_name, arguments)
            if result.is_error:
                raise WorkspaceMCPError("MCP tool returned an error")
            if not isinstance(result.structured_content, dict):
                raise WorkspaceMCPError("MCP tool returned no structured result")
            return result.structured_content

        try:
            structured = asyncio.run(invoke())
        except WorkspaceMCPError:
            raise
        except Exception as exc:
            raise WorkspaceMCPError("MCP tool call failed") from exc
        artifact = self._artifact(server, tool_name, structured)
        artifact_id = self.store.save_artifact(user_id, artifact)
        return {"result": structured, "artifact": {**artifact, "id": artifact_id}}
