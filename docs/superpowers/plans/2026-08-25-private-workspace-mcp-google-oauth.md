# Private Workspace MCP and Google OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route Cordia's existing connector and artifact behavior through a private, user-bound MCP server and complete the refreshable Google OAuth path.

**Architecture:** The official MCP Python SDK provides an embedded `MCPServer` and `Client`. A thin user-bound wrapper delegates to the existing connector registry, `ConnectorRuntime`, and `Store`; Flask remains the HTTP/UI shell and maps the model's bounded actions to MCP tools.

**Tech Stack:** Python 3.12, Flask 3.1, MCP Python SDK 2.x, SQLite, cryptography, unittest

**Spec:** `docs/superpowers/specs/2026-08-25-private-workspace-mcp-google-oauth-design.md`

## Global Constraints

- Keep one connector registry and one connector runtime; do not create provider-specific runtime modules.
- Bind each MCP server to the authenticated user; MCP tool arguments never accept `user_id`.
- Keep credentials outside model input, messages, resources, artifacts, logs, and API responses.
- Only real provider verification can produce live `verified` state.
- Google Drive remains metadata-read-only in this slice.
- No public MCP endpoint, Alidora, marketplace, billing, deployment, or desktop packaging work belongs in this plan.

---

### Task 1: User-Bound Workspace MCP Contract

**Files:**
- Create: `cordia/workspace_mcp.py`
- Create: `tests/test_workspace_mcp.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `ConnectorRuntime.start_connection`, `ConnectorRuntime.call_operation`, `Store.operator_markdown`, `Store.connection_status`, `Store.artifacts`, and `Store.save_artifact`.
- Produces: `create_workspace_server(user_id: int, runtime: ConnectorRuntime, store: Store) -> MCPServer` and `WorkspaceMCPClient.call(user_id: int, tool_name: str, arguments: dict) -> dict`.

- [ ] **Step 1: Add the MCP dependency and write failing MCP contract tests**

Add `mcp>=2,<3` to `requirements.txt`. In `tests/test_workspace_mcp.py`, create a real temporary `Store`, a real `ConnectorRuntime` with a provider transport double only at the external HTTP boundary, and assert through `Client(server)` that:

```python
tools = await client.list_tools()
self.assertEqual(
    {"connectors_search", "connector_start", "connector_status", "connector_call", "artifact_create"},
    {tool.name for tool in tools.tools},
)
result = await client.call_tool("connectors_search", {"query": "drive"})
self.assertEqual("google_drive", result.structured_content["connectors"][0]["id"])
```

Also prove `cordia://operator`, `cordia://connectors`, and `cordia://artifacts` return the bound user's data and never include stored credential values.

- [ ] **Step 2: Run the new tests and verify the missing module fails**

Run: `python -m unittest tests.test_workspace_mcp -v`

Expected: FAIL because `cordia.workspace_mcp` does not exist.

- [ ] **Step 3: Implement the minimal MCP server and embedded client**

Create one server factory with the five tools and three resources. Every tool closes over `user_id`; none accepts it as a parameter. `WorkspaceMCPClient.call` creates the bound server, enters `Client(server)`, invokes one tool, rejects `is_error`, and returns `structured_content`.

- [ ] **Step 4: Run the MCP contract tests and the complete suite**

Run: `python -m unittest tests.test_workspace_mcp -v`

Expected: PASS.

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS with no errors.

- [ ] **Step 5: Commit the MCP boundary**

```bash
git add requirements.txt cordia/workspace_mcp.py tests/test_workspace_mcp.py
git commit -m "feat: add private workspace MCP boundary"
```

