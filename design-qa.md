# Cordia Short Design QA

- Source visual truth path: unavailable; the earlier Cordia workspace reference was a temporary conversation attachment that no longer exists on disk.
- Implementation screenshot: `cordia-short-browser.png`
- Browser: Codex in-app browser
- CSS viewport: 1265 x 720
- Implementation pixels: 1264 x 1000 full-page capture
- Density normalization: not applicable; no accessible source capture exists for normalization.
- State: signed-in user after Surveyor, real OpenAI Google Drive proposal, missing-Google-credentials setup card.

## Full-view comparison evidence

Blocked. The implementation was captured from the browser, but the source image could not be opened. No visual-fidelity comparison is claimed.

## Focused region comparison evidence

Blocked for the same reason. The implemented chat rail, setup card, empty artifact area, and workspace memory were inspected directly, but not compared against an accessible source crop.

## Functional browser evidence

- Signed in with a synthetic local QA account.
- Submitted all five Surveyor answers in the same left conversation.
- Observed the saved `memory.md` content in the workspace.
- Sent `Connect Google Drive` through the real OpenAI-backed Cordia Agent.
- Observed a generic connector setup card reporting `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as missing.
- Checked browser warning and error logs: none observed.

## Findings

- P1: Exact visual fidelity cannot be evaluated without the source reference image.
  - Impact: The workspace is functional, but cannot be declared a faithful recreation of the selected target.
  - Fix: Reattach the reference image, capture the same signed-in workspace state at the same viewport, compare them together, and correct P0-P2 differences.
- P1: The real Google Drive connected and artifact-populated states cannot yet be captured.
  - Impact: The most important dashboard state remains externally blocked.
  - Fix: Configure the Google OAuth web client, complete real authorization, run `list_recent_files`, and capture the populated artifact state.

## Required fidelity surfaces

- Fonts and typography: implementation inspected; source comparison blocked.
- Spacing and layout rhythm: implementation inspected at 1265 x 720; source comparison blocked.
- Colors and visual tokens: ivory, sage, olive, paper, and sand tokens are present; source sampling blocked.
- Image quality and asset fidelity: no raster imagery is used in the current core workspace; the previous source cannot be checked for required assets.
- Copy and content: functional copy is visible and explicit about missing configuration; source comparison blocked.

## Comparison history

- Pass 1: implementation captured and interactions verified; comparison blocked because the source reference attachment is unavailable. No fidelity fixes were made from unsupported inference.

## Implementation checklist

- Reattach the Cordia workspace reference image.
- Configure Google OAuth credentials.
- Capture the verified connector and populated artifact state.
- Run source-versus-implementation comparison and fix P0-P2 differences.

final result: blocked
