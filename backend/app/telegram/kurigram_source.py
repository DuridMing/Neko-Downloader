"""Kurigram adapter for TelegramSource.

Kurigram is a maintained fork of Pyrogram and still imports as `pyrogram`,
so this is the only module that may name it. Everything crossing out of here
is a domain type from types.py.

Why Kurigram (checked 2026-07-25): Pyrogram is unmaintained and Telethon was
archived 2026-02-21 (last release 1.44.0). Kurigram is on 2.2.24, released
2026-07-11, and ships prebuilt wheels for CPython 3.13 — which matters here
because this host has no compiler.
"""

import asyncio
import contextlib
import os
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from pyrogram import Client
from pyrogram import errors as tg_errors
from pyrogram.types import Chat, Message, User

from .source import TelegramSource
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

# Fallback probe order, only used when msg.media is missing. Ordered so the
# richest type wins: a video sent as a file populates .document. This list is
# not the source of truth — msg.media is — because hardcoding types is exactly
# how animation/video_note/voice got missed and whole channels indexed empty.
_MEDIA_ATTRS = (
    "video",
    "document",
    "animation",
    "video_note",
    "audio",
    "voice",
    "photo",
    "live_photo",
    "sticker",
)


def _normalize_ref(ref: str) -> "int | str":
    return parse_ref(ref)[0]


def _to_account(user: User) -> TgAccount:
    return TgAccount(
        id=user.id,
        first_name=user.first_name or "",
        username=user.username,
        phone=user.phone_number,
    )


def _to_channel(chat: Chat) -> TgChannel:
    return TgChannel(
        id=chat.id,
        title=chat.title or chat.first_name or str(chat.id),
        username=chat.username,
        protected=bool(chat.has_protected_content),
        members=chat.members_count,
    )


def _media_kind(msg: Message) -> Optional[str]:
    """What kind of media the message carries, downloadable or not.

    Reported for diagnostics so an empty index is explainable ("40 web_page,
    3 poll") instead of a silent zero.
    """
    if msg.media is None:
        return None
    return getattr(msg.media, "value", str(msg.media))


def _resolve_media(msg: Message) -> tuple[Optional[str], object]:
    """The message's media attribute, driven by msg.media rather than a
    hardcoded list, so new Telegram media types are picked up for free."""
    kind = _media_kind(msg)
    if kind:
        media = getattr(msg, kind, None)
        if media is not None:
            return kind, media
    for name in _MEDIA_ATTRS:
        media = getattr(msg, name, None)
        if media is not None:
            return name, media
    return kind, None


def _to_media_item(msg: Message) -> Optional[TgMediaItem]:
    """None for anything without a downloadable file: text posts, service
    messages, polls, link previews. Callers skip those; not an error."""
    kind, media = _resolve_media(msg)
    # file_unique_id is what makes something an actual file. Polls, locations,
    # link previews and paid-media containers have none, so they drop out here
    # without needing a type whitelist to maintain.
    if media is None or not getattr(media, "file_unique_id", None):
        return None

    return TgMediaItem(
        channel_id=msg.chat.id,
        message_id=msg.id,
        date=msg.date,
        kind=kind,
        # file_unique_id is stable for the same file across channels, unlike
        # file_id which is bound to this peer. That makes it the dedup key.
        document_id=getattr(media, "file_unique_id", None),
        file_name=getattr(media, "file_name", None),
        file_size=getattr(media, "file_size", None),
        mime_type=getattr(media, "mime_type", None),
        duration=getattr(media, "duration", None),
        caption=msg.caption,
    )


@contextlib.contextmanager
def _mapped_errors():
    """Translate library exceptions into domain ones at the boundary."""
    try:
        yield
    except tg_errors.FloodWait as exc:
        raise TgFloodWait(exc.value) from exc
    except (tg_errors.PhoneCodeInvalid, tg_errors.PhoneCodeExpired) as exc:
        raise TgBadCode(str(exc)) from exc
    except tg_errors.AuthKeyUnregistered as exc:
        raise TgAuthRequired("session was revoked; log in again") from exc
    except (
        tg_errors.ChannelPrivate,
        tg_errors.PeerIdInvalid,
        tg_errors.UsernameNotOccupied,
        tg_errors.UsernameInvalid,
        tg_errors.ChannelInvalid,
    ) as exc:
        # Deliberately terminal. Auto-joining would "fix" this, which is
        # exactly what the hard rules forbid.
        raise TgNotFound(
            "this account cannot see that channel — join it manually in a "
            "Telegram client first"
        ) from exc


