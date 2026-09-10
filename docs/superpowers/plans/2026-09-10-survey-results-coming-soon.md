# Survey Results Coming-Soon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unfinished post-Surveyor workspace with a persistent, evidence-backed Cordia Profile results page that truthfully summarizes communication preferences, workspace needs, connector plans, and unsupported conclusions.

**Architecture:** Add one pure Python derivation module over the canonical saved Surveyor stages, existing `score_profile()` output, and existing normalized connector records. Expose the bounded result through the current Flask state endpoint behind an environment flag, then render it with a small dedicated browser module inside the existing Cordia shell. Keep the Markdown compiler and existing workspace unchanged as the rollback path.

**Tech Stack:** Python 3.12, Flask, standard-library `unittest`, browser JavaScript, native canvas, HTML, CSS, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-10-survey-results-coming-soon-design.md`

## Global Constraints

- Derive results from persisted structured Surveyor answers; do not parse Markdown and do not call an LLM.
- Do not store a second survey or results copy.
- Do not infer diagnoses, protected traits, provider reliability, unstated jobs, permissions, or authorization.
- Use `Not enough evidence` for unsupported consequential conclusions.
- Requested control level is a preference, not granted authority.
- Preserve the current workspace behind `CORDIA_COMING_SOON_AFTER_SURVEY=false`.
- Suppress automatic connector setup while the coming-soon experience is enabled.
- Reuse existing Cordia colors, typography, spacing, cards, and brand assets.
- Insert user text with DOM text nodes; never interpolate it into HTML.
- Add no runtime dependency.
- Run focused tests only; manual browser verification remains with the user.

---

## File map

- Create `cordia/survey_results.py`: pure result scoring, labels, connector summaries, inference rules, and unknown rules.
- Create `tests/test_survey_results.py`: deterministic unit coverage for formulas, evidence, connector truth, and missing evidence.
- Modify `app.py`: feature-flag evaluation, result-state assembly, and connector-setup suppression.
- Modify `tests/test_app.py`: Flask contract tests for results state, persistence, rollback, and no automatic setup.
- Create `static/survey-results.js`: DOM-safe result renderer and native-canvas plot.
- Modify `static/index.html`: add the hidden results root and load the renderer.
- Modify `static/app.js`: route `state === "results"` to the dedicated renderer.
- Modify `static/styles.css`: responsive Cordia results layout.
- Create `tests/survey_results_ui.test.cjs`: browser-module contract tests using a narrow DOM/canvas double.

### Task 1: Deterministic survey-results derivation

**Files:**
- Create: `cordia/survey_results.py`
- Create: `tests/test_survey_results.py`

**Interfaces:**
- Consumes: `score_profile(stages) -> dict`, canonical `stages["workspace_discovery"]["answers"]`, and `normalize_applications(...) -> list[dict]`.
- Produces: `build_survey_results(stages: dict, profile: dict, applications: list[dict]) -> dict`.
- Produces helpers: `delegation_score(discovery, applications) -> dict`, `context_score(profile) -> dict`, and `breadth_score(discovery, applications) -> dict`.

- [ ] **Step 1: Write failing score and connector tests**

Create `tests/test_survey_results.py` with imports and fixtures based on `tests.test_survey.valid_stages`:

```python
import unittest

from cordia.connectors import CONNECTORS
from cordia.onboarding import normalize_applications, score_profile
from cordia.survey_results import build_survey_results
from tests.test_survey import valid_stages


