# Cordia Short Current Build Truth

Last verified: 2026-09-06

Current FDE implementation review: 2026-09-06. The user completed a real local browser/provider pass through authorization, approval, and Slack delivery. The newest outcome-only reply and survey-action UI changes in the working tree have not been executed because the user reserved runtime testing for their own browser pass.

Product-code baseline before governance-only changes: `e06172f`

Checked-out branch: `feat/connector-catalog-bootstrap` with an uncommitted approved universal-connector rewrite.

This file is the concise re-entry point for agents. Verify it against Git and runtime evidence whenever work resumes.

## Established in the repository

- Cordia Short is a Flask application with local persistence, a bounded Cordia Agent, connector execution, artifacts, and Surveyor onboarding code.
- `requirements.txt` declares the official Python MCP SDK with `mcp>=2,<3`.
- `cordia/workspace_mcp.py` imports the official SDK's `Client` and `MCPServer`.
- The current Workspace MCP implementation creates a user-bound in-process server and client for a tool call.
- `cordia/connector_runtime.py` is the only connector control-plane owner. It obtains a developer token, searches the external application catalog, creates customer-scoped managed-auth links, verifies connected accounts, and produces per-user/per-app remote MCP configuration.
- `cordia/connectors.py` contains provider-record normalization only. It contains no application records, OAuth endpoints, scopes, logos, or operation mappings.
- `cordia/workspace_mcp.py` remains the only MCP boundary. It discovers and invokes each connected application's provider-supplied tools through the remote MCP endpoint.
- `cordia/agent_runs.py` searches applications and discovers tools at runtime. Read-only tools may execute directly; other tools pause for explicit user approval before execution.
- Surveyor reads application identities and logos from the runtime catalog. If provider configuration is missing, the UI reports `needs_configuration` and shows no simulated fallback catalog.
- The configured Pipedream OAuth client authenticated successfully against the live provider on 2026-09-02. Cordia fetched applications from the live universal catalog and created a provider-hosted end-user authorization link for a catalog-selected application.
- On 2026-09-03, the user completed the real local browser path for a consequential Slack action: Cordia discovered provider tools, paused for approval, invoked the provider after approval, and the requested `test` message appeared in the intended Slack direct message. Cordia also saved the provider result and permalink. This verifies one real application action through the universal path; it does not prove every catalog application or tool.
- The 2026-09-02 local suites passed: 118 Python tests and 23 Node onboarding/setup tests.
- The application imports and uses `WorkspaceMCPClient`; removing it now would break the current application path.

## Implemented in the current unverified working tree

- Surveyor completion atomically compiles `surveyor.md` and `connectors.md` into one standalone `fde.md` workspace-build assignment.
- The existing bounded `AgentRuns` graph starts that FDE assignment automatically; it does not save a fake user chat message or wait for the user to type `continue`.
- The existing authorization interruption and checkpoint resume the same FDE run after provider verification.
- Surveyor completion attempts to open the provider authorization in a popup and retains the setup-card link when a browser blocks it.
- Existing completed Surveyor workspaces are deterministically recompiled and start the FDE build on first access if they do not yet contain the new Markdown contract; the user is not sent through Surveyor again.
- The workspace presentation is now a compact square artifact grid beside Cordia chat. The separate selected-applications summary, large workspace heading, operator-profile card, and unsupported Live View presentation have been removed from the main workspace.
- Artifact windows resolve application names and logos from the same runtime-selected catalog metadata, render a bounded human-facing data subset, expose survey-requested or artifact-provided actions, and provide generic refresh, hide, and app-scoped prompt controls without named-application branches.
- Browser-native voice dictation is progressively attached to Surveyor text fields, Cordia chat, and artifact prompts. Cordia receives and persists the resulting text only; it adds no audio upload or audio storage path.
- App-scoped artifact prompts attach a bounded, user-owned artifact context to the model request without replacing the visible user-authored chat message.
- Consequential-action cards now derive plain-language application, action, confirmation, and safe input details from runtime catalog/tool metadata. Provider descriptions, schemas, and opaque identifiers remain internal rather than becoming approval copy.
- Consecutive duplicate assistant messages are collapsed in presentation, approval pauses no longer add chat-history noise, successful provider retries become the final action outcome, and key/value provider results are projected as compact human-facing receipts.
- Completed approved actions now produce a deterministic one-sentence outcome without message contents, links, provider receipts, or evidence; other model replies are bounded to their first useful sentence.
- Selected-application activity prose is deterministically converted into at most five short action starters. The same survey-derived actions appear at the top of every matching connector artifact, and a verified connector receives a lightweight action window even before a provider data artifact exists.
- Clicking a survey-derived action now sends only its application and action identifiers; the server resolves them against that user's selected Surveyor applications before adding a trusted fresh-action instruction. An underspecified action must collect only its missing inputs and cannot reuse recipients, content, titles, or tool arguments from an earlier completed request.

## Not established by the repository

- A persistent Cordia MCP host with one maintained client per MCP server.
- Connection to arbitrary local stdio MCP servers.
- Proof that every provider-listed application exposes usable tools; catalog presence alone is not a live adapter guarantee.
- A live-verified provider journey on the currently deployed beta for this commit.
- A live deployment containing every local branch change.
- Runtime or browser proof for the 2026-09-03 FDE compilation, automatic-start, popup, and resume changes.
- The final generic human-facing artifact projection layer; nested provider payloads can still require additional normalization.
- Browser proof for microphone permissions, dictation behavior, the artifact-scoped prompt flow, the newest compact approval/receipt presentation, outcome-only replies, survey-derived connector actions, and fresh-action missing-detail collection. The user-observed browser pass did establish the square Slack artifact layout before these readability changes.

Do not describe any of these as implemented or working without new evidence.

The universal control plane is implemented, fixture-verified locally, and provider/browser-verified for provider authentication, catalog retrieval, end-user authorization, and one approved Slack message action. Deployment and behavior across the full provider catalog remain unverified.

## Rejected and removed

The 2026-08-31 duplicate connector-catalog/Supabase sprint was rejected and removed. Its four commits, unfinished edits, migration, seed, tests, ignored review artifacts, and abandoned SQLite stash are not current architecture or evidence.

This rejection does not prohibit a future approved use of Supabase. It prohibits treating that removed duplicate implementation as accepted work.

## Documentation authority

- `AGENTS.md` controls agent behavior in this repository.
- This file records current verified build truth.
- `docs/NEXT_CHANGE_CONTRACT.md` records the only approved next architectural change.
- Files under `docs/superpowers/` are historical design and implementation records unless a current contract explicitly reactivates one.
- Official MCP specification and Python SDK documentation control MCP protocol and SDK behavior.

## Required update rule

Update this file in the same reviewed change whenever architectural ownership, verified capability, rejected work, deployment truth, or the active commit boundary changes.