class KurigramSource(TelegramSource):
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_dir: Path,
        session_name: str = "neko_user",
    ) -> None:
        if not api_id or not api_hash:
            raise TgError("TELEGRAM_API_ID / TELEGRAM_API_HASH are not configured")
        self._api_id = int(api_id)
        self._api_hash = api_hash
        self._session_dir = Path(session_dir)
        self._session_name = session_name
        self._client: Optional[Client] = None

    # -- session file ------------------------------------------------------

    @property
    def session_path(self) -> Path:
        return self._session_dir / f"{self._session_name}.session"

    def _new_client(self) -> Client:
        # Owner-only before the library can create the file, so the auth key is
        # never briefly world-readable.
        self._session_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._session_dir, 0o700)
        return Client(
            name=self._session_name,
            api_id=self._api_id,
            api_hash=self._api_hash,
            workdir=self._session_dir,
            # We poll history on demand; consuming the update stream would only
            # add load and keep the singleton worker busy for nothing.
            no_updates=True,
        )

    def _harden(self) -> None:
        """The session file *is* full account access — treat it as a key, not
        as data. Never copy it into the DB, logs, API responses or backups."""
        if self.session_path.exists():
            os.chmod(self.session_path, 0o600)

    # -- TelegramSource ----------------------------------------------------

    async def connect(self) -> None:
        client = self._new_client()
        with _mapped_errors():
            authorized = await client.connect()
        self._harden()
        if not authorized:
            with contextlib.suppress(Exception):
                await client.disconnect()
            raise TgAuthRequired(
                f"no Telegram session at {self.session_path}; "
                "run scripts/telegram-login.py once"
            )
        self._client = client

    async def close(self) -> None:
        if self._client is None:
            return
        with contextlib.suppress(Exception):
            await self._client.disconnect()
        self._client = None

    def _require_client(self) -> Client:
        if self._client is None:
            raise TgAuthRequired("not connected; call connect() first")
        return self._client

    async def get_account(self) -> TgAccount:
        with _mapped_errors():
            return _to_account(await self._require_client().get_me())

    async def get_channel(self, ref: str) -> TgChannel:
        client = self._require_client()
        with _mapped_errors():
            return _to_channel(await client.get_chat(_normalize_ref(ref)))

    async def iter_media(
        self,
        channel: TgChannel,
        *,
        after_message_id: int = 0,
        limit: Optional[int] = None,
        on_scan: Optional[Callable[[int, Optional[str]], None]] = None,
    ) -> AsyncIterator[TgMediaItem]:
        client = self._require_client()
        yielded = 0
        try:
            # reverse=True walks oldest -> newest, and min_id bounds it to
            # messages newer than the watermark, which is what makes
            # after_message_id a resumable resume point. (offset_id would also
            # work but the library deprecated it.) limit=0 means "no limit".
            async for msg in client.get_chat_history(
                channel.id,
                min_id=after_message_id,
                reverse=True,
                limit=0,
            ):
                # Belt and braces: never re-emit anything at or below the
                # watermark, whatever min_id ends up meaning.
                if msg.id <= after_message_id:
                    continue
                if on_scan is not None:
                    on_scan(msg.id, _media_kind(msg))
                item = _to_media_item(msg)
                if item is None:
                    continue  # text/service post: a gap, not a failure
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
        except tg_errors.FloodWait as exc:
            raise TgFloodWait(exc.value) from exc
        except (
            tg_errors.ChannelPrivate,
            tg_errors.PeerIdInvalid,
            tg_errors.ChannelInvalid,
        ) as exc:
            raise TgNotFound("lost access to that channel mid-scan") from exc

    def session_exists(self) -> bool:
        return self.session_path.exists()

    async def logout(self) -> None:
        client = self._client
        try:
            if client is None:
                client = self._new_client()
                if await client.connect():
                    await client.log_out()  # revokes the key server-side
                else:
                    await client.disconnect()
            else:
                await client.log_out()
                self._client = None
        except Exception:
            # A revoke that fails (revoked already, no network) must not keep
            # the key sitting on disk — deleting locally is the part we can
            # guarantee, so it happens either way.
            pass
        finally:
            self.session_path.unlink(missing_ok=True)
            self.session_path.with_suffix(".session-journal").unlink(missing_ok=True)
            self._client = None

    async def download_media(
        self,
        peer: "int | str",
        message_id: int,
        dest_dir: Path,
        *,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> "tuple[Path, TgMediaItem]":
        client = self._require_client()
        with _mapped_errors():
            msg = await client.get_messages(
                _normalize_ref(peer) if isinstance(peer, str) else peer, message_id
            )
        if msg is None or getattr(msg, "empty", False):
            raise TgNotFound(f"message {message_id} is gone or not visible")
        item = _to_media_item(msg)
        if item is None:
            raise TgNotFound(f"message {message_id} carries no downloadable file")

        dest_dir.mkdir(parents=True, exist_ok=True)
        # Telegram-supplied names are untrusted input: basename only, or a
        # channel could write outside dest_dir with "../..". Empty name means
        # "you pick one", which the library does from the media type.
        safe = os.path.basename(item.file_name or "").strip() or ""
        target = f"{dest_dir}{os.sep}{safe}"

        with _mapped_errors():
            path = await client.download_media(
                msg, file_name=target, progress=on_progress
            )
        if path is None:  # transmission stopped without an exception
            raise TgError(f"download of message {message_id} did not complete")
        return Path(path), item

    async def login(
        self,
        phone: str,
        ask_code: Callable[[], str],
        ask_password: Callable[[], str],
    ) -> TgAccount:
        client = self._new_client()
        await client.connect()
        try:
            with _mapped_errors():
                sent = await client.send_code(phone)
                # input() would block the event loop and Pyrogram's keepalive.
                code = (await asyncio.to_thread(ask_code)).strip()
                try:
                    user = await client.sign_in(phone, sent.phone_code_hash, code)
                except tg_errors.SessionPasswordNeeded:
                    password = await asyncio.to_thread(ask_password)
                    user = await client.check_password(password)
            if not isinstance(user, User):
                # Pending terms-of-service or a signup prompt: this account has
                # never been used, which an official client must resolve.
                raise TgError(
                    "Telegram wants this account to finish setup (terms of "
                    "service / signup) in an official client first"
                )
            return _to_account(user)
        finally:
            # disconnect() is what flushes the session to disk.
            with contextlib.suppress(Exception):
                await client.disconnect()
            self._harden()
