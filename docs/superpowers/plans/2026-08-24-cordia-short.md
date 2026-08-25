# Cordia Short Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest honest Cordia journey from sign-in and Surveyor memory through a real Cordia Agent, verified Google Drive connection, real operation, and visible artifact.

**Architecture:** A single Flask service owns authentication and orchestration. Focused Python modules own persistence, model decisions, declarative connector metadata, and connector execution; one plain browser client renders every state generically.

**Tech Stack:** Python 3.12, Flask, SQLite, Requests, Cryptography, vanilla HTML/CSS/JavaScript, OpenAI Responses API, Google OAuth 2.0 and Drive API.

**Spec:** `docs/superpowers/specs/2026-08-24-cordia-short-design.md`

## Global Constraints

- Do not read from, write to, import, or modify the existing `Cordia` repository.
- No connector-specific Python modules or provider-specific UI components.
- No simulated production responses and no completion claim without an observed result.
- Secrets never enter the model, transcript, memory, artifact, response body, or logs.
- Google Drive is read-only and is the only connector claimed live in this slice.
- No Alidora, billing, installer, marketplace, automation system, or deployment work.

---

### Task 1: Persistent user journey

**Files:** Create `app.py`, `cordia/store.py`, `tests/test_journey.py`, `requirements.txt`, and `README.md`.

**Interfaces:** `Store.register`, `Store.authenticate`, `Store.create_session`, `Store.save_survey_answer`, `Store.memory_markdown`, `Store.add_message`, `Store.save_artifact`.

- [ ] Write failing tests for password authentication, session ownership, ordered survey answers, readable memory, continuous messages, and artifact persistence.
- [ ] Run `python -m unittest tests.test_journey -v` and confirm failures are missing behavior.
- [ ] Implement the minimum SQLite store and authenticated JSON routes.
- [ ] Re-run the focused tests and the complete suite.

### Task 2: Real bounded Cordia Agent

**Files:** Create `cordia/agent.py` and `tests/test_agent.py`; modify `app.py`.

**Interfaces:** `Agent.respond(memory: str, messages: list[dict]) -> dict` returns exactly one action: `speak`, `propose_connector`, or `run_operation`.

- [ ] Write failing tests for schema validation, plain model failure, secret exclusion, and Google Drive intent resolution.
- [ ] Confirm the tests fail before implementation.
- [ ] Implement one OpenAI Responses API request using strict structured output and `gpt-5-mini` by default.
- [ ] Make the authenticated chat route persist both sides of the same conversation and reject unknown actions.
- [ ] Re-run focused and complete tests.

### Task 3: Universal connector registry and runtime

**Files:** Create `cordia/connectors.py`, `cordia/connector_runtime.py`, and `tests/test_connectors.py`; modify `cordia/store.py` and `app.py`.

**Interfaces:** `resolve_connector`, `start_connection`, `finish_connection`, `verify_connection`, and `call_operation`.

- [ ] Write failing tests proving aliases resolve, malformed records fail, OAuth state is owner-bound and single-use, tokens are encrypted, verification requires a real provider response, and declared operations create no invented fields.
- [ ] Confirm the tests fail before implementation.
- [ ] Add the declarative Google Drive record and protocol-driven OAuth runtime.
- [ ] Add authenticated start and callback routes; verify with Drive `files.list` before recording `verified`.
- [ ] Re-run focused and complete tests.

### Task 4: One continuous workspace UI

**Files:** Create `static/index.html`, `static/styles.css`, `static/app.js`, and `tests/test_ui_contract.py`.

**Interfaces:** Generic API states are `signed_out`, `survey`, and `workspace`; cards use `type`, `title`, `status`, `fields`, and `action_url`; artifacts use `type`, `title`, `columns`, `rows`, and `source`.

- [ ] Write failing contract tests for the sign-in panel, persistent left conversation, generic setup card, generic artifact renderer, and explicit unavailable/error states.
- [ ] Confirm the tests fail before implementation.
- [ ] Implement the single-page Cordia workspace in the established ivory, sage, and olive visual language.
- [ ] Re-run focused and complete tests.

### Task 5: Honest end-to-end verification

**Files:** Modify `README.md`; create `tests/test_application_path.py`.

**Interfaces:** The application path is register → Surveyor → memory → agent proposal → OAuth completion → provider verification → operation → persisted artifact.

- [ ] Write the application-path test against the real Flask routes with injected model/provider transports; label it simulated-network integration evidence.
- [ ] Run the entire suite from a clean database.
- [ ] Start the local application and make one real OpenAI request.
- [ ] If Google OAuth credentials are configured, complete real OAuth and confirm a real Drive table artifact. Otherwise report that exact external credential blocker without claiming the connector works.
- [ ] Record observed commands and results in `README.md`; do not deploy in this plan.

