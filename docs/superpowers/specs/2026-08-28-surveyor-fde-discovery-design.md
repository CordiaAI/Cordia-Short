# Cordia Surveyor and FDE Discovery Design

**Date:** 2026-08-28

**Status:** Approved in chat; written-spec review pending

**Source experience:** `https://cordia-survey1.vercel.app/survey`

## Purpose

After sign-in, Cordia must learn both the person and the work before opening the workspace. The onboarding flow has two deliberately separate responsibilities:

1. The unchanged four-part assessment learns how the user communicates, reasons, and supplies context.
2. A short adaptive FDE discovery step learns the user's desired outcome, current workflow, applications, permission boundaries, and first useful workspace slice.

Cordia then compiles three readable workspace files:

- `operator.md`: how to interpret the user's prompts and communicate with them.
- `connectors.md`: which applications are involved, how the user uses them, and their truthful connection status.
- `fde.md`: the initial forward-deployed engineering plan for building the workspace.

The survey performs discovery. It does not claim that a connector, model, skill, or automation works until the corresponding real provider or runtime path is verified.

## Scope

### Included

- A resumable onboarding experience that appears after registration or sign-in when the current survey version is incomplete.
- Content parity with every visible question and answer option in the four-part source survey.
- A deterministic profile compiler with evidence and discrete Cordia operator axes.
- Adaptive FDE workspace discovery.
- Searchable application selection, including applications not yet present in Cordia's connector catalog.
- Per-application current-use and desired-use capture.
- Atomic compilation of `operator.md`, `connectors.md`, and `fde.md`.
- A profile snapshot before workspace entry.
- Preservation of the existing explicit response-feedback loop.

### Excluded from this slice

- Connecting or authenticating applications during the survey.
- Asking for API keys, passwords, OAuth codes, or other credentials.
- Automatically choosing cloud architecture, RAG, agents, or infrastructure before the discovered workflow requires them.
- Treating an application selection as a verified connector.
- Alidora or advanced agent-system design.
- Billing, enterprise administration, or compliance certification.

## User Flow

```text
Register or sign in
  -> Four-part human assessment
  -> Profile snapshot
  -> Adaptive Workspace Discovery
  -> Review first workspace plan
  -> Compile operator.md + connectors.md + fde.md
  -> Enter the continuous Cordia workspace
  -> Cordia Agent continues with the compiled context
```

The onboarding is rendered inside the existing single-page application as a focused, full-screen layer. It is not a separate product and does not place survey questions in the Cordia Agent chat. Each completed section is saved immediately so refreshes and sign-ins resume at the first incomplete section.

## Four-Part Assessment Question Manifest

The wording and answer choices below are source requirements. Question identifiers are stable internal keys; visible numbering is not required.

### Part 1 of 4: About you

Visible instructions:

> Describe yourself as you generally are now, not as you wish to be in the future. Describe yourself as you honestly see yourself, in relation to other people you know of the same sex and age. Rate each statement from 1 (Very Inaccurate) to 5 (Very Accurate).

Every statement uses buttons `1`, `2`, `3`, `4`, and `5`, labeled from `Very Inaccurate` to `Very Accurate`.

1. Am the life of the party.
2. Talk to a lot of different people at parties.
3. Don't talk a lot.
4. Keep in the background.
5. Sympathize with others' feelings.
6. Feel others' emotions.
7. Am not really interested in others.
8. Am not interested in other people's problems.
9. Get chores done right away.
10. Like order.
11. Often forget to put things back in their proper place.
12. Make a mess of things.
13. Have frequent mood swings.
14. Get upset easily.
15. Am relaxed most of the time.
16. Seldom feel blue.
17. Have a vivid imagination.
18. Have difficulty understanding abstract ideas.
19. Am not interested in abstract ideas.
20. Do not have a good imagination.

### Part 2 of 4: Your domains

Visible instructions:

> Pick 1-2 areas where you'd bring real context to an AI conversation.

Domain choices:

- Work / professional (whatever your actual job is)
- Technology & software
- Money & finance
- Health & wellness
- Creative & writing
- Everyday life / general knowledge

For each selected domain, ask:

> How would you rate your knowledge of [domain]? (1 = beginner, 5 = expert)

The rating uses buttons `1` through `5`.

`Work / professional` has no generic terminology check because the user's profession is not known yet. The other domains ask whether each term is `Familiar` or `Not familiar`.

**Technology & software**

- cloud storage
- two-factor authentication
- adaptive port throttling
- browser cache
- API

**Money & finance**

- APR
- annualized credit
- amortization
- compound interest
- diversification

**Health & wellness**

