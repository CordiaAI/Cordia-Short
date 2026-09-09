# Universal Connector Control Plane Design

## Product invariant

Cordia is a multi-tenant software product. A customer can ask the Cordia Agent to connect an application and perform an available action without Cordia containing application-specific OAuth, endpoint, scope, logo, or action code. Application names in examples and tests are non-normative fixtures, not product scope.

## Architecture

`ConnectorRuntime` remains the sole connector owner. Its static application records are replaced by a Pipedream-backed implementation with five provider-neutral operations: search applications, prepare a customer-scoped connection, read connection status, discover tools, and execute a selected tool. Pipedream provides application metadata, managed authentication, tenant-scoped connected accounts, and MCP tools. `WorkspaceMCPClient` remains the only MCP boundary and delegates its workspace tools to this runtime.

Cordia passes an opaque, stable Cordia user identifier as Pipedream's `external_user_id`. Pipedream developer credentials remain server-only. Cordia never retrieves or exposes end-user provider credentials.

## Public records

An application exposed to the UI contains only `id`, `name`, `logo`, `description`, `categories`, `auth_type`, and a truthful status. A discovered tool contains `id`, `app_id`, `name`, `description`, `input_schema`, and provider annotations. A receipt contains the provider tool identity, sanitized result, timestamp, and status. These records must not contain access tokens, Connect tokens, developer credentials, or provider account credentials.

## User flow

1. Surveyor queries the dynamic application catalog and renders returned application tiles.
2. A selected application ID is persisted with the customer's Surveyor answers.
3. When the workspace is created, Cordia asks `ConnectorRuntime` to prepare setup for the first selected application that is not verified.
4. The runtime creates a short-lived, customer-scoped Pipedream Connect link and pauses for human authorization.
5. After returning to Cordia, the runtime checks Pipedream account health for that customer and application. Only a healthy provider account becomes `verified`.
6. The agent discovers provider tools dynamically. It executes only a tool ID and arguments validated against the discovered schema.
7. Writes and destructive operations pause at Cordia's existing approval boundary. Successful calls save a sanitized receipt and any supported artifact.
8. Additional selected applications follow the same sequence.

## Failure truth

Missing Pipedream configuration produces `needs_configuration`. Catalog, authorization, account-health, MCP discovery, or execution failures remain explicit and cannot create verified state or success receipts. A catalog result is never treated as an installed or connected capability.

## Security

Cordia requests least-privilege Pipedream API scopes, uses server-side short-lived developer tokens, scopes Connect links and MCP calls to the authenticated Cordia user, validates remote application/tool data, bounds payload sizes, redacts secrets, and never sends credentials into model context. Provider annotations inform approval policy but never weaken Cordia's own write/destructive approval requirements.

## UI

Surveyor renders a responsive grid from catalog-returned metadata. Search is server-backed and no static fallback is shown. Selected applications persist by opaque application ID. The workspace shows `setup required`, `authorization required`, `verified`, `needs attention`, or `catalog unavailable` accurately.

## Acceptance

The same parameterized integration tests must pass for at least two unrelated application fixtures and different tool schemas without production-code changes. Browser proof covers sign-in, Surveyor, dynamic application selection, workspace creation, and a truthful setup card. Provider verification requires real Pipedream credentials and a healthy connected account; mocks establish only unit/integration behavior.
