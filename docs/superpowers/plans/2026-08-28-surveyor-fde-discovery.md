# Surveyor FDE Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chat-based legacy survey with a resumable four-part human assessment plus adaptive FDE workspace discovery that deterministically creates `operator.md`, `connectors.md`, and `fde.md` before the user enters Cordia.

**Architecture:** Keep the current Flask, SQLite, and vanilla JavaScript application. Add one focused survey manifest/validation module and one deterministic compiler module; extend the existing store with versioned stage persistence and atomic workspace-file replacement; expose three onboarding endpoints; and render onboarding through a separate browser controller that hands the user back to the existing continuous workspace after compilation.

**Tech Stack:** Python 3.12, Flask, SQLite, `unittest`, vanilla JavaScript, HTML, CSS

**Spec:** `docs/superpowers/specs/2026-08-28-surveyor-fde-discovery-design.md`

## Global Constraints

- Preserve the exact visible wording and answer choices in the spec's four-part assessment manifest.
- Use survey schema version `2`.
- Store one validated JSON document per onboarding stage in the existing `survey_answers` table.
- Operator axes are always integers in `{-1, 0, 1}`.
- Post-onboarding operator weights change only through explicit user response-adjustment clicks.
- Never ask for credentials during onboarding.
- Never represent a selected application as `verified`; only the existing connector runtime can produce `verified` after a real provider check.
- Survey completion must not require a model call.
- Preserve existing users' messages, artifacts, connections, credentials, connector settings, and operator adjustments.
- Compile `operator.md`, `connectors.md`, and `fde.md` atomically before changing state to `workspace`.
- Use the existing Cordia ivory, sage, typography, spacing, and rounded-card system.
- Do not add a frontend framework, ORM, migration framework, task queue, or model-based survey scorer.

---

## File Responsibility Map

- `cordia/survey.py`: immutable version-2 question manifest, stage order, answer validation, conditional discovery rules, and browser-safe schema payloads.
- `cordia/onboarding.py`: deterministic assessment scoring, operator vote aggregation, connector intent normalization, and Markdown compilation.
- `cordia/store.py`: versioned stage persistence, onboarding completion state, existing adjustment retrieval, and atomic installation of compiled files.
- `app.py`: onboarding state projection and authenticated onboarding endpoints; no scoring or Markdown rendering.
- `static/onboarding.js`: the onboarding browser controller and stage-specific renderers.
- `static/app.js`: integration between auth/state rendering, onboarding, and the existing workspace.
- `static/index.html`: one onboarding layer mounted inside the existing Cordia application.
- `static/styles.css`: responsive onboarding styles using existing tokens.
- `tests/test_survey.py`: question parity, validation, branching, scoring, and compiler unit tests.
- `tests/test_journey.py`: persistence, compilation, adjustments, migration, and end-to-end service tests.
- `tests/test_app.py`: HTTP state and endpoint contracts.
- `tests/test_ui_contract.py`: browser asset and static interaction contracts.

---

### Task 1: Versioned Survey Manifest and Validation

**Files:**
- Create: `cordia/survey.py`
- Create: `tests/test_survey.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION: int = 2`
- Produces: `STAGE_ORDER: tuple[str, ...]`
- Produces: `public_stage_schema(stage: str, answers: dict | None = None) -> dict`
- Produces: `validate_stage(stage: str, payload: dict) -> dict`
- Produces: `next_stage(saved_stages: dict[str, dict]) -> str | None`
- Produces: `conditional_discovery_fields(discovery: dict) -> list[str]`
- Consumes: no application services, database, model, connector runtime, or secrets.

- [ ] **Step 1: Write manifest parity tests**

Create `tests/test_survey.py` with a `SurveyManifestTests(unittest.TestCase)` class. Assert the contract directly rather than relying only on counts:

```python
from cordia.survey import SCHEMA_VERSION, STAGE_ORDER, public_stage_schema


class SurveyManifestTests(unittest.TestCase):
    def test_schema_version_and_stage_order_are_stable(self):
        self.assertEqual(2, SCHEMA_VERSION)
        self.assertEqual(
            (
                "assessment_part_1",
                "assessment_part_2",
                "assessment_part_3",
                "assessment_part_4",
                "profile_snapshot",
                "workspace_discovery",
                "workspace_review",
            ),
            STAGE_ORDER,
        )

    def test_part_one_contains_all_twenty_source_statements(self):
        schema = public_stage_schema("assessment_part_1")
        prompts = [item["prompt"] for item in schema["questions"]]
        self.assertEqual(20, len(prompts))
        self.assertEqual("Am the life of the party.", prompts[0])
        self.assertEqual("Do not have a good imagination.", prompts[-1])
        self.assertTrue(all(item["options"] == [1, 2, 3, 4, 5] for item in schema["questions"]))

    def test_domain_terms_match_the_source(self):
        schema = public_stage_schema("assessment_part_2")
        self.assertEqual(
            ["cloud storage", "two-factor authentication", "adaptive port throttling", "browser cache", "API"],
            schema["domains"]["technology_software"]["terms"],
        )
        self.assertEqual([], schema["domains"]["work_professional"]["terms"])
        self.assertIn("passive humidity banking", schema["domains"]["everyday_general"]["terms"])
```

