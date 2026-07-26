"""The seam between business logic and whichever MTProto library is current.

Implementations live next to this file (see kurigram_source.py). Import rule,
enforced by tests/test_telegram_seam.py: this module and types.py must never
import the MTProto library, so swapping it means writing one new adapter.

Scope note: stage 1 covers authentication only. Indexing and download methods
are added here in stages 2-3 rather than being stubbed out now.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from .types import TgAccount, TgChannel, TgMediaItem


class TelegramSource(ABC):
    """A logged-in Telegram user account, viewed as a data source.

    Never joins anything: there is no join/import-invite method on this
    interface on purpose. Channels are joined by the user in a real Telegram
    client; we only read what the account can already see.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Open the session. Raises TgAuthRequired if no valid session exists."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection. Safe to call when never connected."""

    @abstractmethod
    async def get_account(self) -> TgAccount:
        """The signed-in user. Requires connect() first."""

    @abstractmethod
    async def get_channel(self, ref: str) -> TgChannel:
        """Resolve @username, a t.me link, or a numeric id.

        Raises TgNotFound when the account cannot see the channel. That is the
        end of it: a private channel the user has not joined stays unreachable,
        because joining is the user's job, done in a real Telegram client.
        """

    @abstractmethod
    def iter_media(
        self,
        channel: TgChannel,
        *,
        after_message_id: int = 0,
        limit: Optional[int] = None,
        on_scan: Optional[Callable[[int, Optional[str]], None]] = None,
    ) -> AsyncIterator[TgMediaItem]:
        """Yield media messages, metadata only — no bytes are fetched here.

        Walks oldest to newest starting just past `after_message_id`, so the
        caller can keep the last id as an incremental watermark and resume.
        Message ids are not contiguous (deletions, service messages, non-media
        posts); gaps are normal and never an error.

        `on_scan(message_id, media_kind)` fires for *every* message seen,
        including ones that yield nothing, with media_kind None for plain text.
        Without it the caller could not advance its watermark past a run of
        text posts, and an empty result would be indistinguishable from a
        broken scan.
        """

    @abstractmethod
    def session_exists(self) -> bool:
        """Whether a stored session is present. Cheap and offline — says
        nothing about whether Telegram still accepts it."""

    @abstractmethod
    async def logout(self) -> None:
        """Revoke the session with Telegram, then delete it locally.

        Revoking matters: deleting only the local file would leave a session
        alive on Telegram's side that a leaked copy could still use. Deleting
        locally happens even if the revoke call fails.
        """

    @abstractmethod
    async def download_media(
        self,
        peer: "int | str",
        message_id: int,
        dest_dir: Path,
        *,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> "tuple[Path, TgMediaItem]":
        """Fetch one message's file into dest_dir; returns (path, metadata).

        `on_progress(downloaded, total)` fires per chunk. Raising from it
        aborts the transfer and deletes the partial file — that is the whole
        cancellation mechanism, so callers do not need a separate flag.

        Raises TgNotFound when the message is gone or carries no file.
        """

    @abstractmethod
    async def login(
        self,
        phone: str,
        ask_code: Callable[[], str],
        ask_password: Callable[[], str],
    ) -> TgAccount:
        """One-time interactive sign-in, driven by the CLI.

        `ask_code`/`ask_password` are blocking prompts; the adapter runs them
        off the event loop. `ask_password` is only called when the account has
        two-step verification enabled.
        """
