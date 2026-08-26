import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceUIContractTests(unittest.TestCase):
    def test_one_page_contains_auth_chat_setup_and_artifact_surfaces(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="auth-panel"', html)
        self.assertIn('id="chat-panel"', html)
        self.assertIn('id="setup-card"', html)
        self.assertIn('id="artifact-grid"', html)
        self.assertNotIn("iframe", html.lower())

    def test_javascript_uses_generic_setup_and_artifact_renderers(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function renderSetupCard", javascript)
        self.assertIn("function renderArtifact", javascript)
        self.assertIn("state.setup_card", javascript)
        self.assertIn("/api/survey", javascript)
        self.assertIn("/api/chat", javascript)
        self.assertIn("credential_form", javascript)
        self.assertIn("/api/connectors/setup", javascript)
        self.assertIn('type="${escapeHtml(field.type)}"', javascript)

    def test_visual_tokens_match_cordia_identity(self):
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--ivory", css)
        self.assertIn("--sage", css)
        self.assertIn("--olive", css)


if __name__ == "__main__":
    unittest.main()
