from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import Client
from mcp.server import MCPServer

from .connectors import CONNECTORS, resolve_connector


class WorkspaceMCPError(RuntimeError):
    pass


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
    def __init__(self, runtime, store):
        self.runtime = runtime
        self.store = store

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
