# Testing

## Running the suite

Tests must never touch a real database. Point them at a throwaway file:

```bash
cd apps/api-python
PYTHON_TEST_DATABASE_URL=sqlite:////tmp/scratch.db python -m pytest tests/ -q
```

`PYTHON_TEST_DATABASE_URL` is the variable the fixtures read. Setting
`DATABASE_URL` instead silently falls back to `tests/test_suite.db`, which
pollutes later runs with leftover rate limits and sessions.

## What the suite protects

| Area | Example file |
| --- | --- |
| Money safety: PIN, idempotency, atomic debit, price revalidation | `test_backend_safety.py` |
| Session handling, cookie-less browsers, logout | `test_cookieless_session.py`, `test_session_safety.py` |
| Provider contracts, routing and fallbacks | `test_provider_platform.py`, `test_wisesub_fallback.py` |
| Catalogue pricing and categories | `test_plan_catalog.py`, `test_categorization.py` |
| Frontend contract: routes the UI calls, CSS tokens, installability | `test_frontend_contract.py`, `test_css_tokens.py`, `test_pwa_installability.py` |
| Security headers and origin checks | `test_security_headers.py`, `test_origin_gate_safety.py` |

## Rules

* No live supplier calls. Adapters are exercised with mocked HTTP.
* PostgreSQL-only paths are opt-in (`postgres_test_gate.py`) and require a
  validated connection string; they are skipped otherwise.
* A failing assertion is fixed by making the assertion handle dialect
  differences, never by weakening what it checks.
* New behaviour ships with the test that would have caught its absence.
