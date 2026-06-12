from ..models import DownloadContext, DownloadResult, Job
from ._ytdlp_common import run_ytdlp
from .base import DownloadHandler


class YtDlpPlatformHandler(DownloadHandler):
    """Catch-all: yt-dlp's built-in extractors cover thousands of platforms
    and manage their required headers/cookies/signatures automatically."""

    name = "platform"

    def can_handle(self, url: str) -> bool:
        return True

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        # Platform extractors set their own headers; ours would interfere.
        ctx.headers.pop("Origin", None)
        if not job.referer:
            ctx.headers.pop("Referer", None)
        return run_ytdlp(job, ctx)
