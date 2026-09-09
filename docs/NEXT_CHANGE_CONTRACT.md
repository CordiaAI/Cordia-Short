# Cordia Short Next Change Contract

Status: **APPROVED**

The previous provider-specific `CONNECTORS` extension was rejected. This replacement removes the static application allowlist and uses Pipedream Connect as the first dynamic catalog, managed-auth, and tool provider behind Cordia's existing runtime boundary.

## Observable user outcome

Any Cordia customer can name or select an application returned by the external catalog, authorize it for their own account, and ask the Cordia Agent to discover and execute that application's provider-supplied tools. Named applications and actions in tests are examples only; no application-specific behavior is implemented in Cordia code.

## Official sources

- Pipedream Connect overview: https://pipedream.com/docs/connect
- App discovery: https://pipedream.com/docs/connect/app-discovery
- Managed authentication: https://pipedream.com/docs/connect/managed-auth/quickstart
- Connect token API: https://pipedream.com/docs/connect/api-reference/create-connect-token
- Pipedream MCP for developers: https://pipedream.com/docs/connect/mcp/developers
- MCP tools and managed credentials: https://pipedream.com/docs/connect/mcp

## Existing ownership and dependencies

- `cordia/connector_runtime.py` remains the only application catalog, connection, and execution owner; its static internals will be replaced, not duplicated.
- `cordia/workspace_mcp.py` remains the only MCP client/server boundary.
- `cordia/onboarding.py` and persisted Surveyor answers own selected-application state.
- `app.py` owns authenticated workspace-state assembly, automatic FDE-build startup, and connector-return resumption.
- `cordia/agent_runs.py` owns bounded agent runs, full evidence, retry context, and persisted visible responses.
- `static/onboarding.js`, `static/app.js`, and `static/styles.css` own the existing Surveyor and workspace presentation.

## Files expected to change

- `app.py`
- `cordia/agent_runs.py`
- `cordia/connector_runtime.py`
- `cordia/connectors.py`
- `cordia/workspace_mcp.py`
- `cordia/onboarding.py`
- `static/app.js`
- `static/onboarding.js`
- `static/styles.css`
- Connector, agent-run, application, and onboarding tests under `tests/`
- `docs/superpowers/specs/2026-09-02-universal-connector-control-plane-design.md`
- `docs/superpowers/plans/2026-09-02-universal-connector-control-plane.md`
- This contract and `docs/CURRENT_BUILD_TRUTH.md`

## Preserve

- The single existing `ConnectorRuntime`, Workspace MCP boundary, setup-card flow, agent loop, and artifact system.
- Cordia user identity as Pipedream `external_user_id` for strict per-customer isolation.
- Provider account health or a successful provider-derived operation as the only transition to `verified`.
- Full internal run evidence and full original assistant text for retries.

## Replace or delete

- Replace the `CONNECTORS` static allowlist, provider OAuth endpoints, provider scopes, provider operation maps, and checked-in provider logos.
- Replace named `connect_service` and `run_operation` assumptions with application and tool discovery through the existing runtime and MCP boundary.
- Delete the rejected unfinished Slack-specific edits and their tests.

## Non-goals

- No deployment.
- No app-specific OAuth, scopes, endpoints, tool names, logos, or execution branches in Cordia code.
- No promise that every catalog application has every possible capability.
- No second connector framework, new database, or background service.
- No storage or collection of user passwords.

## Real acceptance test

Using two different catalog fixtures with different application IDs and tool schemas, prove the same search, selection, setup, verified-account, tool-discovery, approval, execution, and receipt path without changing production code. Then run the local browser from sign-in through Surveyor application selection and workspace setup. Without Pipedream credentials, the browser must truthfully report platform configuration is required rather than showing a fabricated catalog or connection.

## Required evidence

- Failing tests observed before production implementation.
- Focused connector, agent-run, application, and browser-contract tests pass.
- Full Python and JavaScript suites pass.
- Python compilation and JavaScript syntax checks pass.
- Browser output captures the local generic journey and has no console errors.
- Source scan confirms no named application, provider OAuth endpoint, scope, operation, or logo remains in the runtime path.

## User approval

Approved by the user on 2026-09-02 after explicitly clarifying that Cordia is a multi-tenant software startup, all named applications/actions are examples rather than static requirements, and the connector path must be universal. The user then approved Pipedream Connect as the initial connector substrate and directed implementation to continue.
