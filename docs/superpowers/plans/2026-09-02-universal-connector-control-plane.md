# Universal Connector Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Cordia's static named connector allowlist with a Pipedream-backed dynamic application, managed-auth, and tool path that works identically for arbitrary catalog applications.

**Architecture:** `ConnectorRuntime` remains the one catalog/auth owner and calls Pipedream REST endpoints through an injected transport. `WorkspaceMCPClient` remains the one MCP transport owner and invokes Pipedream's app-scoped remote MCP server. Existing Surveyor, setup-card, agent-run, approval, and artifact owners consume provider-neutral application/tool records.

**Tech Stack:** Python 3, Flask, SQLite, official MCP Python SDK, Pipedream Connect REST API, Pipedream remote MCP, vanilla JavaScript/CSS.

**Spec:** `docs/superpowers/specs/2026-09-02-universal-connector-control-plane-design.md`

## Global Constraints

- Named applications/actions are fixtures only and must never branch production code.
- No static app records, provider OAuth endpoints, provider scopes, provider tool mappings, or checked-in provider logos.
- Pipedream developer secrets remain server-only; customer provider credentials never enter Cordia.
- Only provider account health or provider-derived tool evidence may establish verified/success state.
- Replace existing owners; do not add a second catalog, OAuth manager, MCP boundary, agent loop, or artifact framework.
- No deployment in this task.

---

### Task 1: Dynamic catalog and managed connection

**Files:**
- Replace: `cordia/connectors.py`
- Modify: `cordia/connector_runtime.py`
- Test: `tests/test_connectors.py`

**Interfaces:**
- Produces: `ConnectorRuntime.search_applications(user_id: int, query: str = "", limit: int = 60) -> list[dict]`, `ConnectorRuntime.start_connection(user_id: int, app_id: str) -> dict`, and `ConnectorRuntime.verify_connection(user_id: int, app_id: str, state: str) -> dict`.

- [ ] Write parameterized failing tests using two unrelated opaque app fixtures; assert both use identical URLs/control flow and no production app name appears.
- [ ] Run the tests and confirm they fail because the runtime still imports `CONNECTORS`.
- [ ] Implement short-lived Pipedream developer tokens, app listing/search, customer-scoped Connect links, and healthy-account verification through the existing injected HTTP transport.
- [ ] Run focused connector tests and confirm both fixtures pass.
- [ ] Remove static provider records and local provider logo assets.

### Task 2: Dynamic MCP tool discovery and execution

**Files:**
- Modify: `cordia/workspace_mcp.py`
- Test: `tests/test_workspace_mcp.py`

**Interfaces:**
- Consumes: server token/config from `ConnectorRuntime`.
- Produces: `application_search`, `application_connect`, `application_status`, `tools_discover`, and `tool_execute` workspace tools with provider-neutral records.

- [ ] Write failing tests that feed different application IDs and tool schemas through the same MCP transport double.
- [ ] Run them and confirm failure from missing generic tools.
- [ ] Replace static connector MCP tools with runtime catalog/auth delegation and app-scoped Pipedream MCP discovery/calls.
- [ ] Validate tool IDs, schemas, bounded inputs, annotations, results, and tenant headers.
- [ ] Run focused MCP tests.

### Task 3: Persist dynamic Surveyor selections

**Files:**
- Modify: `cordia/onboarding.py`
- Modify: `cordia/store.py`
- Modify: `app.py`
- Test: `tests/test_survey.py`
- Test: `tests/test_journey.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: public application records from `search_applications`.
- Produces: selected applications stored by opaque `application_id` plus provider-returned public metadata and status.

- [ ] Write failing tests for two catalog fixtures, persistence across refresh/sign-in, sequential setup preparation, missing provider configuration, and no fabricated fallback.
- [ ] Remove all `CONNECTORS` imports and pass runtime catalog records into existing normalization/document compilation.
- [ ] Make onboarding APIs fetch the catalog safely and automatically prepare the first unverified selected app.
- [ ] Run focused Surveyor/journey/application tests.

### Task 4: Provider-neutral agent actions and receipts

**Files:**
- Modify: `cordia/agent.py`
- Modify: `cordia/agent_runs.py`
- Modify: `cordia/store.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_agent_runs.py`

**Interfaces:**
- Consumes: workspace application/tool tools.
- Produces: generic agent actions and durable sanitized execution evidence/receipts.

- [ ] Write failing tests in which two different app/tool fixtures follow the same search/connect/discover/execute path.
- [ ] Replace `connect_service`/`run_operation` static resolution with generic application/tool operations.
- [ ] Preserve full internal evidence while formatting visible agent replies as at most three short bullets.
- [ ] Require existing approval policy before provider-annotated write/destructive calls.
- [ ] Run focused agent tests.

### Task 5: Dynamic catalog UI

**Files:**
- Modify: `static/onboarding.js`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Test: `tests/onboarding.test.cjs`
- Test: `tests/setup.test.cjs`

**Interfaces:**
- Consumes: dynamic `application_catalog`, selected applications, and generic setup cards.
- Produces: responsive logo tiles and truthful unavailable/setup/verified states without app-specific markup.

- [ ] Write failing controller tests using arbitrary app metadata.
- [ ] Render returned logos/names as a responsive tile grid and preserve selection/editor controls.
- [ ] Render catalog-unavailable and setup-required states explicitly; never display a static fallback.
- [ ] Run all JavaScript tests and syntax checks.

### Task 6: Verification and truth update

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/CURRENT_BUILD_TRUTH.md`

**Interfaces:**
- Produces: exact configuration and evidence boundaries.

- [ ] Run full Python and JavaScript suites, compilation, syntax, diff, and source scans.
- [ ] Start a clean local server and browser-test sign-in through dynamic application setup or truthful configuration-required state.
- [ ] Record unit/integration/browser evidence separately from missing provider verification.
- [ ] Document only `PIPEDREAM_CLIENT_ID`, `PIPEDREAM_CLIENT_SECRET`, `PIPEDREAM_PROJECT_ID`, and `PIPEDREAM_ENVIRONMENT` as external platform configuration.
- [ ] Do not deploy.
