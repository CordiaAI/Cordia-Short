from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from .connectors import public_application, resolve_application


class ConnectorError(RuntimeError):
    pass


def _http_transport(
    method: str, url: str, headers: dict, data: dict | None, timeout: int
) -> dict:
    request_headers = {"Accept": "application/json", **headers}
    body = None
    if method == "GET" and data:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(data)
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise OSError(f"provider returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OSError("provider response unavailable") from exc


class ConnectorRuntime:
    """Cordia's provider-neutral boundary around an external connector catalog."""

    API_BASE = "https://api.pipedream.com/v1"
    MCP_ENDPOINT = "https://remote.mcp.pipedream.net/v3"
    REQUIRED_CONFIGURATION = (
        "PIPEDREAM_CLIENT_ID",
        "PIPEDREAM_CLIENT_SECRET",
        "PIPEDREAM_PROJECT_ID",
    )

    def __init__(
        self,
        store,
        env: Mapping[str, str] | None = None,
        transport: Callable[[str, str, dict, dict | None, int], dict] | None = None,
    ):
        self.store = store
        self.env = os.environ if env is None else env
        self.transport = transport or _http_transport
        self._token: str | None = None
        self._token_expires_at = 0.0

    def missing_configuration(self) -> list[str]:
        return [name for name in self.REQUIRED_CONFIGURATION if not self.env.get(name)]

    def catalog_state(self, query: str = "", limit: int = 100) -> dict:
        missing = self.missing_configuration()
        if missing:
            return {
                "status": "needs_configuration",
                "applications": [],
                "message": "Universal connector catalog is unavailable until Cordia finishes server configuration.",
            }
        return {"status": "ready", "applications": self.search_applications(query, limit)}

    def _developer_token(self) -> str:
        if self._token and self._token_expires_at > time.time() + 30:
            return self._token
        missing = self.missing_configuration()
        if missing:
            raise ConnectorError("connector provider is not configured")
        try:
            response = self.transport(
                "POST",
                f"{self.API_BASE}/oauth/token",
                {},
                {
                    "grant_type": "client_credentials",
                    "client_id": self.env["PIPEDREAM_CLIENT_ID"],
                    "client_secret": self.env["PIPEDREAM_CLIENT_SECRET"],
                    "scope": self.env.get(
                        "PIPEDREAM_OAUTH_SCOPE",
                        "connect:apps:* connect:accounts:read connect:accounts:write connect:actions:* connect:tokens:create",
                    ),
                },
                30,
            )
        except Exception as exc:
            raise ConnectorError("connector provider authentication failed") from exc
        token = str(response.get("access_token") or "")
        if not token:
            raise ConnectorError("connector provider returned no access token")
        self._token = token
        self._token_expires_at = time.time() + int(response.get("expires_in") or 3600)
        return token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._developer_token()}",
            "x-pd-environment": self.env.get("PIPEDREAM_ENVIRONMENT", "development"),
        }

    @staticmethod
    def external_user_id(user_id: int) -> str:
        return f"cordia:{int(user_id)}"

    @staticmethod
    def _items(response: dict, *keys: str) -> list[dict]:
        value = response
        for key in keys:
            if not isinstance(value, dict):
                return []
            value = value.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def search_applications(self, query: str = "", limit: int = 100) -> list[dict]:
        params = {"limit": max(1, min(int(limit), 100))}
        if str(query).strip():
            params["q"] = str(query).strip()
        try:
            response = self.transport(
                "GET", f"{self.API_BASE}/connect/apps", self._headers(), params, 30
            )
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError("connector catalog unavailable") from exc
        records = self._items(response, "data") or self._items(response, "apps")
        applications = []
        for record in records:
            try:
                applications.append(public_application(record))
            except ValueError:
                continue
        return applications

    def application(self, value: str) -> dict:
        application = resolve_application(value, self.search_applications(value, 20))
        if not application:
            raise ConnectorError(f"application was not found in the provider catalog: {value}")
        return application

    def _callback_uri(self, state: str) -> str:
        base = self.env.get("CORDIA_BASE_URL", "http://127.0.0.1:5050").rstrip("/")
        return base + "/api/connectors/oauth/callback?" + urllib.parse.urlencode({"state": state})

    def _provider_account(self, user_id: int, connector_id: str) -> dict | None:
        try:
            response = self.transport(
                "GET",
                f"{self.API_BASE}/connect/{self.env['PIPEDREAM_PROJECT_ID']}/accounts",
                self._headers(),
                {"external_user_id": self.external_user_id(user_id), "app": connector_id},
                30,
            )
        except Exception as exc:
            raise ConnectorError("connector verification failed") from exc
        accounts = self._items(response, "data") or self._items(response, "accounts")
        return next(
            (
                item
                for item in accounts
                if not item.get("dead")
                and item.get("healthy") is not False
                and str((item.get("app") or {}).get("name_slug") or item.get("app") or connector_id)
                == connector_id
                and item.get("id")
            ),
            None,
        )

    def _save_provider_account(self, user_id: int, connector_id: str, account: dict) -> None:
        self.store.save_connection(
            user_id,
            connector_id,
            "verified",
            {"account_id": str(account["id"])},
        )

    def start_connection(
        self, user_id: int, connector_id: str, requested_scopes: list[str] | None = None
    ) -> dict:
        del requested_scopes
        missing = self.missing_configuration()
        if missing:
            return {
                "type": "connector_setup",
                "connector_id": str(connector_id),
                "title": "Connect application",
                "status": "needs_configuration",
                "message": "Connections are unavailable until Cordia finishes server configuration.",
            }
        application = self.application(connector_id)
        account = self._provider_account(user_id, application["id"])
        if account:
            self._save_provider_account(user_id, application["id"], account)
            return {
                "type": "connector_status",
                "connector_id": application["id"],
                "title": f"{application['name']} connected",
                "status": "verified",
                "message": "This application is already connected.",
            }
        state = self.store.create_oauth_state(user_id, application["id"])
        payload = {
            "external_user_id": self.external_user_id(user_id),
            "scope": "connect:apps:* connect:accounts:read connect:accounts:write connect:actions:*",
            "success_redirect_uri": self._callback_uri(state),
            "error_redirect_uri": self._callback_uri(state) + "&error=authorization_denied",
        }
        try:
            response = self.transport(
                "POST",
                f"{self.API_BASE}/connect/{self.env['PIPEDREAM_PROJECT_ID']}/tokens",
                self._headers(),
                payload,
                30,
            )
        except Exception as exc:
            raise ConnectorError("connector authorization could not be prepared") from exc
        action_url = str(response.get("connect_link_url") or response.get("url") or "")
        if not action_url:
            raise ConnectorError("connector provider returned no authorization link")
        separator = "&" if "?" in action_url else "?"
        return {
            "type": "oauth_redirect",
            "connector_id": application["id"],
            "title": f"Connect {application['name']}",
            "status": "ready",
            "message": "Continue to the provider to authorize this application.",
            "action_url": action_url + separator + urllib.parse.urlencode({"app": application["id"]}),
            "state": state,
        }

    def finish_connection(self, user_id: int, connector_id: str, setup_result: dict) -> dict:
        state = str(setup_result.get("state") or "")
        if not state or not self.store.consume_oauth_state(user_id, connector_id, state):
            raise ConnectorError("authorization state is invalid, expired, owned by another user, or already used")
        try:
            account = self._provider_account(user_id, connector_id)
        except ConnectorError:
            self.store.save_connection(user_id, connector_id, "needs_attention")
            raise
        if not account:
            self.store.save_connection(user_id, connector_id, "needs_attention")
            raise ConnectorError("connector verification failed")
        self._save_provider_account(user_id, connector_id, account)
        return {"connector_id": connector_id, "status": "verified"}

    def connection_status(self, user_id: int, connector_id: str) -> dict:
        application = self.application(connector_id)
        status = self.store.connection_status(user_id, application["id"]) or "not_connected"
        if status != "verified" and not self.missing_configuration():
            try:
                account = self._provider_account(user_id, application["id"])
            except ConnectorError:
                account = None
            if account:
                self._save_provider_account(user_id, application["id"], account)
                status = "verified"
        return {
            "connector_id": application["id"],
            "name": application["name"],
            "status": status,
        }

    def mcp_configuration(self, user_id: int, connector_id: str) -> dict:
        application = self.application(connector_id)
        if self.store.connection_status(user_id, application["id"]) != "verified":
            raise ConnectorError("application is not connected")
        return {
            "endpoint": self.MCP_ENDPOINT,
            "headers": {
                "Authorization": f"Bearer {self._developer_token()}",
                "x-pd-project-id": self.env["PIPEDREAM_PROJECT_ID"],
                "x-pd-environment": self.env.get("PIPEDREAM_ENVIRONMENT", "development"),
                "x-pd-external-user-id": self.external_user_id(user_id),
                "x-pd-app-slug": application["id"],
            },
            "application": application,
        }

    def decorate_artifact(self, user_id: int, artifact: dict) -> dict:
        del user_id
        return artifact

    def agent_provider(self, user_id: int) -> None:
        del user_id
        return None

    def agent_runtime(self, user_id: int) -> None:
        del user_id
        return None
