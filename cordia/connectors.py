from __future__ import annotations

import re


CONNECTORS = {
    "google_drive": {
        "id": "google_drive",
        "name": "Google Drive",
        "aliases": ["google drive", "drive", "gdrive"],
        "auth": {
            "kind": "oauth2",
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
            "callback_path": "/api/connectors/oauth/callback",
        },
        "operations": {
            "list_recent_files": {
                "method": "GET",
                "url": "https://www.googleapis.com/drive/v3/files",
                "query": {
                    "pageSize": "20",
                    "orderBy": "modifiedTime desc",
                    "q": "trashed=false",
                    "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
                },
                "result_key": "files",
                "artifact": {
                    "type": "table",
                    "title": "Recent Google Drive files",
                    "columns": ["Name", "Type", "Modified", "Open"],
                    "fields": ["name", "mimeType", "modifiedTime", "webViewLink"],
                },
            }
        },
    }
}


def validate_registry(registry: dict | None = None) -> None:
    registry = registry or CONNECTORS
    for connector_id, connector in registry.items():
        if connector.get("id") != connector_id:
            raise ValueError(f"{connector_id}: id must match dictionary key")
        if not connector.get("name"):
            raise ValueError(f"{connector_id}: name is required")
        if not isinstance(connector.get("aliases"), list):
            raise ValueError(f"{connector_id}: aliases must be a list")
        auth = connector.get("auth")
        if not isinstance(auth, dict) or auth.get("kind") not in {"oauth2", "api_key", "remote_mcp"}:
            raise ValueError(f"{connector_id}: supported auth kind is required")
        operations = connector.get("operations")
        if not isinstance(operations, dict) or not operations:
            raise ValueError(f"{connector_id}: operations are required")
        for operation_id, operation in operations.items():
            if operation.get("method") not in {"GET", "POST"} or not operation.get("url"):
                raise ValueError(f"{connector_id}.{operation_id}: method and url are required")
            artifact = operation.get("artifact")
            if not isinstance(artifact, dict) or not artifact.get("fields"):
                raise ValueError(f"{connector_id}.{operation_id}: artifact mapping is required")


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def resolve_connector(value: str) -> dict | None:
    wanted = _normalize(value)
    for connector in CONNECTORS.values():
        names = {connector["id"], connector["name"], *connector["aliases"]}
        if wanted in {_normalize(name) for name in names}:
            return connector
    return None


validate_registry()