class SurveyResultsTests(unittest.TestCase):
    def results(self, mutate=None):
        stages = valid_stages()
        if mutate:
            mutate(stages["workspace_discovery"]["answers"])
        discovery = stages["workspace_discovery"]["answers"]
        applications = normalize_applications(discovery["applications"], CONNECTORS, {})
        return build_survey_results(stages, score_profile(stages), applications)

    def test_plot_uses_documented_structured_scores(self):
        def configure(discovery):
            discovery["control_level"] = "automate_low_risk"
            discovery["applications"][0]["control_level"] = "perform_approved_actions"
            discovery["applications"].append({
                "application_id": None,
                "name": "Notion",
                "already_uses": True,
                "wants_added": True,
                "current_activities": "Keep project notes.",
                "desired_activities": "Supply project context.",
                "inputs_outputs": "Notes in, decisions out.",
                "control_level": "prepare_for_approval",
            })
            discovery.update({
                "cadence": "Weekly",
                "people_roles": "Founder reviews",
                "source_locations": "Drive and Notion",
                "environment": ["web", "cloud_services"],
            })

        plot = self.results(configure)["plot"]
        self.assertEqual(67, plot["delegation"]["score"])
        self.assertEqual(100, plot["breadth"]["score"])
        self.assertIn(plot["context"]["score"], (0, 50, 100))

    def test_connector_plan_preserves_truthful_registry_status(self):
        connector = self.results()["connector_plans"][0]
        self.assertEqual("Setup required", connector["status"])
        self.assertEqual("OAuth", connector["auth_method"])
        self.assertIn("permission approval", connector["setup_note"])

    def test_unregistered_application_is_planned_not_failed(self):
        def configure(discovery):
            discovery["applications"] = [{
                "application_id": None,
                "name": "Private Ledger",
                "already_uses": True,
                "wants_added": True,
                "current_activities": "Review balances.",
                "desired_activities": "Prepare a summary.",
                "inputs_outputs": "Balances in, summary out.",
                "control_level": "suggest_actions_only",
            }]

        connector = self.results(configure)["connector_plans"][0]
        self.assertEqual("Planned", connector["status"])
        self.assertIn("not yet available", connector["setup_note"])
```

- [ ] **Step 2: Run the focused test and verify the module is missing**

Run: `..\..\..\.venv\Scripts\python.exe -m unittest tests.test_survey_results -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'cordia.survey_results'`.

- [ ] **Step 3: Implement scores, direct findings, and connector plans**

Create `cordia/survey_results.py` with constant mappings and pure helpers:

```python
from __future__ import annotations

from cordia.onboarding import AXIS_GUIDANCE, AXIS_LABELS, CONTROL_LEVEL_LABELS

CONTROL_SCORES = {
    "suggest_actions_only": 0,
    "prepare_for_approval": 33,
    "perform_approved_actions": 67,
    "automate_low_risk": 100,
}
STATUS_LABELS = {
    "verified": "Connected",
    "needs_attention": "Needs attention",
    "setup_required": "Setup required",
    "planned": "Planned",
}


def _present(value) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def delegation_score(discovery: dict, applications: list[dict]) -> dict:
    selections = [discovery["control_level"]]
    selections.extend(app["control_level"] for app in applications if app.get("control_level"))
    score = round(sum(CONTROL_SCORES[value] for value in selections) / len(selections))
    nearest = min(CONTROL_SCORES, key=lambda key: abs(CONTROL_SCORES[key] - score))
    return {"score": score, "label": CONTROL_LEVEL_LABELS[nearest]}


def context_score(profile: dict) -> dict:
    value = profile["operator_axes"]["context"]
    return {"score": {-1: 0, 0: 50, 1: 100}[value], "label": AXIS_LABELS["context"][value].split(" (")[0]}


def breadth_score(discovery: dict, applications: list[dict]) -> dict:
    signals = (
        len(applications) > 1,
        _present(discovery.get("cadence")),
        _present(discovery.get("people_roles")),
        _present(discovery.get("source_locations")),
        len(discovery.get("environment", [])) > 1,
    )
    score = sum(signals) * 20
    label = "Single task" if score < 40 else "Connected workflow" if score < 80 else "Multi-environment orchestration"
    return {"score": score, "label": label}
```

Implement `build_survey_results()` using small private functions:

```python
def build_survey_results(stages: dict, profile: dict, applications: list[dict]) -> dict:
    discovery = stages["workspace_discovery"]["answers"]
    return {
        "status": {"label": "Workspace coming soon", "detail": "Your profile and workspace plan are saved."},
        "plot": {
            "delegation": delegation_score(discovery, applications),
            "context": context_score(profile),
            "breadth": breadth_score(discovery, applications),
        },
        "direct_findings": _direct_findings(discovery, profile),
        "connector_plans": [_connector_plan(app) for app in applications],
        "indirect_findings": _indirect_findings(discovery, profile, applications),
        "unknowns": _unknowns(discovery, applications),
    }
