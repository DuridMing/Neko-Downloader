"""Guards for the Telegram branch's hard rules.

These are the constraints that are cheap to break by accident later: leaking
the MTProto library past the seam, and growing an auto-join method.
"""

import ast
from datetime import datetime, timezone
from pathlib import Path

from app.telegram.source import TelegramSource
from app.telegram.types import TgFloodWait

TG_DIR = Path(__file__).resolve().parent.parent / "app" / "telegram"
ROOT = Path(__file__).resolve().parent.parent.parent
MTPROTO_LIBS = {"pyrogram", "kurigram", "telethon", "tgcrypto"}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_business_layer_never_imports_the_mtproto_library():
    """types.py/source.py define the contract; only adapters may name a library."""
    for name in ("types.py", "source.py"):
        leaked = _imported_roots(TG_DIR / name) & MTPROTO_LIBS
        assert not leaked, f"{name} leaks MTProto library import(s): {leaked}"


def test_only_adapter_modules_touch_the_library():
    """Anything outside *_source.py must stay library-agnostic."""
    for path in TG_DIR.glob("*.py"):
        if path.name.endswith("_source.py"):
            continue
        leaked = _imported_roots(path) & MTPROTO_LIBS
        assert not leaked, f"{path.name} leaks MTProto library import(s): {leaked}"


def test_source_interface_offers_no_way_to_join_a_channel():
    """Hard rule: never call JoinChannelRequest / ImportChatInviteRequest.
    The interface must not even offer the capability."""
    forbidden = ("join", "invite", "import_chat")
    for attr in dir(TelegramSource):
        assert not any(f in attr.lower() for f in forbidden), f"join-ish method: {attr}"


def test_no_adapter_calls_a_join_or_invite_api():
    for path in TG_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for banned in ("joinchannel", "importchatinvite", "join_chat"):
            # The rule is quoted in comments; only real call syntax is a bug.
            assert f"{banned}(" not in text, f"{path.name} calls {banned}()"


def test_example_env_holds_no_real_credentials():
    """.env.example is git-tracked; .env is not. Real credentials belong in
    the latter. This caught a live leak once already."""
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue  # commented-out sample values are fine
        key, _, value = line.partition("=")
        if key == "ACCESS_PASSWORD":
            # Present but disabled: a visible setting beats a commented-out one.
            assert value.strip() == "NONE", "a real password in the tracked example"
            continue
        assert key not in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"), (
            f"{key} is set in the tracked example file"
        )


def test_the_real_settings_file_is_git_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert ".env" in ignore, "the only settings file must never be committed"
    assert ".secrets/" in ignore


def test_floodwait_carries_release_time_for_the_queue_to_park_on():
    before = datetime.now(timezone.utc)
    exc = TgFloodWait(120)
    assert exc.seconds == 120
    delay = (exc.retry_at - before).total_seconds()
    assert 119 <= delay <= 122, delay
    assert "120" in str(exc)