Also assert every Part 3 prompt and option from the spec, the Part 4 required/optional flags, the 1-2 domain limit, and the `MOST`/`LEAST` distinct-selection rule.

- [ ] **Step 2: Run the new tests and verify the missing-module failure**

Run:

```powershell
python -m unittest tests.test_survey.SurveyManifestTests -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cordia.survey'`.

- [ ] **Step 3: Implement the immutable browser-safe manifest**

Create `cordia/survey.py`. Use tuples internally and return fresh dictionaries/lists from `public_stage_schema()` so callers cannot mutate module constants. Stable question IDs must follow these forms:

```python
SCHEMA_VERSION = 2
STAGE_ORDER = (
    "assessment_part_1",
    "assessment_part_2",
    "assessment_part_3",
    "assessment_part_4",
    "profile_snapshot",
    "workspace_discovery",
    "workspace_review",
)

PART_1 = (
    {"id": "p1_01", "prompt": "Am the life of the party.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_02", "prompt": "Talk to a lot of different people at parties.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_03", "prompt": "Don't talk a lot.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_04", "prompt": "Keep in the background.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_05", "prompt": "Sympathize with others' feelings.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_06", "prompt": "Feel others' emotions.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_07", "prompt": "Am not really interested in others.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_08", "prompt": "Am not interested in other people's problems.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_09", "prompt": "Get chores done right away.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_10", "prompt": "Like order.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_11", "prompt": "Often forget to put things back in their proper place.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_12", "prompt": "Make a mess of things.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_13", "prompt": "Have frequent mood swings.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_14", "prompt": "Get upset easily.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_15", "prompt": "Am relaxed most of the time.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_16", "prompt": "Seldom feel blue.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_17", "prompt": "Have a vivid imagination.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_18", "prompt": "Have difficulty understanding abstract ideas.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_19", "prompt": "Am not interested in abstract ideas.", "options": (1, 2, 3, 4, 5)},
    {"id": "p1_20", "prompt": "Do not have a good imagination.", "options": (1, 2, 3, 4, 5)},
)
```

The implementation must include all entries explicitly; do not generate or paraphrase question text. Define all Part 2 domains and terms, all Part 3 choices, Part 4 fields, Workspace Discovery core fields, and conditional field metadata from the spec.

- [ ] **Step 4: Write stage-validation tests**

Add tests covering valid normalization and every rejection boundary:

```python
from cordia.survey import validate_stage


def test_part_one_requires_all_integer_ratings(self):
    with self.assertRaisesRegex(ValueError, "all 20 statements"):
        validate_stage("assessment_part_1", {"answers": {"p1_01": 5}})

def test_domains_are_limited_to_two(self):
    with self.assertRaisesRegex(ValueError, "1 or 2 domains"):
        validate_stage("assessment_part_2", {
            "domains": ["technology_software", "money_finance", "creative_writing"],
            "ratings": {},
            "familiarity": {},
        })

def test_most_and_least_must_differ(self):
    payload = valid_part_three_payload()
    payload["most"] = payload["least"] = "logical"
    with self.assertRaisesRegex(ValueError, "different"):
        validate_stage("assessment_part_3", payload)

def test_part_four_requires_two_real_prompts(self):
    with self.assertRaisesRegex(ValueError, "Request 2"):
        validate_stage("assessment_part_4", {"request_1": "Help me plan today", "request_2": ""})
```

Include tests for unknown stage names, booleans passed as numeric ratings, values outside `1..5`, unknown domains, missing familiarity answers, unknown Part 3 options, prompt lengths above `2000`, discovery text above `4000`, more than `20` applications, and unexpected keys.

- [ ] **Step 5: Implement strict stage validation and branching**

`validate_stage()` returns a clean canonical dictionary and raises `ValueError` with a field-specific message. It must:

```python
def validate_stage(stage: str, payload: dict) -> dict:
    if stage not in PERSISTED_STAGES:
        raise ValueError("unknown onboarding stage")
    if not isinstance(payload, dict):
        raise ValueError("stage answers must be an object")
    validators = {
        "assessment_part_1": _validate_part_1,
        "assessment_part_2": _validate_part_2,
        "assessment_part_3": _validate_part_3,
        "assessment_part_4": _validate_part_4,
        "workspace_discovery": _validate_workspace_discovery,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "answers": validators[stage](payload),
    }
```

`profile_snapshot` and `workspace_review` are computed stages and are not accepted by `validate_stage()`. `conditional_discovery_fields()` must return stable field IDs based only on saved discovery answers: sensitive-data questions for health/financial/legal/employee/confidential data, failure behavior and approval boundaries for automatic control, and environment/policy questions when those choices are present.

- [ ] **Step 6: Run the focused manifest and validation suite**