```

`_direct_findings()` must emit the four operator axes with their existing `AXIS_LABELS` and `AXIS_GUIDANCE`, the five trait scores, domain ratings/calibration confidence, and non-empty workflow fields. `_connector_plan()` must copy only the named safe application fields and map status/auth copy exactly as defined by the specification.

- [ ] **Step 4: Add failing inference and unknown tests**

Append tests that verify every conclusion exposes its evidence and that absent recovery information is not invented:

```python
    def test_indirect_findings_name_evidence_and_behavior(self):
        findings = self.results()["indirect_findings"]
        self.assertTrue(findings)
        for finding in findings:
            self.assertIn(finding["confidence"], ("high", "medium"))
            self.assertGreaterEqual(len(finding["evidence"]), 2)
            self.assertTrue(finding["cordia_behavior"])

    def test_missing_failure_recovery_is_explicit_for_automation(self):
        def configure(discovery):
            discovery["control_level"] = "automate_low_risk"
            discovery["cadence"] = "Every morning"
            discovery.pop("failure_behavior", None)

        unknowns = self.results(configure)["unknowns"]
        recovery = next(item for item in unknowns if item["title"] == "Failure recovery")
        self.assertTrue(recovery["statement"].startswith("Not enough evidence"))

    def test_control_preference_never_claims_authorization(self):
        serialized = str(self.results()).lower()
        self.assertNotIn("permission granted", serialized)
        self.assertNotIn("authorized to", serialized)
```

- [ ] **Step 5: Implement the named inference and unknown rules**

Implement only the rules listed in the specification. Use exact structured comparisons for profile axes and control levels; use presence checks for conditional discovery fields. Create findings with one helper so the shape cannot drift:

```python
def _finding(title: str, statement: str, evidence: list[str], confidence: str, behavior: str) -> dict:
    return {
        "title": title,
        "statement": statement,
        "evidence": evidence,
        "confidence": confidence,
        "cordia_behavior": behavior,
    }
```

Do not classify the meaning of `outcome`, `current_workflow`, prompt examples, or other arbitrary prose. Planned/setup-required connector rules may use the normalized status and declared auth kind because those values are structured.

- [ ] **Step 6: Run the focused derivation tests**

Run: `..\..\..\.venv\Scripts\python.exe -m unittest tests.test_survey_results -v`

Expected: all `SurveyResultsTests` pass.

- [ ] **Step 7: Commit the derivation unit**

```bash
git add cordia/survey_results.py tests/test_survey_results.py
git commit -m "feat: derive evidence-backed survey results"
```

### Task 2: Results state and rollback contract

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `build_survey_results(stages, profile, applications) -> dict` from Task 1.
- Produces: `coming_soon_enabled() -> bool` and `state_payload()` responses with either `state: "results"` plus `survey_results`, or the unchanged `state: "workspace"` contract.

- [ ] **Step 1: Write failing Flask contract tests**

Add a boolean constructor configuration to test setup and add these cases to `tests/test_app.py`:

```python
    def test_completed_survey_returns_persistent_results_state(self):
        self.register()
        self.complete_survey()
        first = self.client.get("/api/state").json
        self.client.post("/api/signout")
        self.client.post("/api/signin", json={"email": "person@example.com", "password": "correct horse battery"})
        second = self.client.get("/api/state").json

        self.assertEqual("results", first["state"])
        self.assertEqual(first["survey_results"], second["survey_results"])
        self.assertEqual("Workspace coming soon", first["survey_results"]["status"]["label"])

    def test_results_mode_does_not_prepare_connector_setup(self):
        self.register()
        self.complete_survey()
        self.assertIsNone(self.client.get("/api/state").json.get("setup_card"))
        self.assertFalse(any(call[1] == "connector_start" for call in self.workspace.calls))

    def test_feature_flag_false_preserves_workspace_contract(self):
        self.app.config["COMING_SOON_AFTER_SURVEY"] = False
        self.register()
        self.complete_survey()
        state = self.client.get("/api/state").json
        self.assertEqual("workspace", state["state"])
        self.assertIn("operator", state)
        self.assertIn("artifacts", state)
