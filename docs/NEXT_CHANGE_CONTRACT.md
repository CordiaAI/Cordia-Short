# Cordia Short Next Change Contract

Status: **APPROVED** (user approval in chat, 2026-10-07)

## Observable user outcome

The public cannot brute-force sign-in, run up model costs, embed Cordia in another page, or read internal configuration and historical plans. Dead endpoints and files are gone. Developers work on branches and merge to `master` only after CI passes and a code owner approves.

## Official sources

- Flask security considerations: https://flask.palletsprojects.com/en/stable/web-security/
- OWASP Secure Headers: https://owasp.org/www-project-secure-headers/
- Vercel request headers (`x-real-ip`): https://vercel.com/docs/headers/request-headers
- GitHub CODEOWNERS: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners

## Existing ownership

- `app.py` owns HTTP routes, cookies, and response handling.
- `cordia/store.py` owns persistence, including the new `rate_limits` table.
- `cordia/connector_runtime.py` owns connector configuration messages.

## Files changed

`app.py`, `cordia/store.py`, `cordia/connector_runtime.py`, `static/app.js`, `static/onboarding.js`, `site/vercel.json`, `.gitignore`, `README.md`, tests, this contract, `docs/CURRENT_BUILD_TRUTH.md`, new `.github/CODEOWNERS`, `.github/pull_request_template.md`, `CONTRIBUTING.md`, `SECURITY.md`, `tests/test_security.py`.

## Deleted

`/api/survey`, `/api/connectors/select`, `/api/connectors/live-view`, `ConnectorRuntime.live_view_access`, `ConnectorRuntime.select_value`, model-select UI, `scripts/verify_agent.py`, `tests/test_verification.py`, `design-qa.md`, `cordia-short-browser.png`, `static/assets/google-drive.png`, `docs/agent-framework.md`, `docs/superpowers/`.

## Non-goals

No new auth system, no CAPTCHA, no change to the connector, agent, or Surveyor behavior.

## Acceptance evidence

Full Python and Node suites pass locally; `tests/test_security.py` covers headers, cookie flags, throttling, size caps, and malformed input; CI runs the Postgres rate-limit test.
