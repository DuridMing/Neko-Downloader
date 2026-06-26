from urllib.parse import urlparse

from ..models import DownloadContext, DownloadResult, Job
from ._ytdlp_common import run_ytdlp
from .base import DownloadHandler


class DirectStreamHandler(DownloadHandler):
    """Direct URL to a DASH manifest (.mpd) or a plain media file
    (.mp4/.webm/...) served by a CDN.

    Distinct from the catch-all because that one strips Origin/Referer (right
    for platform extractors, wrong for raw CDN URLs that gate on them). Here we
    keep the derived headers — same reason m3u8 has its own handler. yt-dlp
    fetches the manifest/file and ffmpeg muxes to mp4 when needed.
    """

    name = "stream"

    # DASH manifests + the common progressive/container extensions. HLS has its
    # own handler (needs hls_prefer_native), so .m3u8 is deliberately absent.
    # ponytail: one handler for all of these since they download identically;
    # split per-format only when one needs different yt-dlp opts (e.g. DRM).
    EXTS = (".mpd", ".mp4", ".m4v", ".webm", ".mkv", ".mov", ".flv", ".ts")

    def can_handle(self, url: str) -> bool:
        return urlparse(url).path.lower().endswith(self.EXTS)

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        return run_ytdlp(job, ctx)