```

Update the pre-existing completion test so it explicitly sets `COMING_SOON_AFTER_SURVEY=False`; that test remains the rollback/workspace evidence rather than being rewritten to expect the new state.

- [ ] **Step 2: Run the three focused Flask tests and verify failure**

Run: `..\..\..\.venv\Scripts\python.exe -m unittest tests.test_app.CordiaAppTests.test_completed_survey_returns_persistent_results_state tests.test_app.CordiaAppTests.test_results_mode_does_not_prepare_connector_setup tests.test_app.CordiaAppTests.test_feature_flag_false_preserves_workspace_contract -v`

Expected: results-state assertions fail because completed users still receive `workspace` and completion still calls `connector_start`.

- [ ] **Step 3: Add configuration and results-state assembly**

Import `score_profile` and `build_survey_results`, then extend `app.config.update()`:

```python
COMING_SOON_AFTER_SURVEY=os.getenv("CORDIA_COMING_SOON_AFTER_SURVEY", "true").strip().lower() not in {"false", "0", "no"},
```

Include `auth_kind` in `onboarding_payload()`'s safe selected-application field list. Before the current workspace return in `state_payload()`, add:

```python
        if app.config["COMING_SOON_AFTER_SURVEY"]:
            stages = store.onboarding_stages(user_id)
            try:
                results = build_survey_results(
                    stages,
                    score_profile(stages),
                    onboarding.get("selected_applications", []),
                )
            except (KeyError, TypeError, ValueError):
                app.logger.exception("survey result derivation failed")
                results = {
                    "status": {
                        "label": "Workspace coming soon",
                        "detail": "Your survey is saved, but Cordia could not display the profile yet.",
                    },
                    "plot": None,
                    "direct_findings": [],
                    "connector_plans": [],
                    "indirect_findings": [],
                    "unknowns": [{
                        "title": "Profile display",
                        "statement": "Not enough evidence could be displayed safely. Your saved survey was not changed.",
                    }],
                }
            return {"state": "results", "survey_results": results}
```

In `onboarding_complete()`, call `prepare_selected_setup(user_id)` only when `COMING_SOON_AFTER_SURVEY` is false.

- [ ] **Step 4: Run focused Flask and derivation tests**

Run: `..\..\..\.venv\Scripts\python.exe -m unittest tests.test_survey_results tests.test_app.CordiaAppTests.test_completed_survey_returns_persistent_results_state tests.test_app.CordiaAppTests.test_results_mode_does_not_prepare_connector_setup tests.test_app.CordiaAppTests.test_feature_flag_false_preserves_workspace_contract tests.test_app.CordiaAppTests.test_onboarding_completion_creates_workspace_and_provides_all_context_to_agent -v`

Expected: all selected tests pass, including the existing workspace contract under the disabled flag.

- [ ] **Step 5: Commit the state contract**

```bash
git add app.py tests/test_app.py
git commit -m "feat: expose post-survey results state"
```

### Task 3: Cordia Profile results interface

**Files:**
- Create: `static/survey-results.js`
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Create: `tests/survey_results_ui.test.cjs`

**Interfaces:**
- Consumes: `survey_results` with `status`, `plot`, `direct_findings`, `connector_plans`, `indirect_findings`, and `unknowns`.
- Produces: `window.CordiaSurveyResults.render(root: HTMLElement, results: object) -> void`.

- [ ] **Step 1: Write a failing browser-module contract test**

Create `tests/survey_results_ui.test.cjs` using the narrow `Element` pattern from `tests/onboarding.test.cjs`. The test must load `static/survey-results.js` in a VM and verify text-safe rendering:

```javascript
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("survey results render bounded sections without HTML interpolation", () => {
  const { document, root } = makeDocumentWithCanvas();
  const window = {};
  vm.runInNewContext(fs.readFileSync("static/survey-results.js", "utf8"), { window, document });
  window.CordiaSurveyResults.render(root, {
    status: { label: "Workspace coming soon", detail: "Saved." },
    plot: {
      delegation: { score: 67, label: "Perform approved actions" },
      context: { score: 100, label: "Implicit / high-context" },
      breadth: { score: 40, label: "Connected workflow" },
    },
    direct_findings: [{ title: "Outcome", statement: "<img src=x>" }],
    connector_plans: [{ name: "Slack", status: "Setup required", auth_method: "OAuth", setup_note: "Sign-in required." }],
    indirect_findings: [{ title: "Execution style", statement: "Act first.", evidence: ["Direct", "Answer/action-first"], confidence: "high", cordia_behavior: "Return the result first." }],
    unknowns: [{ title: "Failure recovery", statement: "Not enough evidence to choose recovery behavior." }],
  });

  assert.match(root.textContent, /Workspace coming soon/);
  assert.match(root.textContent, /Slack/);
  assert.match(root.textContent, /Not enough evidence/);
  assert.equal(root.querySelector("img"), null);
  assert.equal(root.querySelectorAll("canvas").length, 1);
});
```

The DOM double must implement `createElement`, `append`, `replaceChildren`, `textContent`, `querySelector`, `querySelectorAll`, `setAttribute`, and a canvas `getContext()` object with `beginPath`, `moveTo`, `lineTo`, `stroke`, `arc`, `fill`, `fillText`, and `clearRect` no-ops.

- [ ] **Step 2: Run the UI contract test and verify the renderer is missing**

Run: `node --test tests/survey_results_ui.test.cjs`

Expected: FAIL with `ENOENT` for `static/survey-results.js`.

- [ ] **Step 3: Add the semantic results markup and renderer**

Add this sibling of `#app-shell` and `#onboarding` to `static/index.html`:

