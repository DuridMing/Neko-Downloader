from urllib.parse import urlparse

from ..models import DownloadContext, DownloadResult, Job
from ._ytdlp_common import run_ytdlp
from .base import DownloadHandler


class M3u8Handler(DownloadHandler):
    """Raw HLS (.m3u8) playlist URLs, merged to mp4 via ffmpeg."""

    name = "m3u8"

    def can_handle(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(".m3u8") or path.endswith(".m3u")

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        return run_ytdlp(
            job,
            ctx,
            extra_opts={
                # Raw playlists have no metadata; name the file by host + job id.
                "outtmpl": str(ctx.output_dir / f"{urlparse(job.url).hostname}_{job.id}.%(ext)s"),
                # Native downloader fetches fragments itself: per-fragment
                # progress and cancel work; ffmpeg only remuxes at the end.
                "hls_prefer_native": True,
            },
        )
