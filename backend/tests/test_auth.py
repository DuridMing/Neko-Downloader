"""The shared-password gate: what it covers, and that it stays off by default."""

import pytest

from app import auth
from app.config import settings


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings, "access_password", "hunter2")


@pytest.mark.parametrize("value", ["NONE", "none", " None ", ""])
def test_the_disabled_sentinel_leaves_everything_open(monkeypatch, value):
    """.env ships ACCESS_PASSWORD=NONE, and empty stays valid for older files.
    Existing installs must not suddenly demand a password."""
    monkeypatch.setattr(settings, "access_password", value)
    assert auth.enabled() is False
    assert auth.needs_auth("/api/jobs") is False
    assert auth.needs_auth("/ws") is False
    # Nothing may pass as "the right password" while authentication is off.
    assert auth.password_ok("") is False
    assert auth.password_ok("NONE") is False


def test_api_and_websocket_are_gated_but_the_page_itself_is_not(locked):
    assert auth.needs_auth("/api/jobs") is True
    assert auth.needs_auth("/ws") is True
    # Otherwise there is no page to type the password into.
    assert auth.needs_auth("/") is False
    assert auth.needs_auth("/assets/index-abc.js") is False
    assert auth.needs_auth("/api/unlock") is False


def test_cookie_proves_the_password_without_carrying_it(locked):
    cookie = auth.token()
    assert "hunter2" not in cookie
    assert auth.cookie_ok(cookie) is True
    assert auth.cookie_ok(None) is False
    assert auth.cookie_ok("") is False
    assert auth.cookie_ok("deadbeef") is False


def test_changing_the_password_invalidates_issued_cookies(locked, monkeypatch):
    old = auth.token()
    monkeypatch.setattr(settings, "access_password", "hunter3")
    assert auth.cookie_ok(old) is False


def test_password_check_accepts_only_the_exact_password(locked):
    assert auth.password_ok("hunter2") is True
    assert auth.password_ok("hunter") is False
    assert auth.password_ok("") is False


def test_surrounding_whitespace_in_the_setting_is_ignored(monkeypatch):
    """Trailing spaces in a .env line must not become part of the password."""
    monkeypatch.setattr(settings, "access_password", "  hunter2\t")
    assert auth.enabled() is True
    assert auth.password_ok("hunter2") is True