- inflammation
- metabolic threshold syncing
- BMI
- cholesterol
- electrolytes

**Creative & writing**

- dangling modifier
- narrative displacement clause
- iambic pentameter
- thesis statement
- active voice

**Everyday life / general knowledge**

- the food-safety temperature danger zone
- expiration vs. best-by dates
- daylight saving time
- recycling symbols
- passive humidity banking

The terminology check calibrates confidence in the self-rating. It must not shame the user, reveal a "gotcha," or turn unfamiliarity into a general intelligence claim.

### Part 3 of 4: How you communicate

Visible instructions:

> There are no right answers — pick whichever feels closest to how you actually operate.

1. **You're briefing a new assistant on a task. You'd rather:**
   - Write out every requirement and constraint upfront
   - Give the gist and correct it as you go
2. **"Can you look at this and tell me what you think?" Which reply would you rather get?**
   - A literal, narrow reply that answers only what was explicitly asked
   - A reply that infers likely unstated context and addresses it
3. **Pick which word describes you MOST, and which describes you LEAST.**
   - logical
   - practical
   - imaginative
   - data-driven
4. **A colleague's plan has an obvious flaw. Do you:**
   - State it plainly
   - Ask leading questions to get them there
   - Hint at it
   - Go along with it
5. **When someone asks you a question, you tend to:**
   - Walk through your reasoning first, then give the answer
   - Give the answer first, then reasoning if asked
6. **When explaining something to someone, you usually:**
   - Assume they need the background spelled out
   - Assume they'll pick up what you mean from context
7. **"Hey, could you take a pass at this before I send it?" Which reply would you rather get?**
   - A reply that makes only the specific edits literally requested
   - A reply that also flags likely problems the sender didn't mention
8. **Someone asks your opinion on something you think is a bad idea. You:**
   - Say so directly
   - Soften it heavily
   - Ask questions instead of stating your view

The MOST and LEAST selections must be different.

### Part 4 of 4: In your own words

Visible instructions:

> Write 2-3 things you'd actually type to an AI assistant if you were using one right now for something real — not test questions, actual requests you'd send.

- Request 1 (required)
- Request 2 (required)
- Request 3 (optional)

These prompt samples are stored as user-authored evidence. Cordia may use them as examples when interpreting future prompts, but the system does not silently change operator weights by guessing whether a sample is "good" or "bad."

## Workspace Discovery

Workspace Discovery follows the profile snapshot and is visually presented as the next onboarding stage, not as a fifth psychometric section.

### Required core

1. **Outcome**
   - What is the first meaningful result you want this workspace to produce?
   - How will you know it worked?
2. **Current workflow**
   - Walk Cordia through how you handle this today.
3. **Applications**
   - Which applications are involved?
   - For each application: What do you currently do here?
   - For each application: What would you like Cordia to do here?
4. **Inputs and outputs**
   - What information starts this workflow?
   - What should Cordia produce or change?
5. **Control level**
   - Suggest actions only
   - Prepare work for approval
   - Perform approved actions
   - Automate low-risk actions
6. **First workspace**
   - Which part should Cordia build first?

When the answer is obvious from earlier responses, Cordia recommends the smallest valuable first workspace slice and lets the user accept or edit it.

### Conditional follow-ups

Only show a follow-up when the core answers make it relevant:

- Where are the relevant documents, records, or messages?
- Is this occasional, daily, continuous, or event-triggered?
- Roughly how many files, records, customers, or requests are involved?
- Who creates, reviews, approves, or receives the work?
- What may Cordia read, create, edit, send, or execute?
- Does the workflow involve personal, financial, health, legal, employee, or confidential information?
- Does the work happen on the web, desktop, local files, a company network, cloud services, or mobile devices?
- What should happen if the automation fails?
- Is there a deadline or response-time requirement?
- Are there company policies, compliance rules, preferred providers, or prohibited tools?

Branching is rule-based. It does not require a model call. For example, selecting financial or health data exposes the sensitive-data question; selecting automatic operation exposes failure behavior and approval boundaries.

## Application Selection Contract

The application picker combines:

- Known entries from Cordia's provider-neutral connector registry.
- A manual application name field for anything not in the registry.

Each selected application records:

- `application_id` when known; otherwise `null`.
- User-visible application name.
- Whether the user already uses it, wants it added, or both.
- Current activities.
- Desired Cordia activities.
- Relevant inputs and outputs.
- Requested control level.
- Connection status.

Initial connection status is always one of:

- `requested`: the user selected the application.
- `setup_required`: Cordia has a supported connector manifest and can offer setup later.
- `planned`: Cordia recorded an unsupported application for later implementation.

