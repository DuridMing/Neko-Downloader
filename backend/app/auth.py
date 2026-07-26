"""One shared password for the whole service.

Not an account system — this is a single-user internal tool. The point is that
the API is not wide open to everyone who can reach the port: it can delete the
Telegram session, and since login moved into the web UI it also carries a phone
number, a login code and a 2FA password. ACCESS_PASSWORD=NONE (or empty)
disables all of this and keeps the old, unauthenticated behaviour.

Stateless on purpose: the cookie is an HMAC of the password itself, so there is
no session store to keep, a restart does not log anyone out, and changing the
password invalidates every cookie at once.

What it does not protect against: plain HTTP means anyone able to record
traffic on the network sees the password. Put TLS in front if the network is
not trusted — note that in macvlan deployments the container has its own LAN
address, so a reverse proxy elsewhere does not stop a direct connection.
"""

import hmac
from hashlib import sha256
from typing import Optional

from .config import settings

COOKIE_NAME = "neko_auth"
# The value .env.example ships. It means the same as empty — no authentication
# — and exists so the setting is *visible* in the settings file: a commented-out
# security control is one nobody remembers to turn on. A literal password of
# "NONE" is therefore not usable.
DISABLED = "NONE"
# A month: this is opened from a phone, and re-typing a password daily is how
# people end up picking a bad one.
COOKIE_MAX_AGE = 30 * 24 * 3600

# Reachable while locked, or there would be no way to unlock.
_OPEN_PATHS = ("/api/unlock",)


def _password() -> str:
    """The configured password, or "" when authentication is off."""
    value = settings.access_password.strip()
    return "" if value.upper() == DISABLED else value


def enabled() -> bool:
    return bool(_password())


def token() -> str:
    """The cookie value: proof of knowing the password, not the password."""
    return hmac.new(_password().encode(), b"neko-v1", sha256).hexdigest()


def password_ok(candidate: str) -> bool:
    # compare_digest, not ==: string comparison leaks the correct prefix length.
    # The enabled() guard matters: without it an empty candidate would match an
    # empty password.
    return enabled() and hmac.compare_digest(candidate, _password())


def cookie_ok(value: Optional[str]) -> bool:
    return bool(value) and hmac.compare_digest(value, token())


def needs_auth(path: str) -> bool:
    """Only the API and the websocket are gated. The static files are not:
    the page that asks for the password has to be able to load."""
    if not enabled() or path in _OPEN_PATHS:
        return False
    return path.startswith("/api/") or path == "/ws"
