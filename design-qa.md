# Cordia Short LiveView Design QA

- Source visual truth: `C:\Users\jacks\AppData\Local\Temp\codex-clipboard-5cfb8b55-3bee-4385-b769-8362ffd7abdb.png`
- Browser: Chrome DevTools MCP, isolated local QA context
- Viewport: 1600 x 900 CSS pixels
- State: signed-in user, Surveyor complete, one Google Drive artifact, LiveView permission accepted

## Visual comparison

The annotated source and the implementation were inspected together at the same desktop state.

- Cordia brand and `My Workspace` remain in the top bar.
- The requested disabled `Back to Cordia` control occupies the highlighted top-bar position.
- Standalone Sign out is replaced by the CordiaCode account avatar and matching seven-item menu.
- The assistant avatar, workspace eyebrow, workspace subtitle, and DashView pill are removed.
- Duplicate connector/model windows are absent from the canvas.
- The remaining connector window uses the official Google Drive logo and a Live View control.
- Selected model configuration is kept in Workspace settings rather than the artifact canvas.

## Functional browser evidence

- Created an isolated local QA account and completed all five Surveyor prompts.
- Confirmed Enter submits the focused composer.
- Created a Google Drive artifact through the real Cordia app route using a deterministic QA connector transport.
- Opened the production-style LiveView permission dialog and accepted it.
- Confirmed the same artifact window refreshed and entered `Live View on` state without creating a duplicate.
- Opened the profile menu and verified: Your profile, Certification, Assessment, Billing, Workspace, Feedback, Sign out.
- Opened Workspace settings and verified the model configuration surface is separated from the artifact canvas.
- Injected an unselected model artifact and verified its explicit `workspace_settings` surface kept it off the canvas while remaining available in Workspace settings.
- Exercised a non-redirect connector setup response and verified LiveView stayed off, the setup card remained visible, and the real configuration message was shown.
- Refreshed granted LiveView data and verified the existing Google Drive window was updated in place (`windows: 1`) and changed to `Live View on`.
- Browser console after the final LiveView flow: no messages.
- Lighthouse snapshot: Accessibility 100, Best Practices 100, SEO 100, Agentic Browsing 100.

## Permission boundary

- Google Drive LiveView is Cordia-rendered provider data, not an embedded Google page.
- The initial contract is read-only metadata access using the already declared Google OAuth scope.
- If a connector lacks required scopes, the backend returns only the missing declared scopes and begins incremental provider authorization.
- The permission dialog states the data used, actions allowed, and revocation path before activation.

final result: pass
