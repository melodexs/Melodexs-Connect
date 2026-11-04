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
| Public pages: price list escaping, support contact consistency | `test_public_price_list.py`, `test_help_and_support.py` |
| Wallet CSV export and customer-facing descriptions | `test_wallet_statement_export.py` |
| Page metadata: descriptions, `noindex` on everything not in the sitemap | `test_page_metadata.py` |
| Form accessibility: every input nameable, password fields declare autocomplete | `test_form_accessibility.py` |
| Error envelope, security helpers, rate limits, package matching, supplier comparison | `test_error_envelope.py`, `test_security_helpers.py`, `test_rate_limit_contract.py`, `test_package_units.py`, `test_package_family_and_keys.py`, `test_comparison_group.py` |

## Browser modules run under Node

`apps/web/statement.js` is plain JavaScript with no DOM access, so
`test_wallet_statement_export.py` executes it for real with Node rather than
only reading its source. This is how the spreadsheet formula-injection defence
is proven. Those tests skip when `node` is missing, so CI installs Node
explicitly (`api-python-ci.yml`) to make sure they always run. Locally, install
Node 22 or newer.

## When CI runs

The workflow runs for changes under `apps/api-python/**` **and** `apps/web/**`,
because the contract tests read the static site. A web-only change used to skip
CI entirely.

## Rules

* No live supplier calls. Adapters are exercised with mocked HTTP.
* PostgreSQL-only paths are opt-in (`postgres_test_gate.py`) and require a
  validated connection string; they are skipped otherwise.
* A failing assertion is fixed by making the assertion handle dialect
  differences, never by weakening what it checks.
* New behaviour ships with the test that would have caught its absence.
