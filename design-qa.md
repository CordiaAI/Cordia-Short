# Cordia Short Design QA

## Current Surveyor onboarding evidence — 2026-08-30

This section supersedes the historical LiveView result below for this branch. It records local evidence only: no merge or live deployment is claimed.

- Browser implementation checkpoint: `e6d96eb` (`feat: add Surveyor onboarding experience`). The controller performed the browser work separately from Task 6's service tests.
- Automated journey/feedback implementation: `f75ad8c` (`test: verify Surveyor FDE onboarding journey`), based on that browser checkpoint. Browser interaction evidence above does not claim a browser rerun of the feedback fix.
- Local service: `http://127.0.0.1:5058`, isolated synthetic account and SQLite/workspaces under `.superpowers/sdd/2026-08-28-surveyor-fde-discovery/browser-data/`. Real API, Store, compiler, and files; no configured model key.
- Source-content authority: the approved verbatim captured assessment manifest. The external reference currently resumes to a preexisting Profile Snapshot. No fresh capture or visual comparison of all four source parts is claimed, and the reference user's state was preserved.

### Current browser interactions

- A second synthetic account registration opened Part 1 directly, not Agent chat.
- Completed all 20 Part 1 ratings; refreshing after saving resumed Part 2.
- Selected Technology & software and Work / professional, supplied ratings and technology familiarity choices, completed Part 3, and supplied two Part 4 sample prompts.
- Profile Snapshot matched the submitted choices: context `+1`, scope `-1`, directness `+1`, implementation `-1`. Back to Part 4 and Continue both worked.
- Added catalog Google Drive and manually entered Workshop Tracker; captured each application's current/desired activities and other required fields.
- Low-risk automation, confidential information, and web-environment choices exposed 11 applicable optional discovery fields; all were filled and survived compilation.
- Workspace Review correctly showed Google Drive as **Setup required** and Workshop Tracker as **Planned**. Build opened the existing workspace with those same honest states and no fabricated artifacts.
- Inspected the three generated files for synthetic user 1: `operator.md` (1,596 bytes), `connectors.md` (923 bytes), and `fde.md` (2,293 bytes) at the browser checkpoint. Profile settings, sample prompts, application activities, and optional constraints were retained.
- Enter submitted and persisted a chat message. The unconfigured real Agent returned the explicit `OPENAI_API_KEY is not configured` error; this was not a successful model turn or connector proposal.
- All seven account-menu labels were present. Workspace opened **Connections & models**, and Close worked.
- Browser error logs were empty before the intentional unavailable-agent request. That chat request produced the expected HTTP 503; no blocking JavaScript error was observed in the reported flow.

### Responsive and visual boundaries

The desktop viewport request of 1280 pixels reported an effective `1422x1000` browser viewport, with no page horizontal overflow. The requested `375x812` viewport initially reported a width of 417 pixels because of browser zoom, so that observation is not 375-pixel proof. Screenshot capture repeatedly returned `Unable to capture screenshot`; no screenshot-based visual comparison, new Lighthouse score, or exact 375-pixel visual pass is claimed.

A subsequent narrow check used effective `374x812` (requested `337x731` at the existing 90% browser zoom). Part 1 had root width 374, onboarding width 358, no element-bounds overflow, and a working click selection. This was a Part 1 layout/interaction check, not a complete narrow-screen journey. Native-choice Enter/Space focused the choice without changing `aria-pressed` in automation; the cause is unresolved, so survey keyboard activation remains pending manual/browser QA. Chat Enter submission was separately observed. The viewport was reset afterward.

Cordia's ivory/sage presentation, progress shell, and separate Profile Snapshot/discovery/review are intentional brand and onboarding adaptations. Source question and option text is checked against the approved manifest; that content check does not establish pixel-level resemblance.

### Automated scope and release boundary

Task 6 automated verification: **145 Python tests passed in 51.629 seconds**, exit 0. The independent onboarding-controller run passed **15 Node tests**, exit 0 (also invoked by the Python UI test). Python compilation, both JavaScript syntax checks, and `git diff --check` exited 0. The deliberate disk-full API regression logged its expected `OSError: disk full` traceback while passing; Git emitted LF/CRLF warnings. The output is therefore not claimed to be warning-free.

Commands were run from `.worktrees/surveyor-fde-discovery`:

```powershell
& "../../.venv/Scripts/python.exe" -m unittest discover -s tests -v
& "../../.venv/Scripts/python.exe" -m py_compile app.py cordia/agent.py cordia/connectors.py cordia/connector_runtime.py cordia/onboarding.py cordia/store.py cordia/survey.py cordia/workspace_mcp.py
node --check static/app.js
node --check static/onboarding.js
node --test tests/onboarding.test.cjs
git diff --check
```

The new service journey uses the real register/stage-save/complete/chat routes, temporary SQLite Store, deterministic compiler, generated files, and real Agent request construction. Its model transport is a **test double**, and `RecordingWorkspaceClient` is a **workspace-MCP boundary double**. Assertions cover all three files reaching the model request, no model/MCP call during onboarding, a persistent later setup card, and no verified connection or stored credential produced by onboarding or proposal.

The legacy migration test preserves exact runtime database records, including encrypted credentials, artifacts, messages, active model selection, and explicit adjustments. Additional API regressions cover a survey setting stepping `-1 -> 0 -> 1`, clamping, original-request retries, and newest feedback winning even when it targets an older response. The existing real-MCP connector journey now enters onboarding through the real API; its provider transport remains deterministic, not live.

Remaining release checks: successful real-provider/model chat and connector proposal in the current browser build; pending infinity indicator; current artifact and Live View interactions backed by provider data; screenshot-based source comparison, exact 375-pixel full journey, and native survey keyboard activation; and final controller branch review/fresh verification. Merge and deployment are separate, unperformed steps.

## Historical LiveView QA — retained context, not current onboarding proof

The following record predates this onboarding change. Its five-question survey flow, screenshot comparison, Lighthouse scores, and pass label do not apply to the current branch.

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

Historical result: pass (not re-established for the current onboarding branch).