### Task 2: Route Cordia Actions Through MCP

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_journey.py`

**Interfaces:**
- Consumes: `WorkspaceMCPClient.call(user_id, tool_name, arguments)` from Task 1 and existing model actions.
- Produces: Flask action handling that maps `propose_connector` to `connector_start`, maps `run_operation` to `connector_call`, then persists the returned artifact through `artifact_create`.

- [ ] **Step 1: Write failing journey tests against the MCP client boundary**

Inject a recording workspace client into `create_app`. Assert a connector request invokes only:

```python
(user_id, "connector_start", {"connector_id": "google_drive"})
```

Assert an operation invokes `connector_call` followed by `artifact_create`, and the artifact returned by `artifact_create` appears in `/api/state`. Assert an MCP error returns `502` with an explicit error and does not create an artifact.

- [ ] **Step 2: Run the focused application tests and verify direct-runtime behavior fails the new contract**

Run: `python -m unittest tests.test_app tests.test_journey -v`

Expected: FAIL because `create_app` does not accept or call the workspace MCP client.

- [ ] **Step 3: Add the minimal action-to-tool mapping**

Construct `WorkspaceMCPClient(runtime, store)` by default. Replace direct calls to `runtime.start_connection`, `runtime.call_operation`, and `store.save_artifact` in both normal chat and adjusted-response retry paths with the MCP calls defined above. Leave the OAuth callback on `ConnectorRuntime.finish_connection` because it is an HTTP callback, not a model-controlled workspace action.

- [ ] **Step 4: Run focused and complete tests**

Run: `python -m unittest tests.test_app tests.test_journey -v`

Expected: PASS.

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS with no errors.

- [ ] **Step 5: Commit the host integration**

```bash
git add app.py tests/test_app.py tests/test_journey.py
git commit -m "feat: route workspace actions through MCP"
```

### Task 3: Refreshable Google OAuth and End-to-End Evidence

**Files:**
- Modify: `cordia/connector_runtime.py`
- Modify: `tests/test_connectors.py`
- Modify: `tests/test_journey.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Google OAuth metadata from `cordia/connectors.py`, encrypted connection methods on `Store`, and the MCP route from Tasks 1-2.
- Produces: automatic refresh of expired Google access tokens, incremental authorization parameters, and a complete provider-derived artifact journey through MCP.

- [ ] **Step 1: Write failing OAuth refresh and journey tests**

Add tests that save an expired access token plus refresh token, call `ConnectorRuntime.call_operation`, and assert the external transport receives a refresh-token exchange before the Drive request. Assert the new credentials preserve the existing refresh token when Google's refresh response omits it. Add a journey test that uses the real MCP wrapper and real runtime with only external Google HTTP responses doubled, then verifies setup, callback, verified status, operation, artifact persistence, and absence of credentials in the returned state.

- [ ] **Step 2: Run focused tests and verify refresh is missing**

Run: `python -m unittest tests.test_connectors tests.test_journey -v`

Expected: FAIL because expired access tokens are currently used without refresh.

- [ ] **Step 3: Implement minimal refresh and incremental authorization behavior**

Before a provider operation, refresh when `expires_at` is due. Send `grant_type=refresh_token`, `refresh_token`, `client_id`, and `client_secret` to the declared token URL. Store the returned access token, expiry, scope, token type, and the previous refresh token when no replacement is returned. Add `include_granted_scopes=true` to the authorization URL.

- [ ] **Step 4: Update operating instructions and run full verification**

Document the private MCP boundary, exact local and live callback URLs, Google Cloud setup, the server-only OAuth client credentials, and the distinction between automated provider doubles and a live Google proof.

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS with no errors.

Run: `python -m compileall -q app.py cordia tests`

Expected: exit code 0.

- [ ] **Step 5: Commit the Google OAuth completion**

```bash
git add cordia/connector_runtime.py tests/test_connectors.py tests/test_journey.py README.md
git commit -m "feat: complete refreshable Google OAuth flow"
```

### Task 4: Review the Slice Against Its Truth Contract

**Files:**
- Modify only if verification finds a defect.

**Interfaces:**
- Consumes: the complete implementation and design specification.
- Produces: evidence-backed status separating automated, local-live, and real-Google-live results.

- [ ] **Step 1: Inspect the complete diff and run mutation-oriented checks**

Confirm tests would fail if tenant binding were removed, an undeclared tool were called, connector verification were skipped, credentials leaked into resources, refresh were skipped, or artifact persistence were bypassed.

- [ ] **Step 2: Run the fresh final verification commands**

Run: `python -m unittest discover -s tests -v`

Run: `python -m compileall -q app.py cordia tests`

Run: `git diff --check master...HEAD`

Expected: tests PASS, compilation exits 0, and diff check exits 0.

- [ ] **Step 3: Record the exact remaining live prerequisite**

If real Google credentials are not configured, report the slice as implementation-complete but live-Google-unverified. Do not describe Google Drive as live until a real account completes consent and a real Drive file-list response produces the artifact.
