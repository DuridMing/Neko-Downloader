import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .audit import audit
from .config import settings
from .handlers import registry
from .models import CancelledByUser, DownloadContext, Job, JobStatus, NeedsSelection
from .ws import ws_manager

logger = logging.getLogger("neko.queue")

TERMINAL_STATES = {
    JobStatus.DONE,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.EXPIRED,
}


class JobQueue:
    """Format-agnostic job queue: bounded asyncio queue, N workers,
    cancel flags, and TTL-based temp file cleanup."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.max_queue_size)
        self._cancel_flags: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        # Temp is disk-backed (not RAM tmpfs), so it survives a crash/restart.
        # Wipe leftovers on boot to keep the "restart = clean slate" guarantee
        # that RAM gave for free. rmtree on a bind-mount point clears its
        # contents and harmlessly fails to remove the mount itself.
        tmp = Path(settings.tmp_dir)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        for i in range(settings.max_concurrent):
            self._tasks.append(asyncio.create_task(self._worker(i)))
        self._tasks.append(asyncio.create_task(self._cleanup_loop()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # -- public API --------------------------------------------------------

    async def submit(
        self, url: str, referer: Optional[str] = None, cookies: Optional[str] = None
    ) -> Job:
        handler = registry.resolve(url)
        job = Job.new(url=url, handler=handler.name, referer=referer, cookies=cookies)
        self.jobs[job.id] = job
        try:
            self._queue.put_nowait(job.id)
        except asyncio.QueueFull:
            del self.jobs[job.id]
            raise
        await self._broadcast(job)
        return job

    async def cancel(self, job_id: str) -> Optional[Job]:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.PROCESSING):
            self._cancel_flags.add(job_id)
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now(timezone.utc)
                await self._broadcast(job)
        else:
            # Terminal or ready job: remove it entirely (and its file).
            self._delete_files(job)
            del self.jobs[job_id]
            await ws_manager.broadcast({"type": "job_removed", "id": job_id})
        return job

    async def select(self, job_id: str, index: int) -> Optional[Job]:
        """User picked candidate `index`; re-queue the job to download it."""
        job = self.jobs.get(job_id)
        if job is None or job.status != JobStatus.NEEDS_SELECTION or not job.candidates:
            return None
        if not 0 <= index < len(job.candidates):
            raise IndexError(index)
        job.selected = job.candidates[index]
        job.candidates = None
        job.status = JobStatus.QUEUED
        job.progress = 0.0
        try:
            self._queue.put_nowait(job.id)
        except asyncio.QueueFull:
            job.status = JobStatus.NEEDS_SELECTION
            raise
        await self._broadcast(job)
        return job

    def mark_done(self, job: Job) -> None:
        """Called after the user has fetched the file."""
        job.status = JobStatus.DONE
        job.completed_at = datetime.now(timezone.utc)
        self._delete_files(job)
        job.file_path = None
        if self._loop:
            self._loop.create_task(self._broadcast(job))

    def snapshot(self) -> list[dict]:
        return [j.public_dict() for j in sorted(self.jobs.values(), key=lambda j: j.created_at)]

    # -- workers -----------------------------------------------------------

    async def _worker(self, index: int) -> None:
        while True:
            job_id = await self._queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.status != JobStatus.QUEUED:
                continue
            if job_id in self._cancel_flags:
                self._cancel_flags.discard(job_id)
                continue
            await self._run_job(job)

    async def _run_job(self, job: Job) -> None:
        loop = asyncio.get_running_loop()

        from .handlers._ytdlp_common import derive_stream_headers, write_cookiefile

        output_dir = Path(settings.tmp_dir) / job.id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Materialize the user's browser cookies into a tmpfs file, then drop
        # the in-memory copy. The file is removed in the finally block below.
        cookiefile: Optional[Path] = None
        if job.cookies:
            cookiefile = output_dir / "_cookies.txt"
            try:
                write_cookiefile(job.cookies, job.url, cookiefile)
            except Exception:
                logger.warning("Job %s: failed to write cookie file; ignoring cookies", job.id)
                cookiefile = None
            finally:
                job.cookies = None

        def on_progress(event: dict) -> None:
            loop.call_soon_threadsafe(self._apply_progress, job, event)

        def make_ctx() -> DownloadContext:
            # Fresh context per attempt: handlers mutate headers in place.
            return DownloadContext(
                output_dir=output_dir,
                headers=derive_stream_headers(job.url, job.referer),
                on_progress=on_progress,
                is_cancelled=lambda: job.id in self._cancel_flags,
                cookiefile=cookiefile,
            )

        try:
            result = None
            needs_selection: Optional[NeedsSelection] = None
            errors: list[str] = []
            # Resume after user selection: replay only the handler that produced
            # the candidates (it reads job.selected and downloads directly).
            if job.selected:
                handlers = [h for h in registry.resolve_all(job.url) if h.name == job.handler]
            else:
                # Fallback chain: try every matching handler in priority order.
                handlers = registry.resolve_all(job.url)
            for handler in handlers:
                job.handler = handler.name
                job.progress = 0.0
                job.status = JobStatus.DOWNLOADING
                await self._broadcast(job)
                try:
                    result = await asyncio.to_thread(handler.download, job, make_ctx())
                    break
                except CancelledByUser:
                    raise
                except NeedsSelection as ns:
                    needs_selection = ns
                    break
                except Exception as exc:
                    if job.id in self._cancel_flags:
                        raise CancelledByUser() from exc
                    logger.info("Job %s: handler %s failed: %s", job.id, handler.name, exc)
                    audit("handler_failed", job.id, handler=handler.name, error=str(exc)[:600])
                    errors.append(f"[{handler.name}] {str(exc)[:600]}")
            if needs_selection is not None:
                # Park the job until the user picks; no completed_at so the
                # cleanup loop leaves it alone while waiting.
                job.candidates = needs_selection.candidates
                job.status = JobStatus.NEEDS_SELECTION
                job.progress = 0.0
                audit(
                    "job_needs_selection",
                    job.id,
                    url=job.url,
                    count=len(needs_selection.candidates),
                )
                return
            if result is None:
                raise RuntimeError(" | ".join(errors) or "no handler matched")
            job.file_path = str(result.file_path)
            job.title = result.title
            job.filename = result.filename
            job.filesize = result.filesize
            job.progress = 100.0
            job.speed = None
            job.eta = None
            job.status = JobStatus.READY
            job.completed_at = datetime.now(timezone.utc)
            audit(
                "job_ready",
                job.id,
                url=job.url,
                handler=job.handler,
                title=job.title,
                filename=job.filename,
                filesize=job.filesize,
            )
        except CancelledByUser:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
            self._delete_files(job)
            audit("job_cancelled", job.id, url=job.url)
        except Exception as exc:
            logger.error("Job %s failed: %s", job.id, exc)
            job.status = JobStatus.FAILED
            job.error = str(exc)[:1500]
            job.completed_at = datetime.now(timezone.utc)
            self._delete_files(job)
            audit("job_failed", job.id, url=job.url, error=job.error)
        finally:
            # Cookies are credentials: remove the temp file as soon as the
            # download finishes, well before the video's own TTL.
            if cookiefile is not None:
                cookiefile.unlink(missing_ok=True)
            self._cancel_flags.discard(job.id)
            await self._broadcast(job)

    def _apply_progress(self, job: Job, event: dict) -> None:
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.PROCESSING):
            return
        if event.get("status") == "processing":
            job.status = JobStatus.PROCESSING
        job.progress = event.get("progress", job.progress)
        job.speed = event.get("speed")
        job.eta = event.get("eta")
        job.downloaded = event.get("downloaded")
        # Populate filesize from yt-dlp's total-bytes estimate so the frontend
        # can show "X / Y" before the real size is known at completion.
        if event.get("total") and not job.filesize:
            job.filesize = event.get("total")
        if self._loop:
            self._loop.create_task(self._broadcast(job))

    # -- cleanup -----------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.cleanup_interval_seconds)
            now = datetime.now(timezone.utc)
            for job in list(self.jobs.values()):
                if not job.completed_at:
                    continue
                age = (now - job.completed_at).total_seconds()
                if age <= settings.file_ttl_seconds:
                    continue
                # READY: delete the file and emit an audit event before removal.
                if job.status == JobStatus.READY:
                    self._delete_files(job)
                    audit("job_expired", job.id, url=job.url, filename=job.filename)
                # All terminal jobs (ready/done/failed/cancelled) disappear from
                # the queue after TTL so the list stays clean.
                del self.jobs[job.id]
                await ws_manager.broadcast({"type": "job_removed", "id": job.id})

    def _delete_files(self, job: Job) -> None:
        job_dir = Path(settings.tmp_dir) / job.id
        shutil.rmtree(job_dir, ignore_errors=True)

    async def _broadcast(self, job: Job) -> None:
        await ws_manager.broadcast({"type": "job_update", "job": job.public_dict()})


job_queue = JobQueue()
