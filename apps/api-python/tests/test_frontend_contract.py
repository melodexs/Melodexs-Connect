"""Frontend-to-Python API contract test.

Scans every static frontend page and the API client in apps/web for /api/
request paths and asserts each one matches a route registered by the Python
backend. This prevents silent drift between the frontend contract and the
Python API (the Node backend is the rollback target, not the reference).
"""

import re
from pathlib import Path

from app.main import app  # noqa: F401  (imports validate configuration)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WEB_DIR = _REPO_ROOT / "apps" / "web"

# Path-shaped API literals in the frontend, including template literals:
#   "/api/data-plans?network=..."  -> /api/data-plans
#   `/api/user/${encodeURIComponent(userId)}` -> /api/user/{dynamic}
#   "/api/user/" + user.id (concatenated prefix) -> /api/user/{dynamic}
_PATH_RE = re.compile(r"""["'`](/api/[A-Za-z0-9_$(){}=?&:/-]+)["'`]""")


def _normalize(raw: str) -> tuple:
    """Normalize a frontend or backend path into comparable segments.

    Frontend template literals (`/api/user/${userId}`), concatenated
    suffixes (`"/api/user/" + user.id`), and FastAPI templates
    (`/api/user/{user_id}`) all normalize to one dynamic segment.
    """
    path = raw.split("?")[0]
    segments = []
    for segment in path.strip("/").split("/"):
        if segment.startswith("$") or segment.startswith(":"):
            segments.append("{dynamic}")
        elif re.fullmatch(r"\{[^}]+\}", segment):
            segments.append("{dynamic}")
        else:
            segments.append(segment.lower())
    if path.endswith("/") and segments:
        # A quoted prefix ending in "/" is concatenated with an id at call
        # time; treat the suffix as a dynamic segment.
        segments.append("{dynamic}")
    return tuple(segments)


def _frontend_api_paths() -> set:
    paths = set()
    for source in sorted(_WEB_DIR.glob("*.html")) + [_WEB_DIR / "api.js"]:
        text = source.read_text()
        for match in _PATH_RE.finditer(text):
            normalized = _normalize(match.group(1))
            if len(normalized) > 1:
                paths.add((normalized, source.name))
    return paths


def _iter_route_paths(routes):
    """Yield path templates, recursing into included-router wrappers.

    Recent FastAPI versions store included routers as a single wrapper
    object whose child routes are resolved at request time, so a flat scan
    of `app.routes` misses the included routes. Read them from the wrapper's
    `original_router` (or a plain `routes` attribute) instead.
    """
    for route in routes:
        template = getattr(route, "path", None)
        if template:
            yield template
        children = getattr(route, "routes", None) or getattr(route, "original_router", None)
        if children is not None:
            child_routes = getattr(children, "routes", children)
            yield from _iter_route_paths(child_routes)


def _python_routes() -> dict:
    routes = {}
    for template in _iter_route_paths(app.routes):
        if template.startswith("/api/"):
            routes[_normalize(template)] = template
    return routes


def test_every_frontend_api_call_matches_a_python_route():
    python_routes = _python_routes()
    assert python_routes, "no /api/ routes registered on the Python app"

    unmatched = []
    for (segments, source) in _frontend_api_paths():
        candidates = [
            template for template in python_routes
            if len(template) == len(segments) and all(
                seg == tmpl
                for seg, tmpl in zip(segments, template)
            )
        ]
        if not candidates:
            unmatched.append(f"{'/'.join(segments)}  ({source})")

    assert not unmatched, (
        "Frontend API calls with no matching Python route:\n  "
        + "\n  ".join(unmatched)
    )


def test_python_routes_cover_the_documented_frontend_contract():
    """Every registered Python route is either called by the frontend or is
    an explicitly allow-listed server-only route."""
    python_routes = _python_routes()
    frontend_paths = {segments for (segments, _source) in _frontend_api_paths()}
    unused = [template for normalized, template in python_routes.items()
              if normalized not in frontend_paths]
    # Intentionally not called by the static frontend:
    #  - /api/status: health/readiness probe used by monitoring and the Node
    #    smoke test.
    #  - /api/purchase-pin/verify: programmatic PIN check (admin/support tool).
    #  - /api/paystack/webhook: called by Paystack server-to-server.
    #  - /api/webhooks/isquaredata: ISQUAREDATA supplier server-to-server
    #    signed transaction callbacks.
    #  - /api/session: session-status probe used by the app shell and
    #    automated clients, not by an individual page action.
    allowed_unused = {"/api/status", "/api/session", "/api/purchase-pin/verify",
                      "/api/paystack/webhook", "/api/webhooks/isquaredata"}
    assert set(unused) == allowed_unused, (
        f"Unexpected Python routes unused by the frontend: "
        f"{sorted(set(unused) - allowed_unused)}"
    )


def test_frontend_api_configuration_is_centralized_and_safe():
    api_js = (_WEB_DIR / "api.js").read_text()
    # Exactly one cutover switch and one production URL constant.
    assert api_js.count("const API_TARGET_IS_PYTHON") == 1
    assert api_js.count("const PRODUCTION_API_URL") == 1
    # The production URL must never be a local address.
    prod_match = re.search(r'PRODUCTION_API_URL = "([^"]+)"', api_js)
    assert prod_match, "PRODUCTION_API_URL constant missing"
    assert "localhost" not in prod_match.group(1)
    assert prod_match.group(1).startswith("https://")
    # The duplicated catalog-flag assignment bug must not return.
    assert api_js.count("window.MELODEXS_CATEGORIZED_CATALOG =") == 1
    # Every API-using HTML page declares the meta override or inherits it.
    for page in _WEB_DIR.glob("*.html"):
        text = page.read_text()
        if "fetch(" in text or "api.js" in text:
            assert 'name="api-base-url"' in text, (
                f"{page.name} uses the API without declaring the api-base-url meta tag"
            )
