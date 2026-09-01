# Cordia Short Agent Rules

These rules apply to every task in this repository. They exist to prevent plausible but unverified architecture, duplicate systems, and false completion claims.

## 1. Re-anchor before reasoning

At the beginning of every task, after context compaction, after a branch/worktree change, and after any material product pivot:

1. Read this file and `docs/CURRENT_BUILD_TRUTH.md`.
2. Inspect `git status`, the current branch, and recent commits.
3. Inspect relevant dependencies, imports, startup wiring, runtime ownership, and tests.
4. Search the repository for an existing implementation before proposing a new component.
5. Re-open the current official documentation for any external protocol, SDK, API, or framework involved.

Do not rely on conversation memory, an old plan, or a previous agent summary when the repository can answer the question directly.

## 2. Authority order

Resolve disagreements in this order:

1. The user's current explicit product decision.
2. Current official protocol, provider, and SDK documentation.
3. The checked-out repository and observed runtime behavior.
4. `docs/CURRENT_BUILD_TRUTH.md`.
5. An approved current change contract.
6. Historical plans and design documents.
7. Model inference.

Historical documents never override current code or an explicit product decision.

## 3. Inventory before architecture

Before designing or implementing a subsystem, identify:

- The file or component that currently owns the responsibility.
- Its callers, dependencies, data store, public interface, and tests.
- Whether an official SDK already supplies the required behavior.
- Whether the proposed work extends, replaces, or duplicates existing ownership.

Do not create a new runtime, registry, catalog, gateway, agent loop, memory system, OAuth manager, MCP boundary, artifact system, or database ownership layer without an approved contract that proves the existing owner cannot be extended safely.

If duplicate ownership is discovered, stop. Prefer deleting or reverting the duplicate over adapting two systems to coexist. Do not delete a currently used component until its verified replacement is ready.

## 4. Approval contract

Architectural work cannot begin while `docs/NEXT_CHANGE_CONTRACT.md` says `NOT APPROVED`.

Before implementation, the contract must contain:

- One observable user outcome.
- Official documentation sources.
- Existing ownership and dependencies.
- Exact files expected to change.
- Components that will be preserved, replaced, or deleted.
- Explicit non-goals.
- A real acceptance test and required evidence.
- The user's approval.

A small bug fix may use the same fields in a short in-chat contract. Approval is still required before editing.

## 5. Evidence and status language

Never use `working`, `complete`, `production-ready`, `live`, or an equivalent claim without naming the evidence level:

- `inspected`: code or configuration was read.
- `unit-tested`: isolated tests passed.
- `integration-tested`: real components communicated across their boundary.
- `provider-verified`: a real provider produced the expected result.
- `browser-verified`: the real user journey succeeded in a browser.
- `live-verified`: the deployed public environment was checked after deployment.

Mocks, fixtures, in-memory transports, deterministic model doubles, and unit tests cannot establish provider, browser, or live capability. A connector is usable only after authentication plus a successful provider-derived operation. A UI card does not establish backend capability.

Preserve `planned`, `implemented`, `verified`, and `unavailable` as distinct states through storage, APIs, UI, documentation, and status reports.

## 6. Subagents and reviews

- Do not delegate implementation before repository inventory and contract approval.
- Use one implementer for a single bounded change.
- Do not parallelize tasks that share state or architectural ownership.
- Give every delegated task the official sources, exact boundary, non-goals, and acceptance evidence.
- Add a reviewer only after the implementer produces the required real integration evidence.
- A reviewer may reject the premise or identify duplicate ownership; review is not limited to code style.

## 7. Minimal process

Use the least machinery that can prove the outcome. Do not add a framework, database, worktree, skill, plan, abstraction, or background service merely because it might be useful later.

If the change grows beyond the approved contract, stop and obtain a new decision. Do not silently expand scope.

## 8. Deletion and correction

Remove rejected or duplicate work when its exact boundary is known and the user authorizes removal. Verify the target before deletion. Record the surviving source of truth afterward.

When a previous claim is disproven, correct the repository truth file and the user-facing status immediately. Do not defend or preserve the disproven claim.
