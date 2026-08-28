from __future__ import annotations

import json
import re
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from .connectors import CONNECTORS, resolve_connector


class ConnectorError(RuntimeError):
    pass


def _http_transport(method: str, url: str, headers: dict, data: dict | None, timeout: int) -> dict:
    body = None
    request_headers = dict(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise OSError(f"provider returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OSError("provider response unavailable") from exc


class ConnectorRuntime:
    def __init__(
        self,
        store,
        env: Mapping[str, str] | None = None,
        transport: Callable[[str, str, dict, dict | None, int], dict] | None = None,
    ):
        self.store = store
        self.env = os.environ if env is None else env
        self.transport = transport or _http_transport

    @staticmethod
    def _connector(value: str) -> dict:
        connector = resolve_connector(value)
        if not connector:
            raise ConnectorError(f"connector is not supported: {value}")
        return connector

    def _redirect_uri(self, connector: dict) -> str:
        base_url = self.env.get("CORDIA_BASE_URL", "http://127.0.0.1:5050").rstrip("/")
        return base_url + connector["auth"]["callback_path"]

    def start_connection(
        self, user_id: int, connector_id: str, requested_scopes: list[str] | None = None
    ) -> dict:
        connector = self._connector(connector_id)
        auth = connector["auth"]
        if auth["kind"] == "api_key":
            return {
                "type": "credential_form",
                "connector_id": connector["id"],
                "title": f"Connect {connector['name']}",
                "status": "ready",
                "message": "Enter the credential below. Cordia verifies it directly with the provider and never sends it to the agent.",
                "submit_url": "/api/connectors/setup",
                "fields": [dict(field) for field in auth["fields"]],
            }
        if auth["kind"] != "oauth2":
            raise ConnectorError(f"auth protocol is not implemented: {auth['kind']}")
        required = [auth["client_id_env"], auth["client_secret_env"]]
        missing = [name for name in required if not self.env.get(name)]
        if missing:
            return {
                "type": "connector_setup",
                "connector_id": connector["id"],
                "title": f"Connect {connector['name']}",
                "status": "needs_configuration",
                "message": "Server configuration missing: " + ", ".join(missing),
            }
        scopes = [auth["scope"], *(requested_scopes or [])]
        scopes = list(dict.fromkeys(scope for scope in scopes if scope))
        state = self.store.create_oauth_state(
            user_id, connector["id"], requested_scopes=scopes
        )
        query = urllib.parse.urlencode(
            {
                "client_id": self.env[auth["client_id_env"]],
                "redirect_uri": self._redirect_uri(connector),
                "response_type": "code",
                "scope": " ".join(scopes),
                "access_type": "offline",
                "include_granted_scopes": "true" if requested_scopes else "false",
                "prompt": "consent",
                "state": state,
            }
        )
        return {
            "type": "oauth_redirect",
            "connector_id": connector["id"],
            "title": f"Connect {connector['name']}",
            "status": "ready",
            "message": "Continue to the provider to approve read-only access.",
            "action_url": auth["authorize_url"] + "?" + query,
        }

    def live_view_access(self, user_id: int, connector_id: str) -> dict:
        connector = self._connector(connector_id)
        live_view = connector.get("live_view")
        if not live_view:
            return {"status": "unsupported", "connector_id": connector["id"]}
        credentials_available = True
        try:
            credentials = self.store.connection_credentials(user_id, connector["id"]) or {}
        except RuntimeError:
            credentials = {}
            credentials_available = False
        granted_scopes = set(str(credentials.get("scope", "")).split())
        required_scopes = list(live_view.get("required_scopes", []))
        missing_scopes = [scope for scope in required_scopes if scope not in granted_scopes]
        status = "granted"
        if (
            self.store.connection_status(user_id, connector["id"]) != "verified"
            or not credentials_available
        ):
            status = "needs_connection"
        elif missing_scopes:
            status = "needs_authorization"
        return {
            "status": status,
            "connector_id": connector["id"],
            "connector_name": connector["name"],
            "operation": live_view["operation"],
            "logo": live_view["logo"],
            "required_scopes": required_scopes,
            "missing_scopes": missing_scopes,
            "permission": dict(live_view["permission"]),
        }

    def finish_connection(self, user_id: int, connector_id: str, setup_result: dict) -> dict:
        connector = self._connector(connector_id)
        auth_kind = connector["auth"]["kind"]
        if auth_kind == "api_key":
            return self._finish_api_key(user_id, connector, setup_result)
        if auth_kind != "oauth2":
            raise ConnectorError(f"auth protocol is not implemented: {auth_kind}")
        return self._finish_oauth2(user_id, connector, setup_result)

    def _finish_oauth2(self, user_id: int, connector: dict, setup_result: dict) -> dict:
        state = str(setup_result.get("state", ""))
        code = str(setup_result.get("code", ""))
        requested_scopes = self.store.oauth_requested_scopes(
            user_id, connector["id"], state
        )
        if not state or not code or not self.store.consume_oauth_state(user_id, connector["id"], state):
            raise ConnectorError("OAuth state is invalid, expired, owned by another user, or already used")
        auth = connector["auth"]
        try:
            token = self.transport(
                "POST",
                auth["token_url"],
                {},
                {
                    "code": code,
                    "client_id": self.env[auth["client_id_env"]],
                    "client_secret": self.env[auth["client_secret_env"]],
                    "redirect_uri": self._redirect_uri(connector),
                    "grant_type": "authorization_code",
                },
                30,
            )
        except Exception as exc:
            raise ConnectorError("OAuth token exchange failed") from exc
        if not token.get("access_token"):
            raise ConnectorError("OAuth token exchange returned no access token")
        try:
            existing = self.store.connection_credentials(user_id, connector["id"]) or {}
        except RuntimeError:
            existing = {}
        credentials = {
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token") or existing.get("refresh_token"),
            "expires_at": int(time.time()) + int(token.get("expires_in", 3600)),
            "scope": token.get("scope") or " ".join(requested_scopes),
            "token_type": token.get("token_type", "Bearer"),
        }
        self.store.save_connection(user_id, connector["id"], "pending_verification", credentials)
        try:
            self.verify_connection(user_id, connector["id"])
        except ConnectorError:
            self.store.save_connection(user_id, connector["id"], "needs_attention")
            raise
        return {"connector_id": connector["id"], "status": "verified"}

    def _finish_api_key(self, user_id: int, connector: dict, setup_result: dict) -> dict:
        fields = connector["auth"]["fields"]
        credentials = {}
        for field in fields:
            value = str(setup_result.get(field["name"], "")).strip()
            if field.get("required") and not value:
                raise ConnectorError(f"{field['label']} is required")
            if value:
                credentials[field["name"]] = value
        self.store.save_connection(user_id, connector["id"], "pending_verification", credentials)
        try:
            self.verify_connection(user_id, connector["id"])
        except ConnectorError:
            self.store.save_connection(user_id, connector["id"], "needs_attention", {})
            raise
        return {"connector_id": connector["id"], "status": "verified"}

    def verify_connection(self, user_id: int, connector_id: str) -> dict:
        connector = self._connector(connector_id)
        operation_id = connector["auth"].get("verify_operation") or next(iter(connector["operations"]))
        operation = connector["operations"][operation_id]
        try:
            result = self._execute(user_id, connector, operation)
            if not isinstance(result.get(operation["result_key"]), list):
                raise ConnectorError("provider result does not match the declared operation")
        except Exception as exc:
            raise ConnectorError("connector verification failed") from exc
        self.store.save_connection(user_id, connector["id"], "verified")
        return {"connector_id": connector["id"], "status": "verified"}

    def call_operation(
        self, user_id: int, connector_id: str, operation_id: str, inputs: dict | None = None
    ) -> dict:
        connector = self._connector(connector_id)
        if self.store.connection_status(user_id, connector["id"]) != "verified":
            raise ConnectorError("connector is not verified")
        operation = connector["operations"].get(operation_id)
        if not operation:
            raise ConnectorError(f"operation is not declared: {operation_id}")
        result = self._execute(user_id, connector, operation)
        items = result.get(operation["result_key"])
        if not isinstance(items, list):
            raise ConnectorError("provider result does not match the declared operation")
        mapping = operation["artifact"]
        rows = [[item.get(field, "") for field in mapping["fields"]] for item in items]
        return {
            "type": mapping["type"],
            "title": mapping["title"],
            "columns": mapping["columns"],
            "rows": rows,
            "source": connector["id"],
            "operation_id": operation_id,
        }

    def select_value(self, user_id: int, connector_id: str, value: str) -> dict:
        connector = self._connector(connector_id)
        selector = connector.get("selector")
        value = str(value).strip()
        if self.store.connection_status(user_id, connector["id"]) != "verified":
            raise ConnectorError("connector is not verified")
        if not selector or not value:
            raise ConnectorError("connector selection is not supported")
        operation = connector["operations"][selector["operation"]]
        result = self._execute(user_id, connector, operation)
        items = result.get(operation["result_key"])
        if not isinstance(items, list) or value not in {
            str(item.get(selector["value_field"], "")) for item in items
        }:
            raise ConnectorError("selected value is not available from the provider")
        if not self._selector_value_allowed(selector, value):
            raise ConnectorError("selected value is not compatible with this Cordia role")
        self.store.save_connection_setting(
            user_id, connector["id"], selector["setting"], value
        )
        if selector.get("runtime_role"):
            self.store.save_connection_setting(
                user_id, "__runtime__", selector["runtime_role"], connector["id"]
            )
        return {
            "connector_id": connector["id"],
            "setting": selector["setting"],
            "value": value,
        }

    def decorate_artifact(self, user_id: int, artifact: dict) -> dict:
        connector = resolve_connector(str(artifact.get("source", "")))
        if not connector:
            return artifact
        decorated = {
            **artifact,
            "connector_name": connector["name"],
            "live_view": self.live_view_access(user_id, connector["id"]),
        }
        if not connector.get("selector"):
            return decorated
        selector = connector["selector"]
        operation_id = artifact.get("operation_id")
        if not operation_id and len(connector["operations"]) == 1:
            operation_id = next(iter(connector["operations"]))
        if operation_id != selector["operation"]:
            return decorated
        fields = connector["operations"][operation_id]["artifact"]["fields"]
        value_column = fields.index(selector["value_field"])
        allowed_values = [
            str(row[value_column])
            for row in artifact.get("rows", [])
            if len(row) > value_column
            and self._selector_value_allowed(selector, str(row[value_column]))
        ]
        return {
            **decorated,
            "active_value": self.store.connection_setting(
                user_id, connector["id"], selector["setting"]
            ),
            "row_action": {
                "endpoint": "/api/connectors/select",
                "label": selector["label"],
                "value_column": value_column,
                "allowed_values": allowed_values,
            },
            "surface": (
                "workspace_settings"
                if selector.get("runtime_role") == "agent_model"
                else "workspace"
            ),
        }

    def agent_provider(self, user_id: int) -> dict | None:
        selection = self._agent_selection(user_id)
        if not selection:
            return None
        connector, selector, model = selection
        credentials = self.store.connection_credentials(user_id, connector["id"])
        credential = (credentials or {}).get(selector["credential_field"])
        if credential:
            return {"credential": credential, "model": model}
        return None

    def agent_runtime(self, user_id: int) -> dict | None:
        selection = self._agent_selection(user_id)
        if not selection:
            return None
        connector, _selector, model = selection
        return {"provider": connector["name"], "model": model, "source": "connector"}

    def _agent_selection(self, user_id: int) -> tuple[dict, dict, str] | None:
        active_connector_id = self.store.connection_setting(
            user_id, "__runtime__", "agent_model"
        )
        connectors = (
            [CONNECTORS[active_connector_id]]
            if active_connector_id in CONNECTORS
            else CONNECTORS.values()
        )
        for connector in connectors:
            selector = connector.get("selector")
            if not selector or selector.get("runtime_role") != "agent_model":
                continue
            if self.store.connection_status(user_id, connector["id"]) != "verified":
                continue
            model = self.store.connection_setting(
                user_id, connector["id"], selector["setting"]
            )
            if model:
                return connector, selector, model
        return None

    @staticmethod
    def _selector_value_allowed(selector: dict, value: str) -> bool:
        return not any(
            re.search(pattern, value, re.IGNORECASE)
            for pattern in selector.get("exclude_value_patterns", [])
        )

    def _execute(self, user_id: int, connector: dict, operation: dict) -> dict:
        credentials = self._fresh_credentials(user_id, connector)
        query = urllib.parse.urlencode(operation.get("query", {}))
        url = operation["url"] + (("?" + query) if query else "")
        try:
            return self.transport(
                operation["method"],
                url,
                self._authorization_headers(connector, credentials),
                None,
                30,
            )
        except Exception as exc:
            raise ConnectorError("provider operation failed") from exc

    def _fresh_credentials(self, user_id: int, connector: dict) -> dict:
        credentials = self.store.connection_credentials(user_id, connector["id"])
        if not credentials:
            raise ConnectorError("connector credentials are missing")
        if connector["auth"]["kind"] == "api_key":
            return credentials
        if not credentials.get("access_token"):
            raise ConnectorError("connector credentials are missing")
        if "expires_at" not in credentials:
            return credentials
        expires_at = int(credentials["expires_at"])
        if expires_at > int(time.time()) + 30:
            return credentials
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            self.store.save_connection(user_id, connector["id"], "needs_attention")
            raise ConnectorError("connector authorization expired; reconnect required")
        auth = connector["auth"]
        required = [auth["client_id_env"], auth["client_secret_env"]]
        if any(not self.env.get(name) for name in required):
            raise ConnectorError("OAuth server configuration is missing")
        try:
            token = self.transport(
                "POST",
                auth["token_url"],
                {},
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.env[auth["client_id_env"]],
                    "client_secret": self.env[auth["client_secret_env"]],
                },
                30,
            )
        except Exception as exc:
            self.store.save_connection(user_id, connector["id"], "needs_attention")
            raise ConnectorError("OAuth token refresh failed") from exc
        if not token.get("access_token"):
            self.store.save_connection(user_id, connector["id"], "needs_attention")
            raise ConnectorError("OAuth token refresh returned no access token")
        refreshed = {
            **credentials,
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token") or refresh_token,
            "expires_at": int(time.time()) + int(token.get("expires_in", 3600)),
            "scope": token.get("scope") or credentials.get("scope", ""),
            "token_type": token.get("token_type") or credentials.get("token_type", "Bearer"),
        }
        self.store.save_connection(user_id, connector["id"], "verified", refreshed)
        return refreshed

    @staticmethod
    def _authorization_headers(connector: dict, credentials: dict) -> dict:
        auth = connector["auth"]
        if auth["kind"] == "oauth2":
            return {"Authorization": f"Bearer {credentials['access_token']}"}
        if auth["kind"] == "api_key":
            try:
                value = auth["header"]["template"].format(**credentials)
            except KeyError as exc:
                raise ConnectorError("connector credentials are incomplete") from exc
            return {auth["header"]["name"]: value}
        raise ConnectorError(f"auth protocol is not implemented: {auth['kind']}")