Only the existing connector runtime may promote a connector to `verified`, and only after authentication plus a successful bounded provider request. Survey completion never starts OAuth, accepts credentials, or writes `verified`.

## Storage Model

Keep the storage change small by continuing to use the existing `survey_answers` table. Store one validated JSON document per stable field:

- `assessment_part_1`
- `assessment_part_2`
- `assessment_part_3`
- `assessment_part_4`
- `workspace_discovery`
- `survey_schema_version`

The current scalar survey keys remain readable for migration but do not define completion for schema version `2`.

Every JSON document contains:

- `schema_version`
- `answers`
- `completed_at`

The server validates allowed keys, answer types, ranges, required values, maximum lengths, and application counts before persistence. The browser never supplies compiled scores, operator weights, connection status, or Markdown.

## Deterministic Profile Compilation

### Human-facing profile

Part 1 is scored as a compact personality inventory. Positive items use the selected value; reverse-keyed items use `6 - selected value`.

| Descriptive trait | Positive items | Reverse-keyed items |
| --- | --- | --- |
| Social energy | 1, 2 | 3, 4 |
| Interpersonal sensitivity | 5, 6 | 7, 8 |
| Order and follow-through | 9, 10 | 11, 12 |
| Emotional reactivity | 13, 14 | 15, 16 |
| Imagination and abstraction | 17 | 18, 19, 20 |

Each trait is normalized to `0-10` with `(keyed_sum - item_count) / (item_count * 4) * 10`, rounded to one decimal place. These values are descriptive display data. They are not diagnoses, authority grants, or direct operator-axis overrides.

Part 2 records selected domains, self-rating, terminology evidence, and an expertise-confidence note. The deliberately implausible terminology items are calibration controls; they do not appear as accusations in the profile.

Part 3 produces the visible communication profile and the operational axes below.

### Cordia operator axes

The Cordia Agent receives only discrete operational values:

- `context`: `-1` explicit/literal, `0` balanced, `1` implicit/high-context.
- `scope`: `-1` detail-first, `0` balanced, `1` big-picture.
- `directness`: `-1` measured/indirect, `0` balanced, `1` direct.
- `implementation`: `-1` reasoning-first, `0` balanced, `1` answer/action-first.

Part 3 produces operator votes as follows:

| Evidence | `-1` vote | `0` vote | `1` vote |
| --- | --- | --- | --- |
| Briefing style -> `scope` | Every requirement upfront | — | Gist, then correction |
| Literal versus inferred reply -> `context` | Literal and narrow | — | Infer likely context |
| Colleague's flawed plan -> `directness` | Hint or go along | Leading questions | State it plainly |
| Answer ordering -> `implementation` | Reasoning first | — | Answer first |
| Background assumption -> `context` | Spell out background | — | Infer from context |
| Edit boundary -> `context` | Only requested edits | — | Flag likely unmentioned problems |
| Opinion on bad idea -> `directness` | Soften heavily | Ask questions | Say so directly |

For axes with multiple votes, the compiler uses the sign of the vote sum: negative becomes `-1`, zero becomes `0`, and positive becomes `1`. The MOST/LEAST word selection is retained as descriptive evidence but does not silently alter an operator axis. Part 1 may shape descriptive communication notes but does not override an explicit Part 3 preference.

The prompt samples from Part 4 are stored as evidence, not classified into hidden personality scores. This avoids asking a model to guess whether it understood the user correctly.

After onboarding, operator weights change only when the user selects an explicit response adjustment. Existing `operator_adjustments` remain authoritative and survive profile recompilation.

## Compiled Workspace Files

Compilation is server-owned, deterministic, and atomic. Temporary files are written first and replace the destination only after all three render successfully.

### `operator.md`

- Purpose and authority boundary.
- Human-facing profile summary.
- Domain context and calibrated expertise.
- Prompt interpretation map with the four `-1 / 0 / 1` axes.
- Concrete guidance connecting survey answers to likely prompt behavior.
- User-authored prompt examples.
- Evidence references to stable question identifiers.
- Explicit response-adjustment history.

### `connectors.md`

For every selected application:

- Name and registry identifier when available.
- Already used, wanted, or both.
- Current activities.
- Desired Cordia activities.
- Required inputs and expected outputs.
- Requested control level and approval boundary.
- Authentication type when known from the registry.
- Truthful status: `requested`, `setup_required`, `planned`, `verified`, or `needs_attention`.

### `fde.md`

