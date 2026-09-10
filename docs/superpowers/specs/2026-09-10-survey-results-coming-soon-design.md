# Survey Results Coming-Soon Experience

## Purpose

After a user completes Surveyor, Cordia will show a polished, persistent results screen instead of opening the unfinished workspace. The screen explains how Cordia expects the user to work with AI, what the requested workspace needs, and what remains unknown. It uses the same stored survey answers and scoring functions that generate `operator.md`, `connectors.md`, and `fde.md`; it does not parse those Markdown files or introduce a second profile system.

This release is a truthful coming-soon boundary. It saves the completed profile and build context, but does not claim that the workspace or requested connectors are live.

## User experience

1. The user signs in and completes the existing Surveyor flow.
2. Completion persists the same canonical survey stages and compiles the existing Markdown artifacts.
3. Cordia does not launch connector authorization while the coming-soon experience is enabled.
4. The browser transitions directly to **Your Cordia Profile**.
5. The page shows:
   - a clear `Workspace coming soon` status;
   - an accessible three-axis plot with one point representing the user's requested AI working style;
   - short direct findings supported by individual answers;
   - connector plans for every application the user named;
   - cross-answer findings with visible evidence and confidence;
   - explicit `Not enough evidence` statements where Cordia cannot support a conclusion.
6. Returning users who completed Surveyor return to this results page without taking the survey again.

The page will use the existing Cordia visual system: warm ivory and pale sand surfaces, sage/olive accents, formal rounded cards, existing typography, spacing, buttons, and brand assets. It will be responsive, readable without horizontal scrolling, and will never display raw JSON or Markdown.

## Architectural boundary

Add one pure derivation module, `cordia/survey_results.py`, which accepts canonical onboarding stages, the existing scored profile, and normalized applications. It returns a JSON-safe `survey_results` object. The module performs no I/O, model calls, provider calls, or free-text semantic classification.

`app.py` will expose this derived object through the existing state payload. When `CORDIA_COMING_SOON_AFTER_SURVEY` is enabled and Surveyor is complete, the state is `results`; when disabled, the current `workspace` state and behavior remain available as the rollback path.

The feature flag defaults to enabled for this release. Setting it to `false`, `0`, or `no` restores the existing post-survey workspace without a code rollback.

The existing Markdown compiler remains the canonical agent context path. Results are derived directly from the same persisted source data so the human-facing summary and agent-facing documents cannot drift because of Markdown parsing.

## Results data contract

The browser receives this bounded structure:

```json
{
  "state": "results",
  "survey_results": {
    "status": {
      "label": "Workspace coming soon",
      "detail": "Your profile and workspace plan are saved."
    },
    "plot": {
      "delegation": {"score": 67, "label": "Perform approved actions"},
      "context": {"score": 100, "label": "Inferential"},
      "breadth": {"score": 60, "label": "Connected workflow"}
    },
    "direct_findings": [
      {"title": "Response style", "statement": "Lead with the answer or action."}
    ],
    "connector_plans": [
      {
        "name": "Slack",
        "status": "Setup required",
        "auth_method": "OAuth",
        "current_activities": "...",
        "desired_activities": "...",
        "inputs_outputs": "...",
        "control": "Perform approved actions",
        "setup_note": "Sign-in and provider permission approval will be required."
      }
    ],
    "indirect_findings": [
      {
        "title": "Concise, context-aware execution",
        "statement": "Cordia should act first, keep replies brief, and label consequential assumptions.",
        "evidence": ["Answer/action-first", "Implicit / high-context"],
        "confidence": "high",
        "cordia_behavior": "Return the result first; ask only when a missing fact changes the action."
      }
    ],
    "unknowns": [
      {"title": "Failure recovery", "statement": "Not enough evidence to choose what Cordia should do after a failed automation."}
    ]
  }
}
```

Text supplied by the user is returned only in the fields where it was entered. The server will not convert free text into numeric scores or factual claims.

## Plot model

The visualization uses three product-relevant axes, each normalized to an integer from 0 to 100:

### X: Delegation

`Suggest` → `Prepare` → `Perform` → `Automate`

Map every available workspace-level and application-level control selection as follows, then average the selections and round to the nearest integer:

- `suggest_actions_only`: 0
- `prepare_for_approval`: 33
- `perform_approved_actions`: 67
- `automate_low_risk`: 100

This measures desired operating authority, not authorization already granted.

### Y: Context expectation

`Literal` → `Balanced` → `Inferential`

Reuse `score_profile().operator_axes.context`:

- `-1`: 0
- `0`: 50
- `1`: 100

### Z: Workflow breadth

`Single task` → `Connected workflow` → `Multi-environment orchestration`

Award 20 points for each structured signal that is present:

- more than one selected application;
- a non-empty cadence answer;
- a non-empty people/roles answer;
- a non-empty source-locations answer;
- more than one selected environment.

This score is intentionally conservative. It does not infer orchestration from prose.

The UI draws three labeled axes and the user point on a small native canvas, avoiding a chart dependency. Beside the canvas, a semantic definition list repeats all coordinates and labels so the result remains accessible and understandable if canvas is unavailable.

## Direct findings

Direct findings restate scored or explicitly provided data without expanding its meaning:

- the four existing operator axes and their existing labels/guidance;
- five personality trait scores, clearly labeled as survey-derived descriptions rather than diagnoses;
- selected domain, self-rating, and calibration confidence;
- the requested outcome, success criteria, first workspace slice, inputs, outputs, cadence, and approval boundary when present;
- each selected application and its explicit current activity, desired activity, input/output role, and requested control level.

