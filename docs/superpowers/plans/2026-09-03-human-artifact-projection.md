# Human Artifact Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert arbitrary sanitized connector results into bounded, human-readable Cordia artifact cards instead of raw JSON.

**Architecture:** A small pure Python projector converts provider data into one of four Cordia-owned view types: `summary`, `metric`, `list`, or `table`. `WorkspaceMCPClient` uses that projector for every application without provider-name branches, while the existing browser renderer selects markup by artifact type.

**Tech Stack:** Python 3 standard library, Flask/SQLite integration already present, vanilla JavaScript/CSS, Python `unittest`, Node built-in test runner.

**Spec:** `docs/superpowers/specs/2026-09-03-autonomous-artifact-workspace-design.md`

## Global Constraints

- Surveyor remains the workspace specification; this sprint does not change its questions.
- Named applications/actions are fixtures only and must never branch production code.
- No new runtime dependency or duplicate connector, agent, or artifact persistence framework.
- Raw JSON, authentication context, tokens, scopes, response metadata, opaque IDs, and unbounded provider payloads are never rendered.
- Tables are bounded to 8 columns and 25 rows; summaries are bounded to 12 items.
- Preserve the currently working Pipedream application discovery and execution path.
- Do not execute automated tests in this sprint session. Add focused tests and provide the exact commands for the user to run.

---

### Task 1: Pure provider-neutral artifact projector

**Files:**
- Create: `cordia/artifact_views.py`
- Create: `tests/test_artifact_views.py`

**Interfaces:**
- Consumes: `project_artifact(title: str, source: str, operation_id: str, result: dict) -> dict` arguments from `WorkspaceMCPClient`.
- Produces: a validated artifact-shaped dictionary with one `type` from `summary`, `metric`, `list`, or `table` and bounded display fields.

- [ ] **Step 1: Write the unexecuted contract tests**

```python
def test_nested_provider_payload_becomes_a_summary_without_json_or_metadata():
    artifact = project_artifact(
        "Example Work", "app_alpha", "current-user",
        {"authContext": {"token": "secret"}, "user": {"name": "Jordan", "timezone": "Central"}},
    )
    assert artifact["type"] == "summary"
    assert artifact["items"] == [
        {"label": "Name", "value": "Jordan"},
        {"label": "Timezone", "value": "Central"},
    ]
    assert "secret" not in str(artifact)
    assert "{" not in str(artifact["items"])

def test_collection_becomes_a_bounded_table():
    artifact = project_artifact(
        "Example Work", "app_beta", "list-work",
        {"items": [{"title": "Launch", "status": "Open"}] * 30},
    )
    assert artifact["type"] == "table"
    assert artifact["columns"] == ["Title", "Status"]
    assert len(artifact["rows"]) == 25
```

- [ ] **Step 2: Implement `project_artifact` with bounded recursive decoding**

Decode JSON-looking provider strings, unwrap single display containers, redact metadata by key, collect scalar leaves, and choose the smallest useful view type. Limit recursion to 6 levels, strings to 240 characters, tables to 8 columns by 25 rows, lists to 25 items, and summaries to 12 items.

- [ ] **Step 3: Keep projection deterministic**

Preserve provider insertion order, derive labels from keys without connector-specific mappings, and attach only `source`, `operation_id`, and a non-secret `provenance` record.

- [ ] **Step 4: Defer test execution to the user**

Run later: `python -m unittest tests.test_artifact_views -v`

Expected after implementation: all artifact projector tests pass.

### Task 2: Integrate the projector at the existing MCP boundary

**Files:**
- Modify: `cordia/workspace_mcp.py`
- Modify: `tests/test_workspace_mcp.py`

**Interfaces:**
- Consumes: `project_artifact(...)` from Task 1.
- Produces: application and generic remote MCP calls with the same `{result, artifact}` envelope already consumed by `AgentRuns` and `app.py`.

- [ ] **Step 1: Update the application-result contract test**

Change the current-user fixture assertion from raw table rows to:

```python
self.assertEqual("summary", called["artifact"]["type"])
self.assertEqual(
    [
        {"label": "Name", "value": "Jordan"},
        {"label": "Timezone", "value": "Central"},
    ],
    called["artifact"]["items"],
)
```

- [ ] **Step 2: Replace `_artifact` with the projector**

Both `call_application_tool` and the temporary generic remote-server path call `project_artifact`. Remove JSON serialization of nested display values. Do not alter the provider result returned to the internal agent.

- [ ] **Step 3: Expand artifact validation without expanding persistence**

`_validate_artifact` accepts exactly the four display types and validates the display field required by each type. `Store.save_artifact` remains the single persistence path and its schema remains unchanged.

- [ ] **Step 4: Defer test execution to the user**

Run later: `python -m unittest tests.test_artifact_views tests.test_workspace_mcp -v`

Expected after implementation: both focused Python modules pass.

### Task 3: Render four human artifact types

**Files:**
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Modify: `tests/setup.test.cjs`

**Interfaces:**
- Consumes: artifact dictionaries accepted by Task 2.
- Produces: escaped semantic card markup; no provider payload is interpreted in the browser.

- [ ] **Step 1: Add unexecuted renderer assertions**

Use the existing VM/DOM harness and assert that `renderArtifact` produces labeled summary rows, one prominent metric, a readable list, and a table. Include a value containing `<script>` and assert it is escaped.

- [ ] **Step 2: Split body rendering by artifact type**

Add small `renderSummaryArtifact`, `renderMetricArtifact`, `renderListArtifact`, and `renderTableArtifact` functions. Unknown types render a safe unavailable message; they never fall back to `JSON.stringify`.

- [ ] **Step 3: Add minimal dashboard styling**

Add styles for `.artifact-summary`, `.artifact-metric`, and `.artifact-list`. Preserve the existing responsive card grid and table styling.

- [ ] **Step 4: Defer test execution to the user**

Run later: `node --test tests/setup.test.cjs`

Expected after implementation: setup/controller tests pass and the browser shows no raw JSON in connector cards.

### Task 4: Static review and user test handoff

**Files:**
- Modify: `docs/CURRENT_BUILD_TRUTH.md`

**Interfaces:**
- Consumes: completed source diff from Tasks 1 through 3.
- Produces: an accurate status note that distinguishes static review from user-run verification.

- [ ] **Step 1: Review only the bounded diff**

Inspect changed artifact files, run `git diff --check` only, and search production code for provider-name branches and browser `JSON.stringify` fallbacks. Do not start the app or run automated tests.

- [ ] **Step 2: Update capability truth**

Record that live Slack OAuth/read proof preceded this sprint, human artifact projection is implemented but awaiting user-run verification, and automatic post-Surveyor building remains the next sprint.

- [ ] **Step 3: Hand off one combined command**

```powershell
python -m unittest tests.test_artifact_views tests.test_workspace_mcp -v
```

Run the browser check only after the command passes: restart the local server, call the existing read-only connected-app tool, and confirm the artifact card contains readable labels rather than raw JSON.
