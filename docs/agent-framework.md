# Cordia agent framework

## Decision

Use LangChain's `create_agent`, backed by LangGraph, inside the existing Cordia-Short application. Do not introduce a second application, agent fleet, cloud orchestration account or a second business-memory store.

| Framework researched | Relevant capability | Decision for this slice |
| --- | --- | --- |
| [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents) | Typed model/tool loop with tool results fed back into the model | Selected; replace the existing single-action production handler. |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/interrupts) | Checkpoint and resume execution while waiting for outside input | Use underneath the standard agent, with local durable checkpoints. |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/running_agents/) | Agent loop, sessions, streaming and human-in-the-loop support | Viable alternative, not an additional dependency alongside LangChain. |
| [Pydantic AI](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) | Typed tools and deferred calls for approval/external completion | Viable alternative; no demonstrated need to replace the approved approach. |

Sources reviewed 2026-08-31. This is a fit assessment, not a benchmark claiming one framework is universally faster.

## Ownership boundaries

- Cordia owns authentication, survey answers, `operator.md`, `connectors.md`, `fde.md`, permissions, connector verification and artifact identity.
- The agent chooses among declared tools and responds using actual results. It cannot set the user identity, provide credentials, invent a connector or execute arbitrary code/URLs.
- LangGraph checkpoints own temporary execution progress, not authoritative connector status or the user's long-term profile.
- The existing MCP/runtime boundary remains the only path for connector operations. Framework integrations do not implement missing provider authorization.
- Selecting an application during onboarding requests setup; it does not authorize data access, writes, or establish a verified connection.

## Efficiency and safety

Use deterministic code for known transitions such as survey completion and verified callbacks. Use the model for interpreting user requests and deciding among allowed tools. Bound model calls, tool calls, context and output instead of allowing an unconstrained planning loop. Never enable automatic model fallback that sends data elsewhere or changes cost unexpectedly.

Only read-only operations belong in this agent slice. Future write operations require an explicit approval and idempotency contract before exposure. OAuth state/credentials remain outside model context and checkpoints. A callback may resume only its authenticated user's matching pending connector run.

Native framework streaming is available, but the existing browser response transport must be explicitly wired before claiming token-by-token UI streaming. Keeping the current working indicator is not streaming model output.

Execution checkpoints can contain private conversation text and provider results even though authentication secrets are excluded. Protect and back up their storage with the same service-account restrictions as the workspace database; do not publish it, commit it, or enable third-party tracing without an explicit data-sharing decision. SQLite targets the current single-VPS deployment, not an untested multi-host deployment.

Per-run limits are not a subscription quota, account-wide spending cap, or public-abuse protection. This slice does not establish unrestricted public-launch readiness. A model can still produce incorrect prose; connection status and artifact changes must remain grounded in backend results rather than assistant claims.

## Repeatable real-provider verification

From the worktree, run with a private, previously authorized environment file:

```powershell
.venv/Scripts/python.exe scripts/verify_agent.py --live --env-file ../../.env.local
```

This is an opt-in billable check using a disposable local database and actual OpenAI requests. It exercises registration, survey/discovery, the three memory files, agent-requested setup, app reconstruction, API-key verification, continuation, provider-derived artifact creation and refresh of the same artifact. It prints sanitized results and deletes only its own temporary workspace on exit.

`--serve` instead starts a disposable, loopback-only browser QA workspace on port 5059. The synthetic QA account is `agent-proof@example.invalid` with password `local-qa-only-password`; it must never be installed or seeded into a deployed database. This mode does not run the full provider proof by itself.

Automated scripted-model/HTTP-fixture tests establish control-flow and failure-boundary behavior. They do not establish real OAuth consent or live provider availability. Record actual executed evidence below before requesting deployment.

## Release status

PR #9 was merged as `cbbd4f8` and deployed to beta on 2026-08-31. Dependencies installed successfully; 183 tests passed as the service user after fixing access to the existing Node test runner. Public health returned `ok: true`, and the public onboarding script hash matched the checkout. The signed-in browser loaded the new assessment. These checks do not establish a complete live user journey.

The deployment's real GPT-5-mini verifier failed twice: the model checked connection status, asked permission again to prepare already-requested setup, and finished without a durable authorization wait. The narrow follow-up clarifies that an explicit connection request authorizes **preparing** the secure card, not granting account access. Backend authorization gates remain unchanged. This is model guidance, not a deterministic guarantee.

