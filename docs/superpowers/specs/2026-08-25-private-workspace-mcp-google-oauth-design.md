# Private Workspace MCP and Google OAuth Design

> **HISTORICAL DESIGN RECORD.** This describes the existing embedded, user-bound MCP slice—not a complete persistent or universal MCP connector system. Current work must start from `docs/CURRENT_BUILD_TRUTH.md` and an approved change contract.

## Goal

Cordia remains one continuous workspace while its connector, memory, and artifact capabilities are exposed through one private MCP server boundary. Google Drive is the first real provider proof. Cordia performs every setup step it can and asks the user only for unavoidable authorization.

## Product Boundary

- The Cordia application is the MCP host/client.
- The Cordia Agent is the model-driven reasoning layer inside that host.
- A user-bound Workspace MCP server exposes tools and resources to Cordia only.
- The MCP endpoint is not public and is not offered to external AI clients in this slice.
- Alidora, a connector marketplace, billing, deployment, desktop packaging, and OAuth providers beyond Google are outside this slice.

## Reuse, Not Replacement

The existing `cordia/connectors.py` registry remains the source of connector metadata. The existing `ConnectorRuntime` remains the only provider execution path. The existing `Store` remains the owner of OAuth state, encrypted credentials, `operator.md`, messages, and artifacts. MCP wraps those components; it does not duplicate them.

## MCP Contract

Each request creates an MCP server bound to the authenticated Cordia user. The model never supplies or selects a `user_id`.

Tools:

- `connectors_search(query: str) -> dict`: return matching supported connector metadata without secrets.
- `connector_start(connector_id: str) -> dict`: create the actual setup card or an explicit missing-configuration result.
- `connector_status(connector_id: str) -> dict`: return the stored connection state.
- `connector_call(connector_id: str, operation_id: str, inputs: dict) -> dict`: execute only a declared operation on a verified connector.
- `artifact_create(payload: dict) -> dict`: persist a validated artifact and return it with its identifier.

Resources:

- `cordia://operator`: the authenticated user's current `operator.md`.
- `cordia://connectors`: supported connectors and the user's connection states, excluding credentials.
- `cordia://artifacts`: saved workspace artifacts, excluding credentials.

The embedded MCP client uses the official Python SDK's in-memory transport. This still performs real MCP tool discovery, schema validation, and invocation without adding a second process or network port. The same server can later use `stdio` in the desktop application or private Streamable HTTP if it becomes a separate deployed service.

## Agent-to-Workspace Flow

The model continues to return one bounded action. The application, not the model, maps that action to an allowed MCP tool:

1. `propose_connector` maps to `connector_start`.
2. `run_operation` maps to `connector_call`.
3. A successful operation result maps to `artifact_create`.
4. Tool errors become explicit user-visible errors; the agent does not fabricate a substitute result.

This keeps the current structured-action guardrail while making the workspace execution boundary MCP-native.

## Automatic Connector Setup Rule

Cordia discovers and prepares everything it can. It pauses only at an unavoidable human boundary:

- OAuth: the user clicks the provider authorization action and approves access on the provider's page.
- API key: the user enters the key into a masked secure setup field, never chat.
- Private remote MCP: the user supplies the private URL or token only when required.

No connector is shown as verified until a real provider request succeeds.

## Google Drive Proof

The initial Google Drive connector requests only `drive.metadata.readonly`. Cordia creates a protected OAuth state, sends the user to Google, exchanges the callback code, encrypts the resulting credentials, and verifies access with the declared Drive file-list operation.

The authorization request includes offline access and incremental authorization. If Google returns a refresh token, Cordia uses it to refresh expired access tokens and preserves it when subsequent token responses omit it. Write scopes are requested later only when an approved skill requires them.

The server operator supplies `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` once. End users never give Cordia their Google password.

## Truth and Security Rules

- No simulated provider response may mark a live connector verified.
- Provider test doubles are valid only inside automated tests and must be identified as such.
- OAuth state is one-time, expiring, and bound to the authenticated user and connector.
- Credentials remain encrypted at rest and never enter model input, messages, `operator.md`, artifacts, logs, or API responses.
- Connector and operation identifiers must resolve through the registry.
- The application reports missing Google configuration, denied consent, token failure, refresh failure, verification failure, and undeclared operations explicitly.

## Acceptance Evidence

Automated evidence must prove MCP tool discovery and invocation through the official client, tenant binding, resource redaction, OAuth URL construction, token exchange, refresh, verification, artifact persistence, and truthful error behavior. Live completion additionally requires a real Google OAuth client and a real Drive verification request; automated doubles do not satisfy that live requirement.
