import asyncio
import threading
import time
from urllib.parse import urlparse

from .. import telegram as tg
from ..config import settings
from ..models import DownloadContext, DownloadResult, Job
from .base import DownloadHandler

_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}

# ponytail: one transfer at a time for the whole process. The session file is
# a SQLite DB and a second concurrent client on it races; Telegram also rate
# limits per account, so parallelism would mostly buy flood waits. Swap for a
# single long-lived client + semaphore if throughput ever matters.
_account_lock = threading.Lock()


def is_busy() -> bool:
    """A transfer is in flight. Logging in or deleting the session under it
    would have two clients writing the same session file."""
    return _account_lock.locked()


def _human_speed(bytes_per_sec: float) -> str:
    value = bytes_per_sec
    for unit in ("B", "KiB", "MiB"):
        if value < 1024 or unit == "MiB":
            return f"{value:.1f}{unit}/s"
        value /= 1024
    return f"{value:.1f}MiB/s"


class TelegramHandler(DownloadHandler):
    """A link to a single Telegram post, downloaded over MTProto as the
    logged-in user.

    Only post links (t.me/<chan>/<id>) match: without a message id there is
    nothing to download, just a channel to browse. Falls through to the
    catch-all when the branch is unconfigured, so a public t.me link can still
    be tried by yt-dlp.
    """

    name = "telegram"

    def can_handle(self, url: str) -> bool:
        if urlparse(url).netloc.lower() not in _HOSTS:
            return False
        if not (tg.AVAILABLE and settings.telegram_api_id):
            return False
        return tg.parse_ref(url)[1] is not None

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        # Holding the lock across the flood wait is the point: a flood wait is
        # throttling of the whole account, so every other Telegram job has to
        # wait it out too, not queue up more requests behind it.
        with _account_lock:
            # Queued behind another transfer, the user may have given up while
            # we were blocked; don't start a 500MB download for nothing.
            ctx.check_cancelled()
            while True:
                try:
                    return asyncio.run(self._download(job, ctx))
                except tg.TgFloodWait as exc:
                    # ponytail: hardcoded ceiling. Longer waits are a sign the
                    # account is in trouble; failing loudly beats a worker
                    # parked for an hour. Make it configurable if it bites.
                    if exc.seconds > 300:
                        raise
                    for left in range(exc.seconds, 0, -1):
                        ctx.check_cancelled()
                        ctx.on_progress(
                            {"status": "downloading", "speed": f"限流等待 {left}s"}
                        )
                        time.sleep(1)

    async def _download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        peer, message_id = tg.parse_ref(job.url)
        started = time.monotonic()
        last_emit = 0.0

        def on_progress(current: int, total: int) -> None:
            nonlocal last_emit
            ctx.check_cancelled()  # raising here aborts and cleans the .temp
            now = time.monotonic()
            if now - last_emit < 1.0 and current < total:
                return  # ~1 event/s: chunks arrive far faster than a UI needs
            last_emit = now
            elapsed = now - started
            speed = current / elapsed if elapsed > 0 else 0
            remaining = (total - current) / speed if speed > 0 else 0
            ctx.on_progress(
                {
                    "status": "downloading",
                    "progress": round(current / total * 100, 1) if total else 0.0,
                    "speed": _human_speed(speed) if speed else None,
                    "eta": f"{int(remaining) // 60:02d}:{int(remaining) % 60:02d}"
                    if remaining
                    else None,
                    "downloaded": current,
                    "total": total or None,
                }
            )

        source = tg.build_source()
        await source.connect()
        try:
            path, item = await source.download_media(
                peer, message_id, ctx.output_dir, on_progress=on_progress
            )
        finally:
            await source.close()

        ctx.on_progress({"status": "processing", "progress": 100.0})
        caption = (item.caption or "").strip().splitlines()
        return DownloadResult(
            file_path=path,
            title=item.file_name or (caption[0] if caption else f"{peer} #{message_id}"),
            filename=path.name,
            filesize=path.stat().st_size,
        )
