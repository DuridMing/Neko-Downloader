"""Headless-browser fallback: load the page, intercept network traffic to
find the real media stream (m3u8/mpd/mp4) and its required headers, then
hand the captured URL to yt-dlp."""

import logging
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from ..config import settings
from ..models import DownloadContext, DownloadResult, Job
from ._ytdlp_common import run_ytdlp
from .base import DownloadHandler

logger = logging.getLogger("neko.sniffer")

# Lower number = better candidate.
KIND_PRIORITY = {"m3u8": 0, "mpd": 1, "media": 2}

MEDIA_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".flv", ".ts")
STREAM_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl": "m3u8",
    "application/x-mpegurl": "m3u8",
    "audio/mpegurl": "m3u8",
    "application/dash+xml": "mpd",
}

PLAY_SELECTORS = (
    "video",
    "button[aria-label*='play' i]",
    "button[title*='play' i]",
    ".vjs-big-play-button",
    ".plyr__control--overlaid",
    ".jw-display-icon-display",
)

FORWARDED_HEADERS = ("referer", "origin", "user-agent", "cookie")


def _classify(url: str, content_type: str = "") -> str | None:
    ct = content_type.split(";")[0].strip().lower()
    if ct in STREAM_CONTENT_TYPES:
        return STREAM_CONTENT_TYPES[ct]
    path = urlparse(url).path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return "m3u8"
    if path.endswith(".mpd"):
        return "mpd"
    if path.endswith(MEDIA_EXTS):
        return "media"
    return None


class BrowserSniffHandler(DownloadHandler):
    name = "sniffer"

    def can_handle(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        candidate = self._sniff(job, ctx)
        if candidate is None:
            raise RuntimeError("Browser sniffing found no media stream on the page")
        logger.info("Job %s sniffed %s stream: %s", job.id, candidate["kind"], candidate["url"])
        ctx.headers.update(candidate["headers"])
        return run_ytdlp(job, ctx, url=candidate["url"])

    def _sniff(self, job: Job, ctx: DownloadContext) -> dict | None:
        candidates: dict[str, dict] = {}

        def on_request(req):
            kind = _classify(req.url)
            if kind and req.url not in candidates:
                headers = {
                    k.title(): v
                    for k, v in req.headers.items()
                    if k.lower() in FORWARDED_HEADERS
                }
                candidates[req.url] = {"url": req.url, "kind": kind, "headers": headers}

        def on_response(resp):
            kind = _classify(resp.url, resp.headers.get("content-type", ""))
            if kind and resp.url not in candidates:
                headers = {
                    k.title(): v
                    for k, v in resp.request.headers.items()
                    if k.lower() in FORWARDED_HEADERS
                }
                candidates[resp.url] = {"url": resp.url, "kind": kind, "headers": headers}

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
            )
            try:
                page = browser.new_context(viewport={"width": 1280, "height": 720}).new_page()
                page.on("request", on_request)
                page.on("response", on_response)
                page.goto(job.url, wait_until="domcontentloaded", timeout=30_000)

                deadline = time.time() + settings.sniff_timeout_seconds
                clicked = False
                while time.time() < deadline:
                    ctx.check_cancelled()
                    # A playlist is authoritative; stop as soon as one shows up.
                    if any(c["kind"] in ("m3u8", "mpd") for c in candidates.values()):
                        break
                    if not clicked:
                        clicked = True
                        for selector in PLAY_SELECTORS:
                            try:
                                page.click(selector, timeout=500)
                            except Exception:
                                continue
                    page.wait_for_timeout(1_000)
            finally:
                browser.close()

        if not candidates:
            return None
        return min(candidates.values(), key=lambda c: KIND_PRIORITY[c["kind"]])
