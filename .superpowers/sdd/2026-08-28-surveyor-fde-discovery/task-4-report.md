# Task 4: Authenticated Surveyor Onboarding API

## Delivered

- Replaced the primary legacy chat-survey state projection with authenticated, resumable version-2 onboarding state.
- Added `GET /api/onboarding`, `PUT /api/onboarding/<stage>`, and `POST /api/onboarding/complete` with authentication, validation, incomplete-completion, completed-edit, and workspace-I/O boundaries.
- Kept incomplete users out of workspace state, chat, artifacts, setup cards, and runtime status.
- Added browser-safe stage schemas, safe `{id, name}` application catalog projection, and compiler-normalized selected application/review state without configuration or credentials.
- Kept the legacy survey route only for partial legacy scalar state; new/onboarding users receive its required 410 boundary.
- Added `Store.agent_context()` and supplied the compiled operator, selected-applications, and FDE documents at both existing agent response boundaries.

## Test-first evidence

RED:

```powershell
../../.venv/Scripts/python.exe -m unittest tests.test_app.ApplicationJourneyTests.test_register_enters_version_two_onboarding tests.test_app.ApplicationJourneyTests.test_stage_save_returns_next_resumable_stage -v
```

Result: both failed as expected: registration returned `survey`, and the stage endpoint returned 404.

GREEN:

```powershell
../../.venv/Scripts/python.exe -m unittest tests.test_app.ApplicationJourneyTests.test_register_enters_version_two_onboarding tests.test_app.ApplicationJourneyTests.test_stage_save_returns_next_resumable_stage -v
```

Result: both passed.

RED:

```powershell
../../.venv/Scripts/python.exe -m unittest tests.test_app.ApplicationJourneyTests.test_legacy_completed_survey_does_not_raise_when_its_route_is_retried -v
```

Result: failed as expected with `StopIteration` from the legacy route after all scalar answers existed.

GREEN:

```powershell
../../.venv/Scripts/python.exe -m unittest tests.test_app.ApplicationJourneyTests.test_legacy_completed_survey_does_not_raise_when_its_route_is_retried -v
```

Result: passed with the explicit 409 legacy-complete response.

## Verification

```powershell
../../.venv/Scripts/python.exe -m unittest tests.test_app -v
../../.venv/Scripts/python.exe -m unittest discover -s tests -v
git diff --check
```

Result: application suite passed 26 tests; full suite passed 131 tests; diff check passed.

## Self-review

- Application catalog has only connector IDs/names, not auth configuration or secrets.
- Selected-applications status comes from the compiler normalization path; setup selection alone remains `setup_required`.
- Completion calls only Store compilation/installation and never an agent/model.
- Completed onboarding rejects stage writes, while repeat completion remains idempotent.
- The onboarding I/O error is logged server-side and returns no file-system details.

## Concerns

None.

## Review-fix round 1

### Fixed public selected-application projection

`normalize_applications()` intentionally carries compiler-only `auth_kind` metadata. The onboarding API now explicitly projects only validated user-entered application fields plus `registry_id` and runtime-derived `status`; it does not return `auth_kind` or connector configuration.

### Regression coverage

The selected-applications API test now records representative encrypted-connection input values and asserts that `GET /api/onboarding`, a stage-save response, and completion response omit credential, token, and configuration identifiers. It also proves a verified runtime status remains visible without exposing connection data.

### Verification

```powershell
../../.venv/Scripts/python.exe -m unittest tests.test_app -v
git diff --check
```

Result: application suite passed 26 tests; diff check passed.