After that correction, the unchanged real-provider verifier passed locally with GPT-5-mini and GPT-4.1-mini: secure setup, verification, durable continuation and refresh of the same 124-row artifact. First-flow observations were 23.94s and 9.94s. All 183 automated tests also passed. The correction still requires review, CI and deployment verification; do not treat these local results as server evidence. Original pre-deployment evidence follows.

Executed 2026-08-31:

- Final full suite after review fixes: **183 Python tests passed in 39.693 seconds**, including the Node controller suites (20 onboarding cases plus two setup-cancel cases). External model/HTTP boundaries in these tests are fixtures. Intentional provider-failure and disk-full tests emitted expected tracebacks.
- Actual GPT-4.1-mini and GPT-5-mini model calls completed the registered-user → survey → Markdown memory → secure setup → app reconstruction → real API verification → original-run continuation → 124-row model artifact → stable-identity refresh path. Initial measured setup/continuation times were 10.52s and 28.84s respectively; these are individual observations, not benchmarks or service guarantees.
- A further real GPT-4.1-mini run selected the user's connected model via `/api/connectors/select`, then completed a two-model-call / one-tool-call refresh with `source: connector`. Reported final-turn usage was 3502 input and 75 output tokens. The model catalog was re-read from the actual provider, not fabricated.
- Independent review tightened the verifier: saved workspace state alone cannot prove a new refresh; the current run must also return a nonempty artifact with the expected ID. Both models passed that stronger check with user-selected provider keys. Final observations: GPT-4.1-mini 7.34s setup/continuation, 3586/67 input/output tokens on refresh; GPT-5-mini 19.94s, 3782/851 tokens. Each refresh used two model calls and one tool, returning the same 124-row artifact.
- Review also corrected loss of failure evidence during response revision and a hidden pending run after a model change during authorization. Focused failing regressions preceded the fixes; independent re-review accepted all three corrections.
- In the local browser, a fresh QA account completed all four assessment parts, snapshot, workflow discovery, review and workspace creation. The selected OpenAI connection's credential card appeared automatically, before any chat request.
- Browser chat: Enter displayed the user's message and infinity working indicator immediately; the real model produced the secure setup pause. Cancel ended the pending task, removed its form, and allowed a subsequent real-model request. The subsequent reply was two short bullets. This is final-answer transport, not token streaming.
- Mouse-based survey completion worked. Browser automation's Enter/Space on survey choice buttons did not establish native activation; that keyboard check remains unresolved and is not counted as passed. Composer Enter did pass. No speculative keyboard patch was added.
- Python compilation, JavaScript syntax, dependency consistency and whitespace checks passed. Final PR checks/review must also pass before merge.

Not established by this slice: fresh Google consent against the new graph; every selectable OpenAI model; arbitrary applications, remote MCP servers or OpenAPI imports; skill authoring, write operations, general web automation, installer, account quotas/billing, token streaming, or public-launch abuse protection. Current registered operations remain Google Drive metadata listing and OpenAI model listing. Google OAuth is implemented and fixture-tested; its real consent path must be rechecked on the deployment host.

### Live deployment gate

After approval: verify the target is **beta Cordia-Short**, preserve the current server commit/configuration/data, install the pinned requirements in its existing service environment, ensure the service account can write the database directory (including checkpoints/locks), restart, and check the actual public release and authenticated chat. Verify proxy/worker timeouts against multi-step requests; do not assume a local Flask development server is suitable for production. Retest Google callback and failure handling there. Keep the prior code/environment available for rollback; do not remove the user's data. The new runtime adds tables/files but does not replace the existing account/connector store.

Preflight evidence on 2026-08-31:

- Baseline Python suite: 154 passed in 23.689 seconds. The deliberate disk-full test logged its expected traceback; no actual disk-full condition was observed.
- Existing onboarding controller suite: 20 passed. This uses a DOM boundary double, not a browser.
- A real authenticated OpenAI `/v1/models` request returned 124 models and included `gpt-4.1-mini` and `gpt-5-mini`. This verifies API-key access, not chat-model invocation or the new agent loop.
- The installed LangChain/OpenAI/LangGraph dependency set passes `pip check`. Exact tested pins are recorded in `requirements.txt` with the implementation.
- Existing draft PR #9 is open against `master`; it is not a live release.
