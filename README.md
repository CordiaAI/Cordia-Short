# Cordia Short

Cordia Short is an isolated, clean-room candidate foundation for Cordia. It does not import from or modify the existing Cordia repository.

The product path is intentionally narrow:

```text
Sign in -> Surveyor -> operator.md -> same Cordia Agent conversation
        -> Google Drive setup card -> verified Drive operation -> artifact window
```

## Observed status on 2026-08-25

- Registration, password authentication, sessions, Surveyor, readable `operator.md`, continuous chat, generic setup cards, generic artifact windows, and sign-out are implemented.
- Every Cordia Agent response offers **Helpful** and **Adjust response** controls. A selected adjustment moves one operator preference toward `-1` or `1`, records evidence against that response, updates `operator.md`, and retries the original request.
- A real OpenAI request through `cordia.agent.Agent` returned a valid `propose_connector` action for Google Drive.
- The complete browser path was exercised from sign-in through all five Surveyor answers and the real agent request. The browser console had no errors.
- The generic setup card persisted after a full page refresh; this was caught and fixed during browser verification.
- Cordia now acts as the MCP host/client for a private, authenticated workspace server. Connector discovery, setup, status, operations, artifacts, `operator.md`, connector state, and artifacts are exposed through that user-bound MCP contract.
- The application uses the official MCP Python SDK's in-memory transport. Tool discovery, schema validation, and invocation still pass through MCP without adding another service or public endpoint.
- Model actions no longer call connector execution or artifact storage directly. The host maps bounded actions to MCP tools and returns explicit failures without creating substitute artifacts.
- Expired Google access tokens are refreshed automatically when Google issued a refresh token. A failed or unavailable refresh is reported rather than hidden.
- Google Drive OAuth has not been completed with a real Google account because `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are not configured. The application reports this explicitly and does not claim Drive is connected.
- The automated suite contains 42 passing tests at this commit. Provider-network responses in connector tests are controlled test evidence, not a live Google verification.

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
- Only Google Drive metadata read access is declared.
- No deployment, billing, installer, Alidora, marketplace, or automation work belongs in this slice.
