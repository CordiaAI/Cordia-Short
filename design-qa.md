# Cordia Short Design QA

## Main-site visual alignment — 2026-08-31

Scope: frontend refinement against `https://cordiacode.com/`, on top of `b5917c9`. No survey questions, scoring, authorization, provider, database, or connector execution changes. This section supersedes earlier visual-check status only; it is not a new live-provider or release acceptance result.

### Source and comparison evidence

- Source visual truth: the current main-site sign-in screen, its real `login-bg.jpg` and logo, and `Cordia/web/assets/cordia-ui.css`. The copied background is a local static asset, not a runtime dependency on the main site.
- Local implementation: `http://localhost:5058/`; isolated synthetic-account data, not beta customer data.
- Saved captures: `.superpowers/sdd/2026-08-31-visual-alignment/source-signin.jpg` and `local-signin.jpg` (ignored local evidence). Both are 1265 x 712 pixels, captured at reported 1280 x 720 CSS viewports, emitted together in one comparison input at matching browser-provided screenshot scale. No additional density transformation was applied. `local-workspace.jpg` records the final empty workspace state.
- Full-view comparison: logo, botanical/data artwork, headline, centered sign-in card, fonts, neutral palette, rounded controls and shadows align. Form text is legible in the full capture, so an additional cropped comparison was unnecessary.
- Deliberate functional differences: no nonfunctional password-reset link or email-verification promise; beta keeps its existing registration behavior. The form footer is shorter and controls retain comfortable touch targets. The focused tab has a visible accessibility ring.

### Required fidelity surfaces

- Typography: Inter body/controls, Newsreader display headings, Work Sans small labels, with local fallbacks. The auth headline retains the main site's Inter weight and wrapping.
- Layout: shared 10/14/20px control/card/dialog radii, consistent spacing, narrower desktop chat, flexible artifact columns, collapsed saved-profile details. At mobile width the workspace stacks vertically and choices use one column.
- Colors: white, near-black, moss `#4a5a42`, wash `#f6f7f4`, and restrained borders/shadows from the source stylesheet. Existing semantic error/notice colors remain distinct.
- Assets: actual Cordia logo and main-site artwork replace the old text logo and unrelated sign-in treatment; aspect ratios are preserved.
- Content: original assessment questions and instructions are unchanged. Removed the empty artifact's misleading READY label; setup status displays spaces instead of internal underscores. No new capability claims.

### Iteration and interaction evidence

The initial comparison found the old cream/olive palette, text-logo approximation, different sign-in composition, and dense always-open operator text. Those were replaced or refined, then recaptured against the source. No substantive visual mismatch remains in the compared sign-in state beyond the deliberate functional differences above.

The independent focused code review found a P2 hover-contrast regression: the generic light hover background overrode the account avatar and active Live View button while retaining white text. Explicit dark hover styles now cover both. The account-avatar problem was reproduced through browser pointer hover before the fix and rechecked after reload; the active Live View selector was source-reviewed, not provider-interaction tested. No other scoped code regressions were reported.

Browser checks used existing synthetic accounts and real local routes: sign-in mode/pressed state/password autocomplete; sign-in and sign-out; all seven survey stages; saved answers and reload resume; application selection and required discovery fields; review-to-workspace transition; the seven-item account menu; Connections & models open/close; and saved-profile disclosure. Desktop screenshots cover survey/profile/workspace/dialog states. Effective 375px captures cover auth, Parts 1–3, profile, discovery and review; Part 4 was inspected at desktop width. Measured mobile profile/discovery/review/auth roots did not exceed the viewport. The mobile workspace and settings dialog also rendered without page overflow. No new console error was observed in the checked workspace session.

Fresh automated verification after the hover fix: **154 Python tests passed in 52.935 seconds**, including the 20-test Node onboarding-controller suite. `node --check static/app.js` and `git diff --check` passed. The intentionally injected disk-full test logged its expected traceback. The new markup/assets guard is not browser or provider proof.

### Remaining acceptance limits

- Native Enter activation is not confirmed: automation focused both a survey choice and the unrelated account-menu button, but did not activate either; pointer activation worked. Source inspection found ordinary native buttons with click handlers, without a shared Enter-prevention handler. Cause remains unconfirmed; no compensating keyboard handler was added.
- Authenticated main-site pages were not accessible for a page-by-page source comparison. Their shared design tokens are reused; pixel identity for those pages is not claimed.
- This isolated account has no verified Google credentials. Populated provider artifacts, the OAuth flow and Live View have not been re-verified with this stylesheet. The visible setup-required state is real, not a simulated successful connection.
- Preview only. Nothing in this section establishes a merge or deployment to `beta.cordiacode.com`.