- Desired business or personal outcome.
- Success criteria.
- Current workflow.
- Proposed first future workflow.
- Smallest valuable workspace slice.
- Required applications and missing connections.
- Proposed initial artifacts and skills.
- Human-approval boundaries.
- Data sensitivity, security, environment, reliability, and timing constraints when relevant.
- Ordered implementation sequence.
- Explicit unknowns the Cordia Agent must resolve through conversation or verified action.

`fde.md` is a plan, not proof that the work is implemented.

## Application Interfaces

### State

Authenticated state adds:

```json
{
  "state": "onboarding",
  "onboarding": {
    "schema_version": 2,
    "current_stage": "assessment_part_1",
    "completed_stages": [],
    "answers": {}
  }
}
```

After compilation, state becomes `workspace` and includes the current operator Markdown as it does today.

### Endpoints

- `GET /api/onboarding`: returns the resumable, authenticated onboarding state.
- `PUT /api/onboarding/<stage>`: validates and replaces one complete stage document.
- `POST /api/onboarding/complete`: validates all required stages, compiles the files, and transitions to the workspace.

The old `POST /api/survey` endpoint remains temporarily available only for users already inside the legacy flow. New schema-version-2 sessions use the onboarding endpoints.

### Error behavior

- Validation errors return `400` with field-level messages and preserve the user's browser inputs.
- Missing required stages return `409` with the first incomplete stage.
- Compilation failure returns `500`, keeps onboarding incomplete, and leaves prior workspace files unchanged.
- Unknown applications are accepted as `planned`; they do not cause survey failure.
- No model is required for survey completion. Model unavailability therefore cannot fabricate or block the deterministic profile.

## Migration

- Users with `survey_schema_version = 2` and all required stages complete enter the workspace normally.
- Existing users without version `2` see the new onboarding once after their next authenticated load.
- Existing messages, artifacts, connections, encrypted credentials, connector settings, and operator adjustments are preserved.
- Recompiling the initial operator profile must not erase later explicit adjustments.

## Visual and Interaction Requirements

- Preserve the source survey's four-part sequence, question grouping, progress language, and response controls.
- Use the established Cordia-Short ivory, sage, typography, spacing, and rounded-card system so onboarding feels like the same product.
- Keep one primary decision per visual block and a persistent `BACK` / `CONTINUE` or `FINISH` action area.
- Disable progression until the current stage is valid.
- Save each completed stage before advancing.
- Support keyboard navigation, visible focus, screen-reader labels, and mobile layouts.
- The workspace remains hidden until compilation succeeds; there is no partial workspace that pretends onboarding is complete.

## Testing and Evidence

### Unit tests

- The manifest contains every required source question and answer option.
- Part 1 reverse scoring and normalization.
- Part 2 domain validation and terminology calibration.
- Part 3 vote-to-axis mapping, including ties resolving to `0`.
- Part 4 length and required-field validation.
- Conditional FDE discovery rules.
- Connector status derivation without false verification.
- Stable deterministic Markdown compilation.
- Operator adjustments surviving recompilation.

### API tests

- New registration enters onboarding.
- Every stage rejects incomplete or malformed answers.
- Refresh and sign-in resume the first incomplete stage.
- Completion is impossible before all required stages.
- Successful completion creates all three files and enters the workspace.
- Compilation failure preserves prior files and remains in onboarding.
- Existing users migrate without losing connectors, artifacts, messages, or adjustments.

### Browser journey

Run the real flow in a clean account:

1. Register.
2. Complete all four assessment parts.
3. Confirm the profile snapshot.
4. Select at least one known and one unknown application.
5. Describe current and desired activity for each.
6. Complete the adaptive discovery questions.
7. Review the first workspace plan.
8. Enter the workspace.
9. Confirm the Cordia Agent receives `operator.md`.
10. Confirm application selections are visible but not falsely marked connected.

Browser evidence must include desktop and mobile layouts, zero blocking console errors, and direct inspection of the generated Markdown files. A passing unit suite alone is not release evidence.

## Acceptance Criteria

- A signed-in user sees the four-part survey outside the Agent chat.
- Every source question and answer option in this document is present.
- The flow is resumable and validates each stage.
- Workspace Discovery gathers outcome, workflow, applications, per-application use, inputs, outputs, control level, and first slice.
- Conditional questions appear only when relevant.
- Completion produces readable `operator.md`, `connectors.md`, and `fde.md`.
- Operator axes are always `-1`, `0`, or `1` and include evidence.
- Explicit user feedback remains the only post-onboarding weight-adjustment mechanism.
- Selected applications are never represented as verified connections.
- The existing Cordia Agent, connector runtime, artifact workspace, and live connections remain intact.
- The end-to-end browser journey produces real application state and generated files without mocks or fabricated success.
