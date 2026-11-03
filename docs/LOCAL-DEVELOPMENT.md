# Local development

## API

```bash
cd apps/api-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=sqlite:///./local.db python -m uvicorn app.main:app --reload
```

With SQLite the app creates its own schema on startup and seeds nothing, so the
catalogue is empty until a synchronisation runs or plans are inserted manually.
Production configuration is not needed: provider adapters report
`is_configured() == False` and routes answer 503 instead of calling out.

## Web

The frontend is static. Serve the folder and open a page:

```bash
cd apps/web
python -m http.server 8080
```

`api.js` rewrites `/api/*` to the API origin unless an `api-base-url` meta tag is
present, so a locally served page talks to production. For an offline UI run,
stub the calls or point the meta tag at a local API.

## Conventions

* Four-space indentation, double quotes in CSS/HTML, no build step.
* Every page includes `styles.css`, `api.js` and `ui.js`, in that order.
* Colour tokens live in `:root`; a `var(--token)` with no declaration silently
  inherits and produces invisible text, which `tests/test_css_tokens.py` catches.