Run:

```powershell
python -m unittest tests.test_survey -v
```

Expected: all manifest, normalization, rejection, and conditional-branch tests PASS.

- [ ] **Step 7: Commit the manifest boundary**

```powershell
git add cordia/survey.py tests/test_survey.py
git commit -m "feat: define versioned Surveyor manifest"
```

---

### Task 2: Deterministic Profile and Workspace Compiler

**Files:**
- Create: `cordia/onboarding.py`
- Modify: `tests/test_survey.py`

**Interfaces:**
- Consumes: canonical stage dictionaries returned by `validate_stage()`.
- Consumes: `adjustments: list[dict]` with `response_id`, `label`, `axis`, `previous`, and `current`.
- Consumes: connector catalog entries shaped like the existing `CONNECTORS` records.
- Produces: `score_profile(stages: dict[str, dict]) -> dict`
- Produces: `compile_documents(stages: dict[str, dict], adjustments: list[dict], connector_catalog: dict[str, dict], connection_statuses: dict[str, str] | None = None) -> dict[str, str]`
- Produces document keys exactly: `operator.md`, `connectors.md`, `fde.md`.

- [ ] **Step 1: Write scoring tests for all operator axes**

Extend `tests/test_survey.py` with canonical payload helpers and assertions:

```python
from cordia.onboarding import score_profile


class ProfileCompilerTests(unittest.TestCase):
    def test_part_one_reverse_scoring_is_normalized(self):
        stages = valid_stages()
        stages["assessment_part_1"]["answers"] = {f"p1_{number:02d}": 5 for number in range(1, 21)}
        profile = score_profile(stages)
        self.assertEqual(5.0, profile["traits"]["social_energy"])
        self.assertEqual(2.5, profile["traits"]["imagination_abstraction"])

    def test_part_three_votes_compile_to_ternary_axes(self):
        stages = valid_stages()
        stages["assessment_part_3"]["answers"].update({
            "briefing_style": "gist",
            "literal_or_inferred": "inferred",
            "flawed_plan": "state_plainly",
            "answer_order": "answer_first",
            "background": "infer_context",
            "edit_boundary": "flag_unmentioned",
            "bad_idea": "ask_questions",
        })
        self.assertEqual(
            {"context": 1, "scope": 1, "directness": 1, "implementation": 1},
            score_profile(stages)["operator_axes"],
        )

    def test_split_votes_resolve_to_balanced(self):
        stages = valid_stages()
        stages["assessment_part_3"]["answers"].update({
            "flawed_plan": "state_plainly",
            "bad_idea": "soften_heavily",
        })
        self.assertEqual(0, score_profile(stages)["operator_axes"]["directness"])
```

Verify the formula `(keyed_sum - item_count) / (item_count * 4) * 10`, one-decimal rounding, the exact Part 3 vote table, and that MOST/LEAST values appear as evidence without changing axes.

- [ ] **Step 2: Run scoring tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_survey.ProfileCompilerTests -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cordia.onboarding'`.

- [ ] **Step 3: Implement pure scoring functions**

Create `cordia/onboarding.py` with no file or database access. Use explicit mappings:

```python
TRAIT_KEYS = {
    "social_energy": (("p1_01", "p1_02"), ("p1_03", "p1_04")),
    "interpersonal_sensitivity": (("p1_05", "p1_06"), ("p1_07", "p1_08")),
    "order_follow_through": (("p1_09", "p1_10"), ("p1_11", "p1_12")),
    "emotional_reactivity": (("p1_13", "p1_14"), ("p1_15", "p1_16")),
    "imagination_abstraction": (("p1_17",), ("p1_18", "p1_19", "p1_20")),
}


def _vote(values: list[int]) -> int:
    total = sum(values)
    return -1 if total < 0 else 1 if total > 0 else 0
```

Return a profile containing `traits`, `domains`, `operator_axes`, `prompt_examples`, and `evidence`. Do not call a model or infer extra scores from free text.

- [ ] **Step 4: Write compiler tests for the three Markdown files**

Add exact contract assertions:

```python
from cordia.connectors import CONNECTORS
from cordia.onboarding import compile_documents


def test_compiler_creates_all_three_readable_documents(self):
    documents = compile_documents(valid_stages(), [], CONNECTORS)
    self.assertEqual({"operator.md", "connectors.md", "fde.md"}, set(documents))
    self.assertIn("Context interpretation: Implicit / high-context (1)", documents["operator.md"])
    self.assertIn("## Prompt examples", documents["operator.md"])
    self.assertIn("Status: setup_required", documents["connectors.md"])
    self.assertIn("Status: planned", documents["connectors.md"])
    self.assertIn("## Smallest valuable workspace slice", documents["fde.md"])

def test_selected_application_never_compiles_as_verified(self):
    documents = compile_documents(valid_stages(), [], CONNECTORS)
    self.assertNotIn("Status: verified", documents["connectors.md"])

def test_adjustment_evidence_is_preserved(self):
    documents = compile_documents(valid_stages(), [{
        "response_id": 9,
        "label": "Give me the implementation",
        "axis": "implementation",
        "previous": 0,
        "current": 1,
    }], CONNECTORS)
    self.assertIn("Response 9", documents["operator.md"])
    self.assertIn("changed from 0 to 1", documents["operator.md"])
```