The UI favors short sentences and bullets. Long user-entered text is preserved but collapsed behind `Show details` when it would overwhelm a card.

## Connector plans and truthful status

Connector plans reuse `normalize_applications()` and the existing connector registry.

- `verified`: display `Connected`.
- `needs_attention`: display `Needs attention` and state that reauthorization or provider attention may be required.
- `setup_required`: display `Setup required` and describe only the registry's declared auth kind.
- `planned`: display `Planned` and state that the application is not yet available in the provider catalog.

Known auth notes are deterministic:

- OAuth: user sign-in and provider permission approval will be required.
- API key: a scoped key will be required and must not be placed in chat.
- no declared auth kind: setup requirements are not yet known.

The page will not claim provider reliability, available operations, or granted permissions unless those facts already exist in the registry or connection state.

## Indirect findings

An indirect finding is emitted only by a named deterministic rule. Each result contains the conclusion, evidence labels, confidence, and the behavior Cordia should follow.

High confidence requires at least two independent structured answers. Medium confidence requires one structured answer plus a directly relevant, non-empty workflow field. Otherwise the result is omitted or represented as an unknown.

Initial rule set:

- High-context + answer/action-first: act concisely, use likely context, and label consequential assumptions.
- Literal context + detail-first: stay within the stated request and ask for consequential missing requirements before broadening.
- Direct + answer/action-first: state the result first and avoid padded explanations.
- Reasoning-first + measured/direct preference: place the requested reasoning before the recommendation while matching the selected tone.
- Automation preference + sensitive-data selection: automate only low-risk steps and require approval before sensitive or externally consequential actions.
- Multiple applications + source locations: prepare for cross-application handoffs and verify identity, permissions, and data shape at every boundary.
- Recurring cadence + missing failure behavior: report that a recovery rule is still needed before recurring execution can be safe.
- Planned application: report a catalog/implementation gap, not a connection failure.
- Setup-required application + declared auth kind: report an expected authorization boundary, not provider unreliability.
- Sensitive data + selected environment: treat the named data and environment as a privacy constraint and preserve the stated policy details.

No rule may diagnose personality, infer protected traits, assert real provider failures, invent an unstated job, or treat a requested control level as permission.

## Unknown and insufficient evidence behavior

The server produces explicit unknowns for consequential details that are absent but relevant to selected answers. Examples include failure recovery for recurring/automated work, approval boundaries for action-taking, sensitive-data handling, or unknown authentication requirements for a planned connector.

The exact copy begins with `Not enough evidence` and states what answer is missing. Empty sections are not filled with generic AI prose.

## Frontend changes

- Add one results root to `static/index.html`, hidden in every non-results state.
- Add a bounded results renderer and small canvas plot renderer to `static/app.js`.
- Add results layout styles to `static/styles.css`, reusing existing design tokens and components.
- Keep sign-out and account navigation available.
- Do not show fake connector buttons, deployment controls, or a nonfunctional workspace.
- Do not expose internal evidence keys, raw stage objects, raw JSON, or the Markdown artifacts.

## Completion, retries, and rollback

While the flag is enabled, survey completion compiles and saves the context but skips `prepare_selected_setup()`. This prevents an OAuth popup from interrupting a coming-soon page that cannot yet use the connection.

If result derivation fails, return a bounded error and the existing completed-survey state without deleting the survey. Do not substitute invented results.

Rollback requires only setting `CORDIA_COMING_SOON_AFTER_SURVEY=false` and restarting the service. The database schema, stored stages, Markdown artifacts, and existing workspace remain unchanged.

## Privacy and security

- Do not send survey results to a model to create this page.
- Do not store a second copy of the survey or derived results.
- Do not expose credentials, provider tokens, or internal connector responses.
- Treat trait scores as descriptive survey outputs, not psychological diagnoses.
- Treat control preferences as preferences, never as authorization.
- Escape all user text through DOM text nodes; do not interpolate it into HTML.

## Verification scope

Implementation will add focused tests but will not run the full suite unless the user requests it:

- pure unit tests for all three score formulas, boundary labels, inference evidence, and insufficient-evidence behavior;
- Flask contract tests for `state: results`, returning-user persistence, feature-flag rollback, and suppression of automatic connector setup;
- frontend contract tests confirming results rendering, text-only insertion, no raw Markdown/JSON, and no horizontal overflow at the existing mobile and desktop breakpoints.

Manual browser verification remains with the user, as requested. Focused tests are feature evidence only, not a production-release claim.

## Non-goals

- Building or enabling the final workspace.
- Connecting or executing any application.
- Replacing the existing Surveyor or Markdown compiler.
- Using an LLM to analyze the survey.
- Moving AutoStudyAI or Supabase data.
- Changing Cordia authentication, Alidora, DNS, deployment, or connector architecture.

## Acceptance criteria

- A completed survey opens the results page immediately and stays complete across sign-out/sign-in.
- The plot scores are reproducible from documented structured inputs.
- Every indirect finding names its evidence and confidence.
- Unsupported conclusions appear as `Not enough evidence` or do not appear.
- Every selected application has an honest plan/status card without claiming unavailable capabilities.
- No OAuth or API-key setup begins automatically while the coming-soon flag is enabled.
- Raw JSON and Markdown never appear in the user interface.
- Disabling the flag restores the current workspace path without data migration or code changes.