Implementation checklist: shared visual changes and local regression tests complete; manual/native-keyboard check and authenticated connector-state review remain before full release acceptance.

final result: blocked

## Real-model local HTTP smoke test — 2026-08-30

After explicit user approval to reuse the existing OpenAI key, the isolated local server at `http://127.0.0.1:5058` was restarted at source commit `5a111c4`. Only `OPENAI_API_KEY` was loaded into that process from the existing ignored project env file; no secret was copied into this worktree or displayed. The real default `Agent` used `gpt-5-mini` and the OpenAI Responses API, with no injected transport or workspace double.

Using the synthetic account whose survey/discovery was completed in the earlier browser journey, real HTTP sign-in and two `/api/chat` requests succeeded:

1. Asked for the first useful workflow, selected apps, and approval boundary, without taking actions. HTTP 200 / `ok: true`; the model identified a source-linked weekly project report, Google Drive and Workshop Tracker, and review/approval before sending or editing. No setup card or artifact was produced.
2. Asked to connect Google Drive and show its secure setup card without listing files. HTTP 200 / `ok: true`; the actual runtime returned `type: connector_setup`, `connector_id: google_drive`, `status: needs_configuration`, and the missing Google client configuration names. Google Drive remained `setup_required`; Workshop Tracker remained `planned`; no artifact was produced.

This proves real model response -> application action dispatch -> persisted setup-card behavior over HTTP. It does not prove Google OAuth authorization, connected data, artifact rendering, or the corresponding browser chat interaction. The isolated server deliberately loaded only the approved OpenAI key; its missing Google configuration is not evidence that the live beta server lost its configuration. No Google credentials or consent flow were used.

The prior final source review and its four fixes were independently approved, and the controller's fresh source run passed 153 Python tests and 20 Node controller tests. GitHub CI passed for draft PR #9 at `5a111c4`. Browser post-fix evidence also confirmed Continue disabled for partial Part 1 answers, enabled with all 20, and Part 2 resume after reload. Visual comparison, native choice keyboard activation, browser real-provider/pending-state checks, and authenticated connector/artifact/Live View checks remain open. Nothing has been merged or deployed.

## Final-review source fix evidence — 2026-08-30

This source/test-only fix wave starts from `3b12950`. It does not replace the earlier browser checkpoint or establish a new visual, native-keyboard, or provider acceptance pass.

- Agent context now appends current, per-user runtime connection status and explicitly supersedes historical status snapshots in `connectors.md` and `fde.md`. Real temporary-Store tests cover upgrade, downgrade, absent connection rows, user isolation, and byte-preservation of all three saved files, including user-authored planning text and explicit operator history. These test status transitions are not live provider-verification claims.
- All five terminology domains separate the calibration-control response from four genuine-term familiarity answers. The neutral confidence note stays conservative, preserves self-rating and operator axes, and retains Work / professional as self-rating-only. Source question wording is unchanged.
- The four effective ternary axes compile concrete prompt guidance with stable Part 3 question/answer references. Explicit response feedback updates the guidance; free-text samples do not classify or change it. Communication preferences never grant action authority.
- Continue is disabled for incomplete or invalid persisted-stage drafts. Manifest-driven checks cover ratings, domain familiarity, distinct MOST/LEAST, required/optional text bounds, application details, and active conditional text. Existing native buttons, labels, required inputs, server validation, and input retention after server errors remain intact. Twenty controller tests pass using the existing DOM boundary double; this is not native-browser keyboard evidence.
- Only the tracked `task-4-report.md` scratch report was removed from the index; its ignored local copy remains.

Fresh source verification: `../../.venv/Scripts/python.exe -m unittest discover -s tests -v` passed **153 tests in 49.916 seconds** (exit 0). `node --test tests/onboarding.test.cjs` passed **20 tests** (exit 0). `node --check static/onboarding.js`, Python compilation of the two changed modules, and `git diff --check` passed. The existing deliberate disk-full regression logs its expected traceback; Git emits LF/CRLF warnings, so the full output is not described as pristine.

Outstanding responsive/source visual comparison, full narrow-screen journey, native survey Enter/Space activation, real-provider chat/setup/artifact/Live View checks, and final controller review remain OPEN. No push, merge, or deployment was performed in this fix wave.

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
