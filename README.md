# Cordia Short

Cordia Short is an isolated, clean-room candidate foundation for Cordia. It does not import from or modify the existing Cordia repository.

The product path is intentionally narrow:

```text
Sign in -> Surveyor -> operator.md -> same Cordia Agent conversation
        -> connector setup card -> verified provider operation -> artifact window
```

## Observed status on 2026-08-26

- Registration, password authentication, sessions, Surveyor, readable `operator.md`, continuous chat, generic setup cards, generic artifact windows, and sign-out are implemented.
- Every Cordia Agent response offers **Helpful** and **Adjust response** controls. A selected adjustment moves one operator preference toward `-1` or `1`, records evidence against that response, updates `operator.md`, and retries the original request.
- A real OpenAI request through `cordia.agent.Agent` returned a valid `propose_connector` action for Google Drive.
- The complete browser path was exercised from sign-in through all five Surveyor answers and the real agent request. The browser console had no errors.
- The generic setup card persisted after a full page refresh; this was caught and fixed during browser verification.
- Cordia now acts as the MCP host/client for a private, authenticated workspace server. Connector discovery, setup, status, operations, artifacts, `operator.md`, connector state, and artifacts are exposed through that user-bound MCP contract.
- The application uses the official MCP Python SDK's in-memory transport. Tool discovery, schema validation, and invocation still pass through MCP without adding another service or public endpoint.
- Model actions no longer call connector execution or artifact storage directly. The host maps bounded actions to MCP tools and returns explicit failures without creating substitute artifacts.
- Expired Google access tokens are refreshed automatically when Google issued a refresh token. A failed or unavailable refresh is reported rather than hidden.
- Google Drive completed real OAuth on `beta.cordiacode.com` with only `drive.metadata.readonly`; a real `files.list` response produced a persisted DashView table artifact.
- The same runtime now supports declarative API-key connectors. The secure setup form posts credentials directly to the backend, verifies them against the declared provider endpoint, encrypts successful credentials, and discards rejected credentials.
- `openai_api` is the first API-key catalog proof and exposes the read-only `list_models` operation. A verified user can select a provider-returned model from its artifact; Cordia revalidates the choice before saving it and uses that user's encrypted key and selected model for later agent turns.
- The workspace status identifies the active provider and model from sanitized runtime state, so users can see whether Cordia is using the managed default or their selected connector without exposing credentials.
- The automated suite contains 57 passing tests at this commit.

## Run locally

PowerShell:

```powershell
Set-Location "C:\Users\jacks\.codex\.chatgpt-projects\g-p-6a7ba4e731b481919a357f044572274b\cordia_short"
& ".\.venv\Scripts\python.exe" app.py
```

Open http://127.0.0.1:5050/.

The OpenAI key is already stored locally in ignored `.env.local`. Never commit or paste that file into chat.

## Enable the real Google Drive proof

In Google Cloud Console:

1. Create or select a project and enable the Google Drive API.
2. Configure the OAuth consent screen.
3. Create an OAuth client with application type **Web application**.
4. Add every environment you intend to test as an exact authorized redirect URI. Google requires an exact match:

   `http://127.0.0.1:5050/api/connectors/oauth/callback`

   `https://beta.cordiacode.com/api/connectors/oauth/callback`

5. Add the resulting values directly to ignored `.env.local`:

```dotenv
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
CORDIA_BASE_URL=http://127.0.0.1:5050
```

Restart the application. Sign in, complete Surveyor, and tell Cordia `Connect Google Drive`. The connection is marked verified only after a successful Drive `files.list` response. Then ask `Show my recent Drive files`; a real provider-derived table artifact should appear.

Cordia completes discovery, authorization URL construction, token exchange, encrypted storage, verification, refresh, and artifact creation automatically. The user only clicks **Continue with Google** and approves access on Google's page. Google credentials and passwords are never entered into Cordia.

## API-key connector proof

Tell Cordia `Connect OpenAI API`. Cordia renders the same generic connector card as a secure password field outside chat. The submitted key is verified using the registry's declared `list_models` request. Only a successful provider response marks the connection verified; rejected keys are removed. After verification, ask Cordia to `List my OpenAI models` to create a provider-derived table artifact, then select **Use model** beside the model that should power later Cordia Agent messages.

Adding another API-key service requires a declarative record in `cordia/connectors.py`: aliases, secure fields, header template, verification operation, declared HTTPS operations, and artifact mapping. It does not require another runtime or frontend component.

## Private Workspace MCP boundary

The MCP server is internal to Cordia in this slice. It is created for one authenticated user and called through the embedded MCP client. The model cannot provide or switch `user_id`.

Available tools:

- `connectors_search`
- `connector_start`
- `connector_status`
- `connector_call`
- `artifact_create`

Available resources:

- `cordia://operator`
- `cordia://connectors`
- `cordia://artifacts`

No credential values are included in any MCP resource. The same MCP server contract can later run over `stdio` in the desktop application without changing connector behavior.

## Run tests

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
```

## Scope guardrails

- `cordia/connectors.py` contains provider data and aliases.
- `cordia/connector_runtime.py` contains the only connector execution path.
- No provider-specific Python modules or UI components.
- Credentials are encrypted at rest and excluded from model input, operator memory, messages, artifacts, and responses.
- OAuth and API-key connectors share the same registry, runtime, MCP, and artifact path.
- Provider endpoints must be declared in code and use HTTPS; users cannot submit arbitrary server URLs.
- No deployment, billing, installer, Alidora, marketplace, or automation work belongs in this slice.
