# Cordia Short Design

## Product acceptance

A new user can register, complete a short conversational Surveyor, continue in the same Cordia Agent conversation, request Google Drive, complete real OAuth, ask the agent to use Drive, and see the real result in an artifact window.

## Boundaries

- This is an isolated candidate foundation. It does not import from or modify the existing Cordia repository.
- One Python service, one SQLite database, one browser client, and one OpenAI model provider.
- The first live connector is read-only Google Drive. Other providers are not described as connected or available.
- Connector differences live in declarative records. Execution dispatches by authentication protocol and operation definition, never by connector-specific Python module.
- Secrets never enter model input, chat history, workspace memory, artifacts, or logs.
- A connector is `verified` only after a successful provider API response.
- An operation result becomes an artifact only after a successful provider API response.
- Model or provider failures are shown plainly. There are no simulated assistant or connector responses in production.

## Files and responsibilities

- `app.py`: authenticated HTTP routes and page delivery only.
- `cordia/store.py`: accounts, sessions, conversation, workspace memory, encrypted connector credentials, and artifacts.
- `cordia/agent.py`: one OpenAI Responses API call returning one bounded structured action.
- `cordia/connectors.py`: connector dictionary, aliases, setup metadata, operations, and artifact mapping.
- `cordia/connector_runtime.py`: `start_connection`, `finish_connection`, `verify_connection`, and `call_operation`.
- `static/`: one continuous workspace interface with sign-in, Surveyor/chat, generic connector setup, and generic artifact windows.

## User flow

1. Register or sign in with email and password.
2. Surveyor asks for name, role, primary goal, current apps, and communication preference in the left conversation.
3. Answers are saved to a readable `memory.md`; the workspace opens without starting a different product.
4. The Cordia Agent receives the memory and recent conversation. It may return only `speak`, `propose_connector`, or `run_operation`.
5. `propose_connector` resolves aliases through `connectors.py` and renders a generic setup card.
6. Google OAuth redirects the user to Google and returns through a state-bound callback. Tokens are encrypted at rest.
7. The callback verifies access with a real Drive `files.list` request before marking the connection verified.
8. A later `run_operation` request executes only a declared read-only operation and saves the returned file list as a generic table artifact.

## Error and security behavior

- Missing OpenAI configuration: the chat states that the model is unavailable.
- Missing Google OAuth configuration: the setup card states exactly which server configuration is missing.
- OAuth denial or state mismatch: no credentials are stored and the connector remains unverified.
- Provider or model errors: return a bounded error with a retry path; never invent data.
- Passwords use PBKDF2-HMAC-SHA256 with a per-user salt.
- Session cookies are HTTP-only and SameSite=Lax; Secure is enabled outside local development.
- Google scope is `drive.metadata.readonly`; no write or delete operation is present.

## Evidence ladder

1. Unit tests use real application functions and injected HTTP transports; simulated network evidence is labeled test-only.
2. Flask integration tests exercise register, Surveyor completion, setup proposal, OAuth callback, verification, operation, and artifact persistence.
3. A local manual run must use the configured OpenAI key and real Google OAuth credentials.
4. Only after the local journey succeeds may the same revision be deployed and tested publicly.

Official protocol references:

- OpenAI Responses API structured outputs: https://platform.openai.com/docs/api-reference/responses
- Google OAuth 2.0: https://developers.google.com/identity/protocols/oauth2
- Google Drive `files.list`: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list

