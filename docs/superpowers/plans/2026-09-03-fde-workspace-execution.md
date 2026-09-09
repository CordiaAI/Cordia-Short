# FDE Workspace Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Surveyor compile the user's source Markdown into one executable `fde.md` and start that workspace build automatically, resuming after connector authorization without a `continue` message.

**Architecture:** Keep the existing deterministic onboarding compiler, SQLite state, `AgentRuns` graph, and universal Pipedream/MCP tools. Rename the user source artifact to `surveyor.md`, make `fde.md` a standalone execution contract derived from `surveyor.md` and `connectors.md`, and add one system-owned `start_workspace_build` entrypoint that uses the existing interrupt/checkpoint/resume path.

**Tech Stack:** Python 3, Flask, SQLite, LangGraph/LangChain already present, Pipedream Connect/MCP already present, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-03-autonomous-artifact-workspace-design.md`

## Global Constraints

- Surveyor completion starts the build; no synthetic user chat message is persisted.
- The build pauses only for authentication, provider-issued credentials, consequential approval, or a genuinely unresolved ambiguity.
- Successful connector verification resumes the exact waiting run automatically.
- Named applications/actions are fixtures only and must never branch production code.
- Keep the existing connector, MCP, agent-run, and artifact owners; add no planner, index, queue, worker, or runtime dependency.
- Provider connection status remains runtime-owned and supersedes a stale Markdown snapshot.
- Do not execute automated tests in this sprint session. Add focused tests and provide one exact user-run command.

---

### Task 1: Compile the source documents into standalone FDE instructions

**Files:**
- Modify: `cordia/onboarding.py`
- Modify: `tests/test_survey.py`

**Interfaces:**
- Produces: `compile_documents(...) -> {"surveyor.md": str, "connectors.md": str, "fde.md": str}`.
- Produces: `fde.md` containing the Surveyor-derived working instructions, connector-derived activities and approval boundaries, desired outcome, smallest slice, and immediate ordered execution sequence.

- [x] Change the compiler contract tests from `operator.md` to `surveyor.md` and assert `fde.md` includes both a Surveyor-derived instruction and a connector-derived desired activity.
- [x] Rename `_render_operator` to `_render_surveyor` and give the document a `# Surveyor profile` title.
- [x] Pass the rendered `surveyor.md` and `connectors.md` into `_render_fde`; embed them as source context inside the standalone build plan.
- [x] Replace “confirm the plan with the user” with immediate execution instructions: begin, connect required sources, gather only required data, build the smallest valuable artifacts, and pause only at the declared boundaries.
- [x] Defer execution of `python -m unittest tests.test_survey -v` to the user.

### Task 2: Make the store treat FDE Markdown as the agent's build control plane

**Files:**
- Modify: `cordia/store.py`
- Modify: `cordia/workspace_mcp.py`
- Modify: `app.py`
- Modify: `static/app.js`
- Modify: `tests/test_journey.py`
- Modify: `tests/test_workspace_mcp.py`

**Interfaces:**
- Produces: `Store.surveyor_markdown(user_id: int) -> str` for the readable profile.
- Produces: `Store.fde_markdown(user_id: int) -> str` for the standalone build assignment.
- Produces: `Store.agent_context(user_id: int) -> str` containing `fde.md` plus current runtime connection status only.

- [x] Update atomic document installation and journey assertions for `surveyor.md`, `connectors.md`, and `fde.md`.
- [x] Replace production reads of `operator.md` with `surveyor.md`; retain the API field name `operator` temporarily because it is presentation copy, not a second source file.
- [x] On first access for an already-completed beta workspace that lacks `surveyor.md`, deterministically recompile all three documents from its saved Surveyor stages and current connection states so the user does not repeat Surveyor.
- [x] Change the private workspace resource from `cordia://operator` to `cordia://surveyor`.
- [x] Make agent context load only `fde.md` plus the runtime-status override; do not concatenate the two source documents a second time.
- [x] Defer focused store/journey/MCP test execution to the user.

### Task 3: Start and resume one FDE build run automatically

**Files:**
- Modify: `cordia/agent.py`
- Modify: `cordia/agent_runs.py`
- Modify: `app.py`
- Modify: `tests/test_agent_runs.py`
- Modify: `tests/test_journey.py`

**Interfaces:**
- Produces: `AgentRuns.start_workspace_build(user_id: int, *, locked: bool = False) -> dict`.
- Consumes: `Store.fde_markdown(user_id)` through the existing system prompt and sends one private build assignment into the existing graph.

- [x] Add an unexecuted journey assertion that onboarding completion invokes the model without posting a user chat message and leaves the run waiting on the first required connector.
- [x] Add `start_workspace_build`, using the existing per-user lock and `_new` execution path. The private assignment says to execute `fde.md` now, never ask for `continue`, and pause only through existing interrupt tools.
- [x] In `/api/onboarding/complete`, remove eager `prepare_selected_setup` and invoke `start_workspace_build(..., locked=True)` after atomic document installation.
- [x] Preserve truthful workspace creation when the model is unavailable: enter the workspace, show the build failure, and do not rerun Surveyor.
- [x] Bootstrap an already-completed workspace once when the new Markdown files are absent, using saved Surveyor data instead of repeating onboarding.
- [x] Leave the existing OAuth callback on `AgentRuns.resume`; this is the exact-run automatic continuation path.
- [x] Open the first provider authorization from the Surveyor completion gesture, retain the setup-card fallback, and return successful authorization to the same workspace automatically.
- [x] Defer execution of focused agent/journey tests to the user.

### Task 4: Static review and handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_BUILD_TRUTH.md`

**Interfaces:**
- Produces: current documentation and one user-run verification command.

- [x] Update the three-document names and state that `fde.md` is the automatic build control plane.
- [x] Record that the implementation received static/diff review only and that user-run verification is pending.
- [x] Run only `git diff --check` and source searches; do not run tests or start a second server.
- [x] Hand off: `python -m unittest tests.test_survey tests.test_journey tests.test_agent_runs tests.test_workspace_mcp -v`.
