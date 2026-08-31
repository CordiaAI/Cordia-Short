import unittest

from cordia.agent import Agent, AgentUnavailable, redact_secrets


class AgentConfigurationTests(unittest.TestCase):
    def test_selected_model_uses_explicit_key_bounded_requests_without_fallback(self):
        model = Agent("fixture-key", "gpt-5-mini").chat_model()
        self.assertEqual("gpt-5-mini", model.model_name)
        self.assertEqual("fixture-key", model.openai_api_key.get_secret_value())
        self.assertEqual(0, model.max_retries)
        self.assertEqual(45, model.request_timeout)
        self.assertEqual(1600, model.max_tokens)
        self.assertFalse(model.store)

    def test_missing_key_is_plainly_unavailable(self):
        with self.assertRaisesRegex(AgentUnavailable, "OPENAI_API_KEY"):
            Agent("").chat_model()

    def test_redacts_assignments_prefixes_and_oauth_links(self):
        source = "OPENAI_API_KEY=private token: ghp_123456789012345678901234567890123456 https://accounts.google.com/oauth?code=secret&state=private"
        result = redact_secrets(source)
        for secret in ("private", "secret", "ghp_123456789012345678901234567890123456"):
            self.assertNotIn(secret, result)
        self.assertIn("[REDACTED]", result)
