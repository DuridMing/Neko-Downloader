"""The password gate as the HTTP layer actually applies it.

test_auth.py covers the helpers; this covers the wiring — middleware, the
websocket check that middleware cannot do, and the unlock round trip.

TestClient is used without its context manager on purpose: entering it runs
the lifespan, which wipes TMP_DIR and starts download workers. These tests
only need routing.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth
from app.config import settings
from app.main import app

PASSWORD = "hunter2"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings, "access_password", PASSWORD)


def test_without_a_password_the_api_stays_open(client):
    """The upgrade must not break installs that never set a password."""
    assert client.get("/api/jobs").status_code == 200
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "queue_snapshot"


def test_locked_api_rejects_requests_without_the_cookie(client, locked):
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/jobs", json={"url": "https://example.com/a.mp4"}).status_code == 401
    assert client.get("/api/telegram").status_code == 401


def test_locked_websocket_is_refused(client, locked):
    """Starlette middleware never sees websockets, so /ws checks the cookie
    itself. If this test fails, the queue is readable without the password."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass


def test_static_page_stays_reachable_while_locked(client, locked):
    """Otherwise there is no page on which to type the password."""
    assert auth.needs_auth("/") is False
    assert client.post("/api/unlock", json={"password": "nope"}).status_code == 401


def test_unlocking_grants_access_to_api_and_websocket(client, locked):
    res = client.post("/api/unlock", json={"password": PASSWORD})
    assert res.status_code == 200
    cookie = res.cookies.get(auth.COOKIE_NAME)
    assert cookie and PASSWORD not in cookie

    assert client.get("/api/jobs").status_code == 200
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "queue_snapshot"


def test_a_cookie_from_a_different_password_is_rejected(client, locked, monkeypatch):
    res = client.post("/api/unlock", json={"password": PASSWORD})
    assert res.status_code == 200
    monkeypatch.setattr(settings, "access_password", "rotated")
    assert client.get("/api/jobs").status_code == 401
