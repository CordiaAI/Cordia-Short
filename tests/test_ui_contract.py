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
        self.assertIn("/api/connectors/select", javascript)
        self.assertIn("data-model-select", javascript)
        self.assertIn('type="${escapeHtml(field.type)}"', javascript)

    def test_chat_renders_pending_work_and_enter_submits(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function renderPendingMessage", javascript)
        self.assertIn('class="cordia-working"', javascript)
        self.assertIn("composer.requestSubmit()", javascript)
        self.assertIn("event.shiftKey", javascript)
        self.assertIn("event.isComposing", javascript)
        self.assertIn("@keyframes cordia-shine", css)

    def test_visual_tokens_match_cordia_identity(self):
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--ivory", css)
        self.assertIn("--sage", css)
        self.assertIn("--olive", css)

    def test_workspace_shell_matches_the_approved_navigation_contract(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="back-to-cordia"', html)
        self.assertIn('id="account-menu-button"', html)
        self.assertIn('id="account-menu"', html)
        self.assertIn('id="workspace-settings"', html)
        self.assertNotIn('id="signout-button"', html)
        self.assertNotIn('id="workspace-subtitle"', html)
        self.assertNotIn('class="view-pill"', html)
        self.assertNotIn('class="assistant-mark">C</span>', html)

    def test_live_view_uses_provider_logo_permission_dialog_and_no_iframe(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="live-view-permission"', html)
        self.assertIn("data-live-view", javascript)
        self.assertIn("connector-logo", javascript)
        self.assertIn("/api/connectors/live-view", javascript)
        self.assertIn('sessionStorage.setItem("cordia-live-view-return"', javascript)
        self.assertIn("renderWorkspaceSettings", javascript)
        self.assertNotIn("iframe", (html + javascript).lower())

    def test_model_catalog_stays_in_settings_and_live_view_never_claims_false_success(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn(
            'artifact.surface !== "workspace_settings"', javascript
        )
        self.assertIn("if (state.setup_card)", javascript)
        self.assertIn("if (!state.artifact) throw new Error", javascript)
        self.assertIn("activateLiveView(resumeLiveView).catch", javascript)


if __name__ == "__main__":
    unittest.main()