```html
<main id="survey-results" class="survey-results" hidden aria-labelledby="survey-results-title">
  <header class="results-hero">
    <p class="eyebrow">YOUR CORDIA PROFILE</p>
    <h1 id="survey-results-title">How Cordia will work with you</h1>
    <p id="results-status"></p>
  </header>
  <section class="results-grid">
    <article id="results-plot-card" class="results-card results-plot-card"></article>
    <article id="results-workspace-card" class="results-card"></article>
    <article id="results-connectors-card" class="results-card results-wide"></article>
    <article id="results-inferences-card" class="results-card results-wide"></article>
    <article id="results-unknowns-card" class="results-card results-wide"></article>
  </section>
</main>
```

Load `<script src="/static/survey-results.js" defer></script>` after `onboarding.js` and before `app.js`.

Implement `static/survey-results.js` as an IIFE. Build every heading, paragraph, list item, meter label, evidence chip, connector row, and details block with `document.createElement()` and `.textContent`. Use helpers `element(tag, className, text)`, `appendList()`, `renderPlot()`, `renderDirectFindings()`, `renderConnectors()`, `renderInferences()`, and `renderUnknowns()`.

`renderPlot()` must create a canvas with width `520`, height `300`, accessible fallback text, and a nearby `<dl>` containing all three numeric scores and labels. Canvas coordinates must use the documented values:

```javascript
const origin = { x: 74, y: 244 };
const x = origin.x + (plot.delegation.score / 100) * 330;
const y = origin.y - (plot.context.score / 100) * 175;
const zOffset = (plot.breadth.score / 100) * 54;
const point = { x: x + zOffset, y: y - zOffset * 0.55 };
```

Draw three labeled axes and a single olive point. Canvas is the visualization; the `<dl>` is the complete accessible representation.

- [ ] **Step 4: Route only results state to the new renderer**

In `static/app.js`, extend `render(state, transient = {})` so it hides all three top-level surfaces before choosing one:

```javascript
byId("auth-panel").hidden = true;
byId("onboarding").hidden = true;
byId("app-shell").hidden = true;
byId("survey-results").hidden = true;
```

After the onboarding branch and before the workspace branch, add:

```javascript
if (state.state === "results") {
  byId("survey-results").hidden = false;
  byId("status-pill").textContent = "Profile saved";
  window.CordiaSurveyResults.render(byId("survey-results"), state.survey_results);
  return;
}
```

Keep the existing signed-out, onboarding, and workspace branches otherwise unchanged.

- [ ] **Step 5: Add responsive Cordia styling**

In `static/styles.css`, reuse existing custom properties and add:

