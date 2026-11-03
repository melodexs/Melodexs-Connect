# Contributing

Thanks for improving MELODEXS CONNECT.

## Before you start

* Never commit secrets, `.env` files, database dumps or `*.db` files.
* Never point tests at production. Use a scratch SQLite file.
* Do not rewrite the backend wholesale; extend it behind the same interfaces.

## Workflow

1. Branch from `master`: `feat/…`, `fix/…`, `docs/…` or `perf/…`.
2. Keep each commit to one idea, with a message that says what changed and why.
3. Run the suite before opening a pull request:

   ```bash
   cd apps/api-python
   PYTHON_TEST_DATABASE_URL=sqlite:////tmp/scratch.db python -m pytest tests/ -q
   ```

4. Open a pull request describing the behaviour change and how you verified it.
   Frontend-only changes skip CI by design; say what you checked in a browser.

## Rules that protect customers

* Money only moves through the atomic debit helper. No route may update
  `users.balance` on its own.
* A supplier failure that is not provably "never happened" leaves the
  transaction `pending`; it is never auto-refunded.
* New providers ship disabled and unconfigured, with mocked contract tests only.
* Prices come from the server, never from the browser.
* A test that fails because of a dialect difference is fixed by making the
  assertion dialect-aware, never by deleting the assertion.

## Style

* Python: four spaces, type hints on new helpers, docstrings explaining *why*.
* Frontend: no build step, no new dependencies, keep pages usable without
  JavaScript where they already are.
* Accessibility: every control needs a label; icons get `aria-hidden`.
