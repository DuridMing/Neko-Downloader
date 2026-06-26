from urllib.parse import urlparse

from ..models import DownloadContext, DownloadResult, Job
from ._hls_png import run_hls
from .base import DownloadHandler


class M3u8Handler(DownloadHandler):
    """Raw HLS (.m3u8) playlist URLs, merged to mp4 via ffmpeg."""

    name = "m3u8"

    def can_handle(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(".m3u8") or path.endswith(".m3u")

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        # run_hls de-stuffs image-prefixed segments and otherwise defers to
        # yt-dlp's native HLS (per-fragment progress/cancel, ffmpeg remux).
        return run_hls(job, ctx, job.url)
