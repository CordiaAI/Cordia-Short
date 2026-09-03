# Autonomous Artifact Workspace Design

## Product invariant

Surveyor is the workspace specification, not a prelude to another setup wizard. When a user finishes Surveyor, Cordia starts building the workspace immediately. The build pauses only when the user must authorize a connector, enter a provider-issued API key, approve a consequential action, or answer an ambiguity that Cordia cannot resolve safely. Successful authorization resumes the same build automatically; the user never has to type `continue`.

The workspace is a Cordia-owned artifact dashboard. Connector windows are readable projections of provider data, not embedded copies of provider applications. Buttons in those windows invoke reusable Cordia actions through the same agent and connector runtime.

## Scope and delivery order

The beta is delivered as short vertical sprints:

1. Replace raw provider JSON with a small, provider-neutral artifact contract and human-readable renderers.
2. Start one durable workspace-build run automatically after Surveyor completion and resume it after authorization.
3. Add generic artifact actions, refresh, hide, and reorder without application-specific code.
4. Give the agent compact cross-connector awareness and retrieve provider detail on demand.
5. Remove unsupported Live View, selector, model-provider, and arbitrary MCP-registry paths after their callers are gone.

Each sprint must leave the existing real connector path usable. Named applications such as Slack and Google Drive are fixtures and examples only.

## Existing owners that remain

- Flask owns the HTTP/session boundary.
- SQLite owns durable workspace, survey, message, run, connection, and artifact state.
- `ConnectorRuntime` owns the universal Pipedream catalog and customer-scoped authentication.
- `WorkspaceMCPClient` owns provider tool discovery and execution.
- `AgentRuns` owns durable agent execution, authorization interruption, approval interruption, and resume.
- Vanilla JavaScript and CSS own the dashboard UI.

No React, React Flow, Supabase, Redis, queue, worker, vector database, or second connector/agent/artifact framework is added for the beta.

## Artifact contract

Provider results remain structured internally, but the browser receives only a bounded Cordia view:

```json
{
  "type": "summary | metric | list | table",
  "title": "Human-readable title",
  "source": "opaque application id",
  "operation_id": "opaque provider tool id",
  "summary": "Optional one-sentence context",
  "items": [{"label": "Name", "value": "Jordan"}],
  "value": "$18,420.75",
  "columns": ["Name", "Status"],
  "rows": [["Launch plan", "Open"]],
  "actions": [{"id": "send", "label": "Send update", "prompt": "Send this update"}],
  "refresh": {"operation_id": "opaque provider tool id", "inputs": {}},
  "provenance": {"connector_id": "opaque application id", "operation_id": "opaque provider tool id"}
}
```

Only fields relevant to the selected artifact type are present. Nested provider objects are decoded, flattened into short labeled values, or omitted. Raw JSON, authentication context, tokens, scopes, response metadata, opaque IDs, and unbounded provider payloads are never rendered. Tables are bounded to 8 columns and 25 rows; summaries are bounded to 12 items.

Provider execution receipts and user-facing artifacts are separate concepts. A receipt proves what the runtime called and retains sanitized diagnostic evidence. An artifact exists because the workspace builder or the user asked for a useful view; a random provider tool call does not permanently clutter the dashboard.

## Automatic build flow

1. Surveyor completion persists the user's goals, role, working preferences, and selected applications.
2. Cordia creates one system-owned build run. It selects at most five initial artifacts that directly support the Surveyor goals.
3. For each required source, the run checks connection state before discovery or execution.
4. If authorization is required, Cordia opens the provider flow in a popup when the browser permits it and shows a clear in-page fallback link when it does not.
5. The callback verifies provider health, closes or returns from the authorization surface, and resumes the exact waiting run.
6. A failed or skipped connector is marked truthfully. The builder continues with independent sources and leaves one retry control; it does not fabricate an artifact.
7. When initial artifacts are ready, the run completes without requiring another user message.

Reloading the page does not restart Surveyor or duplicate the build. Durable survey completion and build-run state decide what happens next.

## Cross-connector context

Cordia does not preload an entire Drive, Slack history, or other provider corpus into model context. It keeps a compact workspace index containing connected source identities, available tool summaries, artifact summaries, and provenance. When a task needs detail, the agent searches or reads the relevant connected source automatically.

For example, an action from a Drive-derived project artifact can ask Cordia to send an update in a messaging application. The action automatically supplies the artifact's source and visible context. Cordia resolves the messaging connector and retrieves any missing source detail itself. It asks one question only when the recipient, content, or authorization boundary remains genuinely ambiguous.

## Actions and safety

Artifact actions are saved plain-language intents, not provider-specific endpoint mappings. One generic action endpoint loads the stored action, attaches the artifact's bounded context and provenance, and starts `AgentRuns`.

Read-only discovery and refresh may execute automatically. Sending messages, publishing, editing provider data, spending money, deletion, and other consequential external actions use the existing approval interruption unless the user later creates an explicitly scoped automation policy. Secrets never enter model context, artifacts, logs, or browser state.

## Removal boundary

After replacement callers exist, remove these beta paths rather than maintaining empty abstractions:

- unsupported connector Live View UI, dialog, endpoint, and runtime stub;
- application-specific selector endpoint and stub;
- unused connector-backed model-provider/runtime stubs and workspace settings artifact path;
- arbitrary MCP registry installation, credential setup, persistence, and remote-server execution paths;
- duplicate in-process workspace MCP dispatch where direct calls already own the same operation.

The Pipedream application MCP path is retained. Markdown compilation is not removed in the first sprints because it currently participates in Surveyor/operator context; it can be simplified only after the automatic build uses an equivalent compact state source.

## Failure truth and acceptance

The UI distinguishes `building`, `authorization required`, `approval required`, `ready`, `needs attention`, and `unavailable`. Catalog presence is never presented as a live capability. An artifact is `ready` only when it contains provider- or process-derived data.

The beta slice is accepted when:

- completing Surveyor starts a build without a chat message;
- an authorization interruption resumes the same build automatically;
- a nested provider result renders without JSON syntax or secret/auth metadata;
- at least two unrelated application fixtures use the same artifact and action code;
- refresh is read-only and automatic while consequential actions still pause for approval;
- reload preserves Surveyor completion, build progress, connections, and artifacts;
- no production branch checks an application name to decide behavior.

Per the user's current testing instruction, implementation sprints may add focused tests and exact commands but must not execute them. Such sprints are reported as statically reviewed and awaiting user-run verification, not as tested or complete.
