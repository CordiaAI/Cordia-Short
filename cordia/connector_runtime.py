from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from .connectors import resolve_connector


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

    def start_connection(self, user_id: int, connector_id: str) -> dict:
        connector = self._connector(connector_id)
        auth = connector["auth"]
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
        state = self.store.create_oauth_state(user_id, connector["id"])
        query = urllib.parse.urlencode(
            {
                "client_id": self.env[auth["client_id_env"]],
                "redirect_uri": self._redirect_uri(connector),
                "response_type": "code",
                "scope": auth["scope"],
                "access_type": "offline",
                "include_granted_scopes": "true",
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

    def finish_connection(self, user_id: int, connector_id: str, setup_result: dict) -> dict:
        connector = self._connector(connector_id)
        state = str(setup_result.get("state", ""))
        code = str(setup_result.get("code", ""))
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
        credentials = {
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "expires_at": int(time.time()) + int(token.get("expires_in", 3600)),
            "scope": token.get("scope", ""),
            "token_type": token.get("token_type", "Bearer"),
        }
        self.store.save_connection(user_id, connector["id"], "pending_verification", credentials)
        try:
            self.verify_connection(user_id, connector["id"])
        except ConnectorError:
            self.store.save_connection(user_id, connector["id"], "needs_attention")
            raise
        return {"connector_id": connector["id"], "status": "verified"}

    def verify_connection(self, user_id: int, connector_id: str) -> dict:
        connector = self._connector(connector_id)
        operation_id = next(iter(connector["operations"]))
        try:
            self._execute(user_id, connector, connector["operations"][operation_id])
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
        }

    def _execute(self, user_id: int, connector: dict, operation: dict) -> dict:
        credentials = self._fresh_credentials(user_id, connector)
        query = urllib.parse.urlencode(operation.get("query", {}))
        url = operation["url"] + (("?" + query) if query else "")
        try:
            return self.transport(
                operation["method"],
                url,
                {"Authorization": f"Bearer {credentials['access_token']}"},
                None,
                30,
            )
        except Exception as exc:
            raise ConnectorError("provider operation failed") from exc

    def _fresh_credentials(self, user_id: int, connector: dict) -> dict:
        credentials = self.store.connection_credentials(user_id, connector["id"])
        if not credentials or not credentials.get("access_token"):
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