Assert known connector aliases normalize to the registry ID, unknown apps remain `planned`, current and desired activity are present, security/failure constraints are present only when answered, and `fde.md` labels unimplemented work as proposed.

- [ ] **Step 5: Implement deterministic document compilation**

Use small private renderers with one responsibility each:

```python
def compile_documents(stages, adjustments, connector_catalog, connection_statuses=None):
    profile = score_profile(stages)
    applications = _normalize_applications(
        stages["workspace_discovery"]["answers"]["applications"],
        connector_catalog,
        connection_statuses or {},
    )
    return {
        "operator.md": _render_operator(profile, adjustments),
        "connectors.md": _render_connectors(applications),
        "fde.md": _render_fde(stages["workspace_discovery"]["answers"], applications),
    }
```

Known catalog entries selected by the user compile as `setup_required`; unknown entries compile as `planned`. When `Store` supplies an existing runtime-owned `verified` or `needs_attention` value in `connection_statuses`, that truthful value is preserved. Normalize aliases case-insensitively through the existing connector registry. The compiler receives statuses only; it never reads credentials or queries providers.

Apply adjustments in ascending order after the survey baseline is scored: each adjustment's validated `current` value replaces that axis in the final operator map. This preserves the explicit feedback loop without allowing survey recompilation to erase learned preferences.

- [ ] **Step 6: Run compiler tests**

Run:

```powershell
python -m unittest tests.test_survey -v
```

Expected: all manifest, validation, scoring, and compiler tests PASS.

- [ ] **Step 7: Commit the deterministic compiler**

```powershell
git add cordia/onboarding.py tests/test_survey.py
git commit -m "feat: compile Surveyor workspace context"
```

---

### Task 3: Resumable Persistence and Atomic Workspace Installation

**Files:**
- Modify: `cordia/store.py`
- Modify: `tests/test_journey.py`

**Interfaces:**
- Consumes: `validate_stage()` and `compile_documents()` from Tasks 1-2.
- Produces: `Store.save_onboarding_stage(user_id: int, stage: str, payload: dict) -> dict`
- Produces: `Store.onboarding_stages(user_id: int) -> dict[str, dict]`
- Produces: `Store.onboarding_state(user_id: int) -> dict`
- Produces: `Store.complete_onboarding(user_id: int, connector_catalog: dict) -> dict[str, str]`
- Preserves: `Store.save_survey_answer()` and `Store.survey_answers()` for legacy reads.

- [ ] **Step 1: Write persistence and resume tests**

Add to `tests/test_journey.py`:

```python
def test_onboarding_stage_round_trips_as_validated_json(self):
    user_id = self.store.register("person@example.com", "correct-horse-battery")
    saved = self.store.save_onboarding_stage(user_id, "assessment_part_1", valid_part_one_payload())
    self.assertEqual(2, saved["schema_version"])
    self.assertEqual(saved, self.store.onboarding_stages(user_id)["assessment_part_1"])

def test_onboarding_resumes_first_incomplete_stage(self):
    user_id = create_user(self.store)
    self.store.save_onboarding_stage(user_id, "assessment_part_1", valid_part_one_payload())
    state = self.store.onboarding_state(user_id)
    self.assertEqual("assessment_part_2", state["current_stage"])
    self.assertEqual(["assessment_part_1"], state["completed_stages"])
```

Assert malformed JSON rows fail closed as incomplete, later stages cannot be persisted before prior required stages, and computed stages are not stored as user answers.

- [ ] **Step 2: Run focused persistence tests and verify failure**

Run:

```powershell
python -m unittest tests.test_journey.JourneyTests.test_onboarding_stage_round_trips_as_validated_json tests.test_journey.JourneyTests.test_onboarding_resumes_first_incomplete_stage -v
```

Expected: FAIL with `AttributeError` for the missing store methods.

- [ ] **Step 3: Implement versioned stage persistence**

Store canonical JSON with sorted keys and compact separators:

```python
def save_onboarding_stage(self, user_id, stage, payload):
    current = self.onboarding_state(user_id)["current_stage"]
    if stage != current and stage not in self.onboarding_stages(user_id):
        raise ValueError(f"complete {current} first")
    document = validate_stage(stage, payload)
    document["completed_at"] = self._now().isoformat()
    self._save_survey_value(user_id, stage, json.dumps(document, sort_keys=True, separators=(",", ":")))
    return document
```

Extract the current insert/update SQL into `_save_survey_value()` so legacy scalar writes and versioned JSON use one database boundary. `onboarding_state()` returns schema version, current stage, completed stages, safe saved answers, and computed profile/review data when those stages are reached. Stage selection follows this exact state machine:

- first missing assessment part -> that persisted part;
- all four assessment parts present and discovery absent -> `profile_snapshot`;
- discovery present and version marker absent -> `workspace_review`;
- version marker `2` present -> complete workspace.

`profile_snapshot` and `workspace_review` are view-only states. The browser advances locally from Profile Snapshot to the Workspace Discovery form; refreshing before saving discovery intentionally shows the snapshot again. Workspace Review advances only through `POST /api/onboarding/complete`.

- [ ] **Step 4: Write atomic compilation and preservation tests**

Add tests that create complete valid stages, an existing agent adjustment, an artifact, and a verified connection. Then call `complete_onboarding()` and assert:

```python
def test_completion_atomically_installs_three_files_and_preserves_runtime_state(self):
    user_id = complete_all_stages(self.store)
    self.store.save_connection(user_id, "google_drive", "verified", {"access_token": "encrypted"})
    documents = self.store.complete_onboarding(user_id, CONNECTORS)
    workspace = self.store.workspace_root / str(user_id)
    self.assertEqual(documents["operator.md"], (workspace / "operator.md").read_text(encoding="utf-8"))
    self.assertTrue((workspace / "connectors.md").exists())
    self.assertTrue((workspace / "fde.md").exists())
    self.assertEqual("verified", self.store.connection_status(user_id, "google_drive"))
```

Patch the third temporary-file write to raise `OSError` and assert all pre-existing destination files remain byte-for-byte unchanged and onboarding remains incomplete.

- [ ] **Step 5: Implement compilation transaction and atomic file replacement**

`complete_onboarding()` must:

1. Verify every persisted required stage with `validate_stage()`.
2. Read existing operator adjustments in ascending ID order.
3. Call `compile_documents()`.
4. Write all three files into a unique temporary directory under the user's workspace.
5. Preserve existing destinations as in-process backups.
6. Replace all three destinations.
7. Restore every backup if any replacement fails.
8. Persist `survey_schema_version = "2"` only after all replacements succeed.

Use `secrets.token_hex(8)` for the temporary directory suffix and `Path.replace()` for final installation. Remove the temporary directory with explicit files after success or rollback; do not recursively delete an unresolved path.

Before calling `compile_documents()`, read statuses only for the selected known connector IDs and pass them through `connection_statuses`. A runtime-owned `verified` or `needs_attention` status may replace `setup_required`, while selection alone still cannot create either runtime status.

- [ ] **Step 6: Keep legacy operator callers compatible**

Update `operator_markdown()` to return the compiled version-2 file when present. Keep the current legacy `_write_operator()` path for users whose version-2 onboarding has not completed, so existing tests and rollback behavior remain readable. `survey_complete()` returns true only for version 2 after successful compilation; add `legacy_survey_complete()` for the old route.

- [ ] **Step 7: Run persistence, journey, and existing regression tests**

Run:

```powershell
python -m unittest tests.test_journey -v
python -m unittest discover -s tests -v
```

Expected: new persistence/atomicity tests PASS and all existing tests remain green.

- [ ] **Step 8: Commit the persistence boundary**

```powershell
git add cordia/store.py tests/test_journey.py
git commit -m "feat: persist resumable FDE onboarding"
```

---

### Task 4: Authenticated Onboarding API and State Transition

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: Store methods from Task 3.
- Produces: `GET /api/onboarding`
- Produces: `PUT /api/onboarding/<stage>`
- Produces: `POST /api/onboarding/complete`
- Changes authenticated state values to `onboarding` or `workspace`.
- Preserves existing connector, agent, chat, adjustment, and Live View endpoints.

- [ ] **Step 1: Write API state and resume tests**

Add to `tests/test_app.py`:

```python
def test_register_enters_version_two_onboarding(self):
    state = self.register()
    self.assertEqual("onboarding", state["state"])
    self.assertEqual(2, state["onboarding"]["schema_version"])
    self.assertEqual("assessment_part_1", state["onboarding"]["current_stage"])
    self.assertNotIn("artifacts", state)

def test_stage_save_returns_next_resumable_stage(self):
    self.register()
    response = self.client.put("/api/onboarding/assessment_part_1", json=valid_part_one_payload())
    self.assertEqual(200, response.status_code)
    self.assertEqual("assessment_part_2", response.json["onboarding"]["current_stage"])
```

Assert all onboarding endpoints require authentication and never expose credentials or connection tokens.

- [ ] **Step 2: Run API tests and verify contract failure**

Run:

```powershell
python -m unittest tests.test_app.AppTests.test_register_enters_version_two_onboarding tests.test_app.AppTests.test_stage_save_returns_next_resumable_stage -v
```

Expected: FAIL because state is still `survey` and the endpoint is missing.

- [ ] **Step 3: Replace chat-survey state projection with onboarding state**

Remove `SURVEY_QUESTIONS` and `next_survey()` from the primary state path. Build authenticated state as:

```python
onboarding = store.onboarding_state(user_id)
onboarding["stage_schemas"] = {
    stage: public_stage_schema(stage, onboarding["answers"])
    for stage in STAGE_ORDER
}
if not onboarding["complete"]:
    return {"state": "onboarding", "onboarding": onboarding}
return {
    "state": "workspace",
    "operator": store.operator_markdown(user_id),
    "messages": store.messages(user_id),
    "artifacts": decorated_artifacts,
    "setup_card": store.setup_card(user_id),
    "agent_runtime": runtime.agent_runtime(user_id) or default_agent_runtime,
}
```

Do not expose existing workspace artifacts, setup cards, or the agent runtime while onboarding is incomplete. `stage_schemas` contains browser-safe labels, options, and conditional field definitions for every stage, allowing Profile Snapshot to advance locally to Workspace Discovery without another state mutation. The signed-out payload remains `{"state": "signed_out"}`.

- [ ] **Step 4: Implement the three endpoints with exact status behavior**

```python
@app.get("/api/onboarding")
def onboarding_state():
    user_id = require_user()
    return jsonify({"ok": True, "onboarding": store.onboarding_state(user_id)})

@app.put("/api/onboarding/<stage>")
def onboarding_stage(stage):
    user_id = require_user()
    try:
        store.save_onboarding_stage(user_id, stage, request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "onboarding": store.onboarding_state(user_id)})

@app.post("/api/onboarding/complete")
def onboarding_complete():
    user_id = require_user()
    try:
        store.complete_onboarding(user_id, CONNECTORS)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc), "onboarding": store.onboarding_state(user_id)}), 409
    except OSError:
        return jsonify({"ok": False, "error": "Cordia could not safely create your workspace. Your survey is saved."}), 500
    return jsonify({"ok": True, **state_payload(user_id)})
```

Import `CONNECTORS` in addition to `resolve_connector`. Return the first incomplete stage in the `409` error text. Log the internal file exception through Flask's logger without returning paths to the browser.

- [ ] **Step 5: Preserve the legacy route without exposing it to version-2 UI**

Keep `POST /api/survey` only for a user with legacy scalar answers and no saved version-2 stages. Return `410` with `{"error": "Continue in the new Surveyor"}` for other users. Update old route tests to assert this boundary rather than driving new registrations through chat questions.

- [ ] **Step 6: Write completion and failure tests**

Cover:

- completion before all stages -> `409` and first incomplete stage;
- validation failure -> `400` with field-specific error;
- successful completion -> `workspace`, three files exist, real artifacts still preserved;
- compiler I/O failure -> `500`, state remains `onboarding`, old files unchanged;
- `/api/chat` before completion -> `409 complete Surveyor first`;
- no model invocation occurs during any onboarding endpoint.

- [ ] **Step 7: Run API and full backend suites**

Run:

```powershell
python -m unittest tests.test_app -v
python -m unittest discover -s tests -v
```

Expected: all API contracts and existing connector/agent/runtime behavior PASS.

- [ ] **Step 8: Commit the API transition**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: expose resumable Surveyor onboarding"
```

---

### Task 5: Production Onboarding Interface

**Files:**
- Create: `static/onboarding.js`
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Modify: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `GET /api/onboarding`, `PUT /api/onboarding/<stage>`, and `POST /api/onboarding/complete`.
- Produces: `window.CordiaOnboarding.createController({root, api, onComplete})`.
- Preserves: existing chat, pending indicator, artifacts, account menu, model settings, setup cards, connector actions, and Live View behavior.

- [ ] **Step 1: Write static contract tests before markup or JavaScript**

Add to `tests/test_ui_contract.py`:

```python
def test_onboarding_layer_and_script_are_present(self):
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    self.assertIn('id="onboarding"', html)
    self.assertIn('/static/onboarding.js', html)

def test_onboarding_controller_uses_stage_and_completion_endpoints(self):
    script = (ROOT / "static" / "onboarding.js").read_text(encoding="utf-8")
    self.assertIn('PUT', script)
    self.assertIn('/api/onboarding/', script)
    self.assertIn('/api/onboarding/complete', script)
    self.assertNotIn('localStorage', script)

def test_chat_composer_no_longer_posts_survey_answers(self):
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    self.assertNotIn('"/api/survey"', script)
    self.assertNotIn('Answer Surveyor', script)
```

Also assert the onboarding root has an accessible heading target, error region with `aria-live`, progress label, Back/Continue action region, and no credential fields.

- [ ] **Step 2: Run UI contract tests and verify failure**

Run:

```powershell
python -m unittest tests.test_ui_contract -v
```

Expected: FAIL because `static/onboarding.js` and onboarding markup do not exist.

- [ ] **Step 3: Add the focused onboarding HTML layer**

Add one sibling of `#app-shell`:

