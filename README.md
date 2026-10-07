# Cordia Short

Cordia Short is the Cordia MVP: Surveyor onboarding, a bounded Cordia Agent, universal connectors through Pipedream Connect, and workspace artifacts. Production runs on Vercel with Supabase Postgres; local runs use SQLite under `data/`.

```text
Sign in -> Surveyor (Parts 1-4) -> Profile Snapshot -> Workspace Discovery -> Workspace Review
        -> surveyor.md + connectors.md -> fde.md -> FDE workspace build
        -> connector setup card -> verified provider operation -> artifact window
```

While `CORDIA_COMING_SOON_AFTER_SURVEY` is true (the default), users see their survey results and a "workspace coming soon" status after Surveyor instead of the workspace build.

Agent rules live in [AGENTS.md](AGENTS.md); verified build state lives in [docs/CURRENT_BUILD_TRUTH.md](docs/CURRENT_BUILD_TRUTH.md). Contribution workflow is in [CONTRIBUTING.md](CONTRIBUTING.md).

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env.local                       # fill in values privately; never commit them
python app.py                                    # http://127.0.0.1:5050
```

Surveyor works without a model key. Agent turns require `OPENAI_API_KEY`; connectors require the `PIPEDREAM_*` values. Missing configuration returns an explicit unavailable error.

## Run tests

```bash
python -m compileall -q app.py cordia tests
python -m unittest discover -s tests -v
CORDIA_TEST_PYTHON=python node --test tests/*.cjs
```

Tests use real temporary SQLite databases and graph execution. Scripted models and provider HTTP responses are boundary doubles, not proof of provider availability.

## Scope guardrails

- `cordia/connectors.py` normalizes provider-returned application and tool records; it contains no application catalog.
- `cordia/connector_runtime.py` contains the only connector execution path.
- `cordia/workspace_mcp.py` is the only MCP boundary, created per authenticated user; the model cannot provide or switch `user_id`.
- No provider-specific Python modules or UI components.
- Credentials are encrypted at rest and excluded from model input, operator memory, messages, artifacts, and responses.
- Users cannot submit arbitrary execution URLs.
