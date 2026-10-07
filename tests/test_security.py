import tempfile
import unittest
from pathlib import Path

from app import MAX_REQUEST_BYTES, RATE_LIMITS, create_app
from cordia.agent import Agent
from tests.agent_helpers import ScriptedModel
from tests.test_app import FakeRuntime, FakeWorkspace


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        runtime = FakeRuntime()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": root / "cordia.db",
                "WORKSPACE_ROOT": root / "workspaces",
                "SESSION_COOKIE_SECURE": True,
                "COMING_SOON_AFTER_SURVEY": True,
            },
            agent=Agent("fixture-key", "fixture-model", chat_model=ScriptedModel(replies=[])),
            connector_runtime=runtime,
            workspace_client=FakeWorkspace(runtime),
        )
        runtime.store = self.app.extensions["cordia_store"]
        self.client = self.app.test_client()

    def test_every_response_carries_browser_security_headers(self):
        for path in ("/", "/api/state", "/static/app.js"):
            response = self.client.get(path)
            self.assertEqual("DENY", response.headers["X-Frame-Options"], path)
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
            self.assertIn("max-age=", response.headers["Strict-Transport-Security"])
            response.close()
        self.assertEqual("no-store", self.client.get("/api/state").headers["Cache-Control"])

    def test_session_cookie_is_secure_httponly_and_lax(self):
        response = self.client.post(
            "/api/register", json={"email": "person@example.com", "password": "correct horse battery"}
        )
        cookie = response.headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(attribute, cookie)

    def test_repeated_signin_failures_for_one_email_are_throttled(self):
        limit = RATE_LIMITS["signin_email"][0]
        for _ in range(limit):
            response = self.client.post(
                "/api/signin", json={"email": "victim@example.com", "password": "wrong password guess"}
            )
            self.assertEqual(401, response.status_code)
        blocked = self.client.post(
            "/api/signin", json={"email": "Victim@Example.com", "password": "wrong password guess"}
        )
        self.assertEqual(429, blocked.status_code)

    def test_registration_is_throttled_per_client(self):
        limit = RATE_LIMITS["register_ip"][0]
        for index in range(limit):
            self.client.post(
                "/api/register", json={"email": f"user{index}@example.com", "password": "correct horse battery"}
            )
        blocked = self.client.post(
            "/api/register", json={"email": "another@example.com", "password": "correct horse battery"}
        )
        self.assertEqual(429, blocked.status_code)

    def test_forged_forwarding_header_does_not_reset_limits_off_vercel(self):
        limit = RATE_LIMITS["register_ip"][0]
        for index in range(limit + 1):
            response = self.client.post(
                "/api/register",
                json={"email": f"spoof{index}@example.com", "password": "correct horse battery"},
                headers={"X-Real-IP": f"203.0.113.{index}"},
            )
        self.assertEqual(429, response.status_code)

    def test_oversized_and_malformed_auth_input_is_rejected_cleanly(self):
        too_large = self.client.post(
            "/api/signin",
            data=b"{" + b" " * MAX_REQUEST_BYTES + b"}",
            content_type="application/json",
        )
        self.assertEqual(413, too_large.status_code)

        long_password = self.client.post(
            "/api/register", json={"email": "long@example.com", "password": "x" * 257}
        )
        self.assertEqual(400, long_password.status_code)

        wrong_types = self.client.post("/api/register", json={"email": ["a@b.c"], "password": 123})
        self.assertEqual(400, wrong_types.status_code)

    def test_store_rate_limit_window_resets(self):
        store = self.app.extensions["cordia_store"]
        self.assertFalse(store.rate_limited("bucket", 1, 60))
        self.assertTrue(store.rate_limited("bucket", 1, 60))
        self.assertFalse(store.rate_limited("bucket", 1, 0))


if __name__ == "__main__":
    unittest.main()