```html
<section id="onboarding" class="onboarding" hidden aria-labelledby="onboarding-title">
  <header class="onboarding-brand"><span class="brand-mark" aria-hidden="true">∞</span><span>cordia</span></header>
  <main class="onboarding-panel">
    <p id="onboarding-progress" class="onboarding-progress"></p>
    <h1 id="onboarding-title"></h1>
    <p id="onboarding-instructions" class="onboarding-instructions"></p>
    <form id="onboarding-form">
      <div id="onboarding-fields"></div>
      <p id="onboarding-error" role="alert" aria-live="assertive"></p>
      <div class="onboarding-actions">
        <button id="onboarding-back" type="button">BACK</button>
        <button id="onboarding-continue" type="submit">CONTINUE</button>
      </div>
    </form>
  </main>
</section>
<script src="/static/onboarding.js" defer></script>
```

Use a text infinity mark only where the current Cordia application already uses it; do not invent a replacement logo asset.

- [ ] **Step 4: Implement the controller and generic stage renderers**

`static/onboarding.js` must be an IIFE exposing only `createController`. The controller owns local unsaved form state, while the server owns completed stages:

```javascript
window.CordiaOnboarding = (() => {
  function createController({ root, api, onComplete }) {
    let onboarding = null;

    async function show(state) {
      onboarding = state;
      root.hidden = false;
      renderCurrentStage();
    }

    function hide() {
      root.hidden = true;
    }

    return { show, hide };
  }

  return { createController };
})();
```

Implement explicit renderers for:

- Part 1: twenty labeled 1-5 button groups.
- Part 2: six domain buttons, 1-2 selection enforcement, selected-domain rating, and terminology Familiar/Not familiar buttons.
- Part 3: all choice groups plus distinct MOST/LEAST controls.
- Part 4: two required and one optional textareas.
- Profile snapshot: descriptive summary, trait rows, three visible communication axes, and Continue.
- Workspace Discovery: required core, searchable application rows, per-application current/desired use, control level, and server-provided conditional fields.
- Workspace Review: outcome, first slice, selected apps/statuses, approval boundary, Back, and Build my workspace.

Use `<button type="button" aria-pressed="true|false">` for selectable cards. Every response group needs a visible label and keyboard focus. Escape all server text before `innerHTML`; prefer DOM node creation for user-authored discovery values. Profile Snapshot Continue changes the controller's viewed stage to `workspace_discovery` using the already returned `stage_schemas`; it does not send a computed-stage document to the server.

- [ ] **Step 5: Implement save, resume, back, and completion behavior**

On Continue:

1. Serialize the current renderer into the exact stage payload.
2. Disable navigation buttons.
3. `PUT /api/onboarding/<current_stage>`.
4. Replace controller state with the response.
5. Render the next stage and focus the heading.
6. On `400`, show the server's field message and preserve inputs.

Back changes only the viewed stage among already completed stages; it does not erase saved answers. Editing and continuing replaces that stage and recomputes later computed screens. Workspace Review submits `POST /api/onboarding/complete`; only a returned `workspace` state invokes `onComplete(state)`.

- [ ] **Step 6: Integrate onboarding into `static/app.js`**

Create the controller once after the existing `api()` helper:

```javascript
const onboardingController = window.CordiaOnboarding.createController({
  root: byId("onboarding"),
  api,
  onComplete: (state) => render(state),
});
```

In `render(state)`:

- signed out -> hide onboarding and workspace;
- onboarding -> hide app shell/account, call `onboardingController.show(state.onboarding)`, and return;
- workspace -> hide onboarding, show the existing shell/account, and execute the existing workspace rendering unchanged.

Remove survey prompting and the conditional `/api/survey` composer path. The chat composer always posts `/api/chat` because it is inaccessible until onboarding completes.

- [ ] **Step 7: Add responsive Cordia onboarding styles**

Use existing CSS variables. Required behavior:

- fixed full viewport layer above the workspace;
- ivory background, sage active states, current Cordia serif headings;
- centered content width no larger than `980px`;
- question cards with the existing border radius and border token;
- persistent action row inside the panel, not covering fields;
- two-column layouts collapse to one column below `760px`;
- `:focus-visible` outline at least `2px`;
- `prefers-reduced-motion` disables nonessential transitions;
- textareas have labels and at least `120px` height;
- no horizontal scrolling at `375px` viewport width.

- [ ] **Step 8: Run syntax and UI contract checks**

Run:

```powershell
node --check static/onboarding.js
node --check static/app.js
python -m unittest tests.test_ui_contract -v
python -m unittest discover -s tests -v
```

Expected: JavaScript syntax checks and all Python tests PASS.

- [ ] **Step 9: Commit the working onboarding interface**

```powershell
git add static/onboarding.js static/index.html static/app.js static/styles.css tests/test_ui_contract.py
git commit -m "feat: add Surveyor onboarding experience"
```

---

### Task 6: Real End-to-End Journey, Migration Proof, and Release Documentation

**Files:**
- Modify: `tests/test_journey.py`
- Modify: `README.md`
- Modify: `design-qa.md`

