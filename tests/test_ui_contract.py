import unittest
import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceUIContractTests(unittest.TestCase):
    def test_signed_out_page_is_a_public_product_landing_surface(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="landing"', html)
        self.assertIn('id="cordia-message"', html)
        self.assertIn('id="products"', html)
        # Sign-in and sign-up open the auth panel in a new tab so the landing page stays put.
        self.assertIn('href="/?auth=signin"', html)
        self.assertIn('href="/?auth=register"', html)
        self.assertIn('href="https://classroom.cordiaai.io"', html)
        self.assertNotIn('classroom.cordiacode.com', html)
        self.assertNotIn('/dashboard/', html)  # the old Hostinger dashboard is retired
        self.assertIn('data-auth-close', html)
        self.assertIn('/static/landing.js', html)

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
        self.assertIn("function compactAssistantMessage", javascript)
        self.assertIn("state.setup_card", javascript)
        self.assertIn("/api/chat", javascript)
        self.assertIn("credential_form", javascript)
        self.assertIn("card.details || []", javascript)
        self.assertIn("card.confirm_label", javascript)
        self.assertIn("isOpaqueIdentifier", javascript)
        self.assertIn("application?.actions || []", javascript)
        self.assertIn("connectorShells", javascript)
        self.assertIn("data-action-id", javascript)
        self.assertIn("action_starter", javascript)
        self.assertNotIn("adjustmentControls", javascript)
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
        for token in ("--ivory: #fbfaf5", "--sage: #4a5a42", "--ink: #0b0b0b",
                      "--sand: #f4f2ea", '"Newsreader"', '"Work Sans"'):
            self.assertIn(token, css)

    def test_shared_brand_assets_and_accessible_composer_are_present(self):
        # Markup/assets guard only; native interaction and layout need browser QA.
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('for="message-input">Message Cordia</label>', html)
        self.assertIn('aria-describedby="composer-help"', html)
        self.assertIn('data-voice-target="message-input"', html)
        self.assertIn('id="auth-title"', html)
        self.assertIn('aria-label="Account access"', html)
        self.assertIn('autocomplete="new-password"', html)
        for asset in ("cordia-logo-header.webp", "login-bg.jpg"):
            path = ROOT / "static" / "assets" / asset
            self.assertTrue(path.is_file(), f"Missing branding asset: {asset}")
            self.assertGreater(path.stat().st_size, 0)

    def test_onboarding_layer_and_script_are_present(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="onboarding"', html)
        self.assertIn('/static/onboarding.js', html)
        layer = html.split('id="onboarding"', 1)[1].split('<section id="auth-panel"', 1)[0]
        self.assertIn('aria-labelledby="onboarding-title"', layer)
        self.assertIn('id="onboarding-title" tabindex="-1"', layer)
        self.assertIn('id="onboarding-progress"', layer)
        self.assertIn('aria-live="assertive"', layer)
        self.assertIn('id="onboarding-back"', layer)
        self.assertIn('id="onboarding-continue"', layer)
        self.assertNotIn('type="password"', layer)
        self.assertIn('/static/assets/cordia-logo-header.webp', layer)

    def test_onboarding_controller_uses_stage_and_completion_endpoints(self):
        path = ROOT / "static" / "onboarding.js"
        self.assertTrue(path.exists(), "onboarding controller is missing")
        script = path.read_text(encoding="utf-8")
        self.assertIn('PUT', script)
        self.assertIn('/api/onboarding/', script)
        self.assertIn('/api/onboarding/complete', script)
        self.assertNotIn('localStorage', script)

    def test_chat_composer_no_longer_posts_survey_answers(self):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('"/api/survey"', script)
        self.assertNotIn('Answer Surveyor', script)

    def test_onboarding_controller_behavior(self):
        result = subprocess.run(
            ["node", "--test", "tests/onboarding.test.cjs", "tests/setup.test.cjs"],
            cwd=ROOT, text=True, capture_output=True,
            env={**os.environ, "CORDIA_TEST_PYTHON": sys.executable},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_workspace_shell_matches_the_approved_navigation_contract(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="back-to-cordia"', html)
        self.assertIn('id="account-menu-button"', html)
        self.assertIn('id="account-menu"', html)
        self.assertIn('id="workspace-settings"', html)
        self.assertNotIn('id="signout-button"', html)
        self.assertNotIn('id="workspace-subtitle"', html)
        self.assertNotIn('class="view-pill"', html)
        self.assertNotIn('class="assistant-mark">C</span>', html)

    def test_workspace_is_a_compact_artifact_dashboard_not_a_setup_summary(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn('id="selected-applications"', html)
        self.assertNotIn('class="memory-card"', html)
        self.assertNotIn('id="live-view-permission"', html)
        self.assertIn("connector-logo", javascript)
        self.assertIn("data-artifact-prompt", javascript)
        self.assertIn("data-artifact-refresh", javascript)
        self.assertIn("artifact_id", javascript)
        self.assertIn("aspect-ratio: 1 / 1", css)
        self.assertIn("auto-fill", css)
        self.assertIn("renderWorkspaceSettings", javascript)
        self.assertNotIn("iframe", (html + javascript).lower())

    def test_model_catalog_stays_in_settings_and_voice_is_progressive(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        onboarding = (ROOT / "static" / "onboarding.js").read_text(encoding="utf-8")

        self.assertIn(
            'artifact.surface !== "workspace_settings"', javascript
        )
        self.assertIn("window.CordiaVoice", onboarding)
        self.assertIn("webkitSpeechRecognition", onboarding)
        self.assertIn("Voice input is unavailable", onboarding)


if __name__ == "__main__":
    unittest.main()
