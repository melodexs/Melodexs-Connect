"""Two payloads that everything else depends on: the health probe and errors.

The keep-alive workflow, the deploy checklist and every page boot read these, so
their shape is a contract rather than an implementation detail.
"""
from fastapi.testclient import TestClient

from app import main


def test_status_reports_success_without_authentication():
    with TestClient(main.app) as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "running" in body["message"].lower()


def test_bootstrap_is_usable_before_login():
    """Pages call it on load; an unauthenticated caller must get a clean answer,
    not a 401 that would bounce them off a public page."""
    with TestClient(main.app) as client:
        response = client.get("/api/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["loggedIn"] is False
    assert body["user"] is None


def test_protected_routes_answer_401_not_500():
    for path in ("/api/transactions/1", "/api/favorites", "/api/admin/stats"):
        with TestClient(main.app) as client:
            response = client.get(path)
        assert response.status_code in {401, 403}, f"{path} returned {response.status_code}"


def test_unknown_route_does_not_leak_a_traceback():
    with TestClient(main.app) as client:
        response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert "traceback" not in response.text.lower()