**Interfaces:**
- Consumes: the complete onboarding, store, API, UI, connector registry, agent, and workspace runtime.
- Produces: one executable service-level journey and a release checklist that distinguishes tests, local browser proof, merge, and live deployment.

- [ ] **Step 1: Write the complete service journey before final implementation adjustments**

Add a new test that uses a real temporary SQLite database, real `Store`, real onboarding compiler, fake model only at the post-onboarding agent boundary, and the existing recording workspace client:

```python
def test_register_to_compiled_workspace_to_connector_proposal(self):
    register = self.client.post("/api/register", json={
        "email": "journey@example.com",
        "password": "correct-horse-battery",
    })
    self.assertEqual("onboarding", register.json["state"])

    for stage, payload in complete_onboarding_payloads().items():
        saved = self.client.put(f"/api/onboarding/{stage}", json=payload)
        self.assertEqual(200, saved.status_code)

    completed = self.client.post("/api/onboarding/complete")
    self.assertEqual("workspace", completed.json["state"])

    workspace = Path(self.temp.name) / "workspaces" / "1"
    self.assertIn("Prompt examples", (workspace / "operator.md").read_text(encoding="utf-8"))
    self.assertIn("Google Drive", (workspace / "connectors.md").read_text(encoding="utf-8"))
    self.assertIn("Smallest valuable workspace slice", (workspace / "fde.md").read_text(encoding="utf-8"))

    chat = self.client.post("/api/chat", json={"message": "Connect Google Drive"})
    self.assertEqual("google_drive", chat.json["setup_card"]["connector_id"])
```

Assert the model receives the compiled operator profile, the selected connector is still not verified, and the setup card—not onboarding—owns the later credential boundary.

- [ ] **Step 2: Add a legacy-user migration regression**

Create a user with legacy scalar survey answers, an operator adjustment, one artifact, a verified Google Drive connection, and an active model selection. Assert their next state is version-2 onboarding; after completion all prior runtime records remain, the operator adjustment appears in the new `operator.md`, and the real `verified` connection status appears in `connectors.md` without being regenerated by the survey.

- [ ] **Step 3: Run the full automated verification suite**

Run:

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py cordia/agent.py cordia/connectors.py cordia/connector_runtime.py cordia/onboarding.py cordia/store.py cordia/survey.py cordia/workspace_mcp.py
node --check static/app.js
node --check static/onboarding.js
git diff --check
```

Expected: every command exits `0`. Record the actual test count in `design-qa.md`; do not predict or round it.

- [ ] **Step 4: Run the real local browser journey**

Start the Flask service with an isolated temporary database and workspace root. In a clean browser session, verify:

1. Registration opens Part 1, not the Agent chat.
2. Refresh resumes the first incomplete section.
3. Every Part 1-4 question and answer choice is reachable.
4. Invalid progression remains disabled or produces a field-level message.
5. Profile Snapshot matches the submitted answers.
6. Workspace Discovery accepts one known and one unknown app and captures per-app activities.
7. Conditional safety and failure questions appear from relevant answers.
8. Workspace Review shows truthful `setup_required` and `planned` statuses.
9. Completion opens the existing workspace.
10. The Cordia Agent chat still sends on Enter, renders the pending infinity indicator, and uses `operator.md`.
11. Asking to connect the known app creates the existing real setup card.
12. Existing artifact, model settings, account menu, connector, and Live View interactions still behave as before.

Inspect browser console errors and failed requests. A screenshot without interaction is insufficient.

- [ ] **Step 5: Run responsive and visual comparison QA**

At desktop width, compare each assessment part with the captured source survey for sequence, grouping, labels, controls, and progression. At `375x812`, verify no horizontal overflow, readable questions, accessible selections, and reachable actions. Record differences that are intentional Cordia-brand adaptations in `design-qa.md`.

- [ ] **Step 6: Update operator documentation and QA evidence**

Update `README.md` with:

- sign-in -> assessment -> discovery -> compiled workspace flow;
- the three generated files and their responsibilities;
- the fact that onboarding never collects credentials or verifies connectors;
- exact local test and run commands;
- existing-user migration behavior.

Update `design-qa.md` with the actual commit, test count, browser viewport/state, verified interactions, console/network result, and explicit remaining limitations. Do not label GitHub merge or live deployment complete during local verification.

- [ ] **Step 7: Commit end-to-end evidence and documentation**

```powershell
git add tests/test_journey.py README.md design-qa.md
git commit -m "test: verify Surveyor FDE onboarding journey"
```

- [ ] **Step 8: Perform final branch verification**

Run the complete Step 3 command set again from a clean process. Confirm `git status --short` is empty. Review the branch diff against `origin/master` and the approved spec, specifically checking:

- no question or option is missing or paraphrased;
- no model call occurs during onboarding;
- no selection creates `verified` status;
- atomic compilation rollback is covered;
- explicit adjustments survive recompilation;
- the current workspace and connector paths were extended rather than duplicated.

Expected: clean worktree, all checks exit `0`, and every acceptance criterion in the spec has direct automated or browser evidence.
