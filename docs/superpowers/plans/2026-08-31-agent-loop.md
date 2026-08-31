# Cordia bounded agent loop implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for implementation and review. User approved the agent-layer replacement and requested implementation; live deployment requires separate approval.

**Goal:** Replace the single-action model handler with a bounded LangChain tool loop that receives real results and resumes after verified connector authorization.

**Architecture:** Keep Flask, the existing Store, connector registry/runtime, internal workspace MCP and frontend. LangChain `create_agent` supplies the model/tool loop, with LangGraph SQLite execution checkpoints. Business memory remains in the existing store and Markdown files; checkpoints store execution state only.

**Tech Stack:** Existing Python/Flask/MCP; LangChain, langchain-openai, LangGraph SQLite checkpointer. Pin tested framework versions; no hosted orchestration dependency.

**Spec:** Approved design in the preceding user/assistant exchange, captured below.

## Global constraints / approved design

- Cordia-Short only; preserve existing survey and UI contracts. No Alidora, framework-wide rewrite, new connector providers, autonomous code execution or arbitrary URL tools.
- One authenticated user's tools per run; the model never supplies the user ID or credentials. No credentials, OAuth codes, state tokens or authorization URLs in model messages or execution checkpoints.
- Real tool results must feed back into the model. Missing provider, unsupported connector, missing server setup, denied authorization and failed provider calls are not success.
- Reuse existing verified connector operations and stable artifact identity. Current operations are read-only. Enforce read-only at the agent boundary; adding write operations later requires an explicit approval design.
- Persist a pending connection run and resume only from server-verified status for the same authenticated user/connector. Browser text cannot assert verification. Callback retries must not repeat completion; pause/restart must preserve the user's original request.
- Bound model calls, tool calls, context, output and network timeout; reject concurrent runs for one workspace rather than race checkpoint writes. Expose non-secret run status and measured usage where available.
- Existing API key reuse was approved by the user; never print or commit secrets. Automated external-response fixtures are boundary tests, not real-provider evidence.
- No live deployment this turn without the user's subsequent approval. Report exact tested capabilities and remaining limitations.

## Task 1: Agent runtime, persistence and Flask integration

**Files:** modify `cordia/agent.py`, `app.py`, `requirements.txt`; add focused `cordia/agent_runs.py` if persistence needs isolation; modify/add relevant `tests/test_agent*.py` and route tests. Avoid unrelated files.

**Interfaces:** Keep `AgentUnavailable`, `InvalidAgentAction`, `redact_secrets` imports compatible. Replace the production single-action route with a service that owns start/resume and returns a final assistant response plus run status; preserve `/api/chat` state payload, setup cards and artifacts. Route adjustment retries through the same service without replaying connector side effects. Callback/API-key verification uses the same pending-run continuation; existing post-connect view remains fallback only when no agent run is waiting.

**Concrete execution requirements:**

- [ ] Add failing behavioral tests before implementation. Exercise real Store + real LangChain graph, using a scripted chat model only at the external model boundary and transport fixtures only at external connector HTTP boundaries. Example acceptance: after a scripted `run_operation(openai_api,list_models)` call, the next model request contains a ToolMessage with provider-derived model rows and the Store contains one artifact. Repeating the operation updates that artifact rather than duplicating it.
- [ ] Test setup -> persisted interrupt -> reconstruct service -> verified status -> resume original task; another user cannot resume it and an unverified connection cannot resume it. Repeat callback does not duplicate the run completion. Test denied setup, configuration missing, invalid tools, tool failure, model failure, iteration limits and concurrent same-user submissions.
- [ ] Install pinned framework dependencies after resolving compatible versions locally. Use `create_agent` with explicit typed tools wrapping existing workspace operations. Preserve privacy redaction, add compact bullet-oriented instructions, cap outputs and context; no automatic provider fallback that changes cost or sends data elsewhere.
- [ ] Persist execution checkpoints with safe serialization (no pickle fallback), user/run ownership and pending connector metadata. Keep per-user mutual exclusion across processes using SQLite or equivalent existing durable mechanism; no process-only lock presented as production protection. Ensure locks release on error and have a recovery path after process death.
- [ ] Wire production chat and verified callback continuation end to end. Ensure a paused graph returns a real setup card immediately without claiming connection; authorized tool success reaches the model and produces a concise final answer. Exclude credential forms and OAuth URLs from tool result content passed to the model.
- [ ] Keep onboarding-selected app setup deterministic. If wiring this handoff is needed for this flow, start only supported requested apps, respect already-verified state, and never pretend unsupported apps are connected. Do not redesign the app selection UI in this task.
- [ ] Run focused tests, then `.venv/Scripts/python.exe -m unittest discover -s tests -q`; preserve unrelated changes. Commit only task files and report exact RED/GREEN evidence and limitations.

## Task 2: Real-path verification and release evidence

**Files:** add a focused opt-in `scripts/verify_agent.py` only if needed for repeatable actual-provider verification; update `docs/agent-framework.md` with research, release instructions and evidence. No credentials in fixtures or reports.

- [ ] Review Task 1 diff independently before release.
- [ ] With the approved existing key, run an isolated disposable workspace using actual OpenAI model and actual `/v1/models` operation; verify final answer, saved artifact identity, run limits/usage and second request update. Never use the user's production workspace for test data.
- [ ] Exercise local UI with the implemented backend; verify setup card and short reply rendering. Clearly report Google consent as unverified if client configuration/session is unavailable.
- [ ] Check dependency consistency and complete test suite, diff checks and release state. Prepare GitHub branch/PR using existing delivery conventions without deploying beta. Report capabilities as implemented/verified/unverified and ask for live approval only when release checks justify it.

## Framework research / decision

Reviewed official docs on 2026-08-31:

- LangChain agents: https://docs.langchain.com/oss/python/langchain/agents — standard typed tool loop; chosen to avoid hand-building it.
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts — persistent external-input pause/resume; requires idempotent steps before interrupts.
- LangChain limits: https://docs.langchain.com/oss/python/langchain/middleware/built-in — bound model/tool calls; defaults are not a cost budget.
- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/running_agents/ — viable agent loop/session alternative, not needed in addition to LangChain.
- Pydantic AI: https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/ — viable typed deferred-tool alternative; no reason to introduce a second agent framework.

Expected benefit is less custom loop code and explicit continuation, not an unmeasured latency/cost guarantee. Framework integrations do not supply missing app authorization or operations.
