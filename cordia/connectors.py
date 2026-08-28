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
        "post_connect_operation": "list_recent_files",
        "live_view": {
            "operation": "list_recent_files",
            "logo": "/static/assets/google-drive.png",
            "required_scopes": [
                "https://www.googleapis.com/auth/drive.metadata.readonly"
            ],
            "permission": {
                "summary": "Open a live, read-only view of your recent Google Drive files inside Cordia.",
                "data": ["File names", "File types", "Modified dates", "Google Drive links"],
                "actions": ["Refresh recent files", "Open a file in Google Drive"],
                "revocation": "You can remove Cordia from your Google Account permissions at any time.",
                "authorize_label": "Continue with Google",
            },
        },
    },
    "openai_api": {
        "id": "openai_api",
        "name": "OpenAI API",
        "aliases": ["openai", "openai api", "chatgpt api"],
        "auth": {
            "kind": "api_key",
            "fields": [
                {
                    "name": "api_key",
                    "label": "OpenAI API key",
                    "type": "password",
                    "required": True,
                }
            ],
            "header": {"name": "Authorization", "template": "Bearer {api_key}"},
            "verify_operation": "list_models",
        },
        "selector": {
            "setting": "model",
            "label": "Use model",
            "operation": "list_models",
            "value_field": "id",
            "runtime_role": "agent_model",
            "credential_field": "api_key",
            "exclude_value_patterns": [
                "embedding|image|audio|realtime|transcribe|whisper|tts|moderation|dall-e"
            ],
        },
        "operations": {
            "list_models": {
                "method": "GET",
                "url": "https://api.openai.com/v1/models",
                "result_key": "data",
                "artifact": {
                    "type": "table",
                    "title": "Available OpenAI models",
                    "columns": ["Model", "Owner"],
                    "fields": ["id", "owned_by"],
                },
            }
        },
        "post_connect_operation": "list_models",
    },
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
            if not operation["url"].startswith("https://"):
                raise ValueError(f"{connector_id}.{operation_id}: provider url must use HTTPS")
            artifact = operation.get("artifact")
            if not isinstance(artifact, dict) or not artifact.get("fields"):
                raise ValueError(f"{connector_id}.{operation_id}: artifact mapping is required")
        post_connect_operation = connector.get("post_connect_operation")
        if post_connect_operation and post_connect_operation not in operations:
            raise ValueError(f"{connector_id}: post-connect operation must be declared")
        live_view = connector.get("live_view")
        if live_view:
            if live_view.get("operation") not in operations:
                raise ValueError(f"{connector_id}: live-view operation must be declared")
            if not live_view.get("logo") or not str(live_view["logo"]).startswith("/static/"):
                raise ValueError(f"{connector_id}: live-view logo must be a local static asset")
            scopes = live_view.get("required_scopes")
            permission = live_view.get("permission")
            if not isinstance(scopes, list):
                raise ValueError(f"{connector_id}: live-view scopes must be a list")
            if not isinstance(permission, dict) or not all(
                permission.get(field)
                for field in ("summary", "data", "actions", "revocation", "authorize_label")
            ):
                raise ValueError(f"{connector_id}: live-view permission copy is required")
        if auth["kind"] == "api_key":
            fields = auth.get("fields")
            header = auth.get("header")
            verify_operation = auth.get("verify_operation")
            if not isinstance(fields, list) or not fields:
                raise ValueError(f"{connector_id}: API key fields are required")
            if any(
                not isinstance(field, dict)
                or not field.get("name")
                or not field.get("label")
                for field in fields
            ):
                raise ValueError(f"{connector_id}: each API key field needs a name and label")
            if any(field.get("type") != "password" for field in fields):
                raise ValueError(f"{connector_id}: API key fields must use password inputs")
            field_names = {field["name"] for field in fields}
            if len(field_names) != len(fields):
                raise ValueError(f"{connector_id}: API key field names must be unique")
            if not isinstance(header, dict) or not header.get("name") or not header.get("template"):
                raise ValueError(f"{connector_id}: API key header is required")
            try:
                header["template"].format(**{name: "credential" for name in field_names})
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{connector_id}: API key header references an unknown field") from exc
            if verify_operation not in operations:
                raise ValueError(f"{connector_id}: API key verification operation is required")
        selector = connector.get("selector")
        if selector:
            operation = operations.get(selector.get("operation"))
            if not selector.get("setting") or not selector.get("label") or not operation:
                raise ValueError(f"{connector_id}: selector setting, label, and operation are required")
            if selector.get("value_field") not in operation["artifact"]["fields"]:
                raise ValueError(f"{connector_id}: selector value field must be in the artifact")
            if selector.get("runtime_role") == "agent_model":
                credential_fields = {field["name"] for field in auth.get("fields", [])}
                if selector.get("credential_field") not in credential_fields:
                    raise ValueError(f"{connector_id}: selector credential field is required")
            patterns = selector.get("exclude_value_patterns", [])
            if not isinstance(patterns, list):
                raise ValueError(f"{connector_id}: selector exclusion patterns must be a list")
            try:
                for pattern in patterns:
                    re.compile(pattern)
            except (TypeError, re.error) as exc:
                raise ValueError(f"{connector_id}: selector exclusion pattern is invalid") from exc


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def resolve_connector(value: str) -> dict | None:
    wanted = _normalize(value)
    for connector in CONNECTORS.values():
        names = {connector["id"], connector["name"], *connector["aliases"]}
        if wanted in {_normalize(name) for name in names}:
            return connector
    return None


def agent_catalog() -> str:
    lines = ["Supported connector catalog:"]
    for connector in CONNECTORS.values():
        operations = ", ".join(connector["operations"])
        lines.append(
            f"- {connector['id']}: {connector['name']} | auth={connector['auth']['kind']} | operations={operations}"
        )
    return "\n".join(lines)


validate_registry()

