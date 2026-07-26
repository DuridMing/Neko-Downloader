"""Domain types for the Telegram branch.

Nothing from the MTProto library may appear in these signatures. The adapter
maps library objects and errors into the types below, so business logic keeps
compiling when the library is swapped. That is not hypothetical: Pyrogram went
unmaintained, Telethon was archived in Feb 2026, and the current pick
(Kurigram) is itself a fork. Assume it will be replaced too.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


def parse_ref(ref: str) -> "tuple[int | str, int | None]":
    """Accept what a user would actually paste: @name, a t.me link, or an id.

    Returns (peer, message_id). A link to a single post keeps its message id —
    dropping it is how `t.me/chan/130170` ended up indexing the channel's
    oldest posts instead of the one the user pointed at.

    t.me/c/<n>/<msg> is the private-channel form; <n> is the id with the -100
    supergroup prefix stripped, so put it back.
    """
    ref = ref.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "tg://resolve?domain="):
        if ref.startswith(prefix):
            ref = ref[len(prefix) :]
            break
    ref = ref.lstrip("@").rstrip("/")
    head, _, tail = ref.partition("/")
    if head == "c":
        internal, _, tail = tail.partition("/")
        head = f"-100{internal}" if internal.isdigit() else internal
    # Topic/thread links are /<peer>/<topic>/<msg>: the last number is the post.
    message_id = next((int(p) for p in reversed(tail.split("/")) if p.isdigit()), None)
    peer: "int | str" = int(head) if head.lstrip("-").isdigit() else head
    return peer, message_id


@dataclass(frozen=True)
class TgAccount:
    """The logged-in user. Deliberately excludes anything session-shaped:
    no auth key, no session path, so this is safe to log and to serialize."""

    id: int
    first_name: str
    username: Optional[str] = None
    phone: Optional[str] = None

    @property
    def label(self) -> str:
        return f"@{self.username}" if self.username else self.first_name


@dataclass(frozen=True)
class TgChannel:
    id: int
    title: str
    username: Optional[str] = None
    # "限制轉存": the owner enabled content protection. Recorded so the UI can
    # show it; it changes nothing about how we read, since the restriction is
    # enforced by official clients rather than by the protocol.
    protected: bool = False
    members: Optional[int] = None

    @property
    def is_private(self) -> bool:
        """No public @username, so it is only reachable because the user
        already joined it. We never join anything ourselves."""
        return self.username is None


@dataclass(frozen=True)
class TgMediaItem:
    """One downloadable message. Metadata only — indexing never fetches bytes."""

    channel_id: int
    message_id: int
    date: datetime
    kind: str  # video | document | audio | photo
    # Stable identifier for the *file*, equal across channels when the same
    # file is reposted. This is the cross-channel dedup key that lets stage 3
    # hardlink instead of downloading twice.
    document_id: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    duration: Optional[int] = None
    caption: Optional[str] = None

    @property
    def key(self) -> tuple[int, int]:
        """Primary key: (channel_id, message_id)."""
        return (self.channel_id, self.message_id)


class TgError(Exception):
    """Base for every Telegram-branch failure the business layer may see."""


class TgAuthRequired(TgError):
    """No usable session. Fixed by logging in: scripts/telegram-login.py, or
    the settings panel in the web UI (see app/telegram/weblogin.py)."""


class TgFloodWait(TgError):
    """Telegram asked us to back off for `seconds`.

    Contract for the queue (stage 4): pause the whole account queue until
    `retry_at`, do NOT increment the task's retry count, and do NOT retry
    immediately. A flood wait is throttling, not a task failure.
    """

    def __init__(self, seconds: int) -> None:
        self.seconds = int(seconds)
        self.retry_at = datetime.now(timezone.utc) + timedelta(seconds=self.seconds)
        super().__init__(f"flood wait {self.seconds}s, until {self.retry_at.isoformat(timespec='seconds')}")


class TgBadCode(TgError):
    """Login code was wrong or expired."""


class TgNotFound(TgError):
    """Channel/message is gone, or this account cannot see it. Never a reason
    to auto-join: the user joins channels manually, by design."""
