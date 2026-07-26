"""Telegram branch: read media from channels this account has already joined.

Optional feature. Kurigram may be absent (it is not needed for the m3u8 side),
so import failures disable the branch instead of breaking app startup — same
pattern as the Playwright-optional browser_sniff handler.
"""

from pathlib import Path
from typing import Optional

from ..config import BACKEND_DIR, settings
from .index import TgIndex
from .source import TelegramSource
from .weblogin import web_login
from .types import (
    TgAccount,
    TgAuthRequired,
    TgBadCode,
    TgChannel,
    TgError,
    TgFloodWait,
    TgMediaItem,
    TgNotFound,
    parse_ref,
)

try:
    from .kurigram_source import KurigramSource

    AVAILABLE = True
except ImportError:  # pragma: no cover - depends on install
    KurigramSource = None  # type: ignore[assignment]
    AVAILABLE = False

__all__ = [
    "AVAILABLE",
    "TelegramSource",
    "TgAccount",
    "TgAuthRequired",
    "TgBadCode",
    "TgChannel",
    "TgError",
    "TgFloodWait",
    "TgIndex",
    "TgMediaItem",
    "TgNotFound",
    "parse_ref",
    "session_dir",
    "status",
    "forget_account",
    "web_login",
    "build_source",
]


def session_dir() -> Path:
    """Where the auth key lives. Relative paths resolve against backend/.
    Never place this under tmp_dir: JobQueue.start() wipes that on boot."""
    path = Path(settings.telegram_session_dir)
    return path if path.is_absolute() else BACKEND_DIR / path


def build_source() -> TelegramSource:
    """The one place that picks an implementation."""
    if not AVAILABLE:
        raise TgError("kurigram is not installed; pip install -r requirements.txt")
    return KurigramSource(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        session_dir=session_dir(),
        session_name=settings.telegram_session_name,
    )


# Verifying a session costs a connect + round trip, and the settings panel asks
# on every open. Cached until login/logout changes it; a session revoked from
# another device shows up on the next restart or logout, which is good enough
# for a status badge.
_account: Optional[str] = None


def forget_account() -> None:
    global _account
    _account = None


async def status() -> dict:
    """What the settings UI needs: is this branch usable, and as whom."""
    global _account
    state = {
        "available": AVAILABLE,
        "configured": bool(settings.telegram_api_id and settings.telegram_api_hash),
        "has_session": False,
        "account": _account,
        "error": None,
    }
    if not (state["available"] and state["configured"]):
        return state
    source = build_source()
    state["has_session"] = source.session_exists()
    if not state["has_session"] or _account:
        return state
    try:
        await source.connect()
        _account = state["account"] = (await source.get_account()).label
    except TgError as exc:
        state["error"] = str(exc)
    finally:
        await source.close()
    return state
