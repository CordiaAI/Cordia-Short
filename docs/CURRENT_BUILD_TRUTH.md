# Cordia Short Current Build Truth

Last verified: 2026-09-01

Product-code baseline before governance-only changes: `e06172f`

Checked-out branch: `feat/connector-catalog-bootstrap` (the name is historical; the rejected catalog work is not present)

This file is the concise re-entry point for agents. Verify it against Git and runtime evidence whenever work resumes.

## Established in the repository

- Cordia Short is a Flask application with local persistence, a bounded Cordia Agent, connector execution, artifacts, and Surveyor onboarding code.
- `requirements.txt` declares the official Python MCP SDK with `mcp>=2,<3`.
- `cordia/workspace_mcp.py` imports the official SDK's `Client` and `MCPServer`.
- The current Workspace MCP implementation creates a user-bound in-process server and client for a tool call.
- `cordia/connector_runtime.py` remains the existing connector execution owner.
- `cordia/connectors.py` remains the existing connector definition owner at this commit.
- The application imports and uses `WorkspaceMCPClient`; removing it now would break the current application path.

## Not established by the repository

- A persistent Cordia MCP host with one maintained client per MCP server.
- Connection to arbitrary remote Streamable HTTP MCP servers.
- Connection to arbitrary local stdio MCP servers.
- Dynamic external MCP capability and tool discovery as the universal connector path.
- Universal application support.
- A live-verified provider journey on the currently deployed beta for this commit.
- A live deployment containing every local branch change.

Do not describe any of these as implemented or working without new evidence.

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