```css
.survey-results { min-height: calc(100vh - 72px); padding: clamp(32px, 5vw, 72px); background: var(--paper); }
.results-hero { max-width: 760px; margin: 0 auto 32px; text-align: center; }
.results-hero h1 { margin: 8px 0 12px; font-family: "Newsreader", serif; font-size: clamp(2.5rem, 6vw, 4.75rem); font-weight: 500; line-height: .98; }
.eyebrow { color: var(--olive); font-size: .75rem; font-weight: 700; letter-spacing: .22em; }
.results-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; max-width: 1180px; margin: 0 auto; }
.results-card { min-width: 0; padding: 28px; border: 1px solid var(--line); border-radius: 24px; background: var(--paper); box-shadow: var(--elev-1); }
.results-wide { grid-column: 1 / -1; }
.results-plot-card canvas { display: block; width: 100%; max-width: 520px; height: auto; margin: 0 auto; }
.results-coordinate-list, .results-finding-list { margin: 20px 0 0; padding: 0; list-style: none; }
.results-connector-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }
.results-chip { display: inline-flex; margin: 4px 6px 0 0; padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; color: var(--olive); font-size: .78rem; }
@media (max-width: 760px) {
  .survey-results { padding: 28px 18px 48px; }
  .results-grid { grid-template-columns: 1fr; }
  .results-wide { grid-column: auto; }
  .results-card { padding: 22px; border-radius: 20px; }
}
```

Use the existing `--paper`, `--line`, `--olive`, `--muted`, and `--elev-1` tokens shown above. Do not add duplicate color or shadow variables.

- [ ] **Step 6: Run focused UI and server contract tests**

Run: `node --test tests/survey_results_ui.test.cjs`

Expected: PASS.

Run: `..\..\..\.venv\Scripts\python.exe -m unittest tests.test_survey_results tests.test_app.CordiaAppTests.test_completed_survey_returns_persistent_results_state tests.test_app.CordiaAppTests.test_results_mode_does_not_prepare_connector_setup tests.test_app.CordiaAppTests.test_feature_flag_false_preserves_workspace_contract -v`

Expected: all selected tests pass.

- [ ] **Step 7: Perform static safety checks**

Run: `rg -n "innerHTML|insertAdjacentHTML" static/survey-results.js`

Expected: no matches.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 8: Commit the interface**

```bash
git add static/survey-results.js static/index.html static/app.js static/styles.css tests/survey_results_ui.test.cjs
git commit -m "feat: show Cordia profile after Surveyor"
```

### Task 4: Final focused verification and handoff

**Files:**
- Verify only; do not modify files unless a focused check identifies a defect in this feature.

**Interfaces:**
- Consumes: all Task 1-3 commits.
- Produces: a clean feature branch and exact user-run browser instructions.

- [ ] **Step 1: Run the complete focused feature set**

Run: `..\..\..\.venv\Scripts\python.exe -m unittest tests.test_survey_results tests.test_app.CordiaAppTests.test_completed_survey_returns_persistent_results_state tests.test_app.CordiaAppTests.test_results_mode_does_not_prepare_connector_setup tests.test_app.CordiaAppTests.test_feature_flag_false_preserves_workspace_contract tests.test_app.CordiaAppTests.test_onboarding_completion_creates_workspace_and_provides_all_context_to_agent -v`

Expected: all selected Python tests pass.

Run: `node --test tests/survey_results_ui.test.cjs`

Expected: all UI contract tests pass.

- [ ] **Step 2: Inspect scope and branch cleanliness**

Run: `git diff origin/master...HEAD --stat`

Expected: only the files named in this plan plus the approved spec and plan.

Run: `git status --short`

Expected: no output.

- [ ] **Step 3: Hand off manual browser verification**

Give the user one exact local-start command for this worktree and ask them to verify:

1. a new account can complete Surveyor and lands on Your Cordia Profile;
2. returning sign-in does not repeat Surveyor;
3. all visible conclusions trace to their answers;
4. unsupported details say `Not enough evidence`;
5. connector cards say connected/setup required/planned truthfully;
6. mobile and desktop layouts have no horizontal overflow;
7. no connector authorization window opens automatically.

Do not deploy, merge, or change production configuration without a separate explicit user request.
