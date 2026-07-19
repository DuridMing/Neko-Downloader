"""myfans.jp — paid fan platform with no yt-dlp extractor.

Its paid HLS is only returned by a private JSON API when an
'Authorization: Token token=<t>' header is sent. The logged-in SPA holds that
token in localStorage (not a cookie the browser auto-replays), so neither a
pasted cookie nor the browser sniffer ever reaches the paid stream — the
sniffer only ever sees the free preview clip. So we call the API ourselves
with the user's token and hand the resulting HLS URL to the shared downloader.

Token: on myfans.jp open DevTools ▸ Application ▸ Local Storage, copy the auth
token value, and paste it into the per-job cookie field as:

    _mfans_token=<value>

API shape (v2): GET /posts/{id} -> {free, subscribed, videos:{main:[{resolution,url}]}}.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

from ..models import DownloadContext, DownloadResult, Job
from ._hls_png import run_hls
from ._ytdlp_common import BROWSER_UA, cookie_opts
from .base import DownloadHandler

logger = logging.getLogger("neko.myfans")

API_POST = "https://api.myfans.jp/api/v2/posts/{post_id}"
RES_PRIORITY = ("uhd", "fhd", "hd", "sd", "ld")
# Post pages: myfans.jp/<user>/posts/<id> or myfans.jp/posts/<id>.
POST_RE = re.compile(r"://(?:www\.)?myfans\.jp/(?:[^/]+/)?posts/([A-Za-z0-9-]+)", re.I)


def _post_id(url: str) -> str | None:
    m = POST_RE.search(url)
    return m.group(1) if m else None


def _token(cookiefile: Path | None) -> str | None:
    """myfans auth token from the user's pasted cookies: a cookie named
    '_mfans_token' (or, failing that, any cookie whose name contains 'token')."""
    if not cookiefile or not cookiefile.is_file():
        return None
    fallback = None
    for line in cookiefile.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        name, value = parts[5], parts[6].strip()
        if name == "_mfans_token":
            return value
        if "token" in name.lower() and fallback is None:
            fallback = value
    return fallback


def _best_video_url(data: dict) -> str | None:
    """Highest-quality master-playlist URL from the post's video variants."""
    variants = {
        v["resolution"]: v["url"]
        for v in data.get("videos", {}).get("main", [])
        if v.get("resolution") and v.get("url")
    }
    for res in RES_PRIORITY:
        if res in variants:
            return variants[res]
    return next(iter(variants.values()), None)


class MyfansHandler(DownloadHandler):
    name = "myfans"

    def can_handle(self, url: str) -> bool:
        return _post_id(url) is not None

    def download(self, job: Job, ctx: DownloadContext) -> DownloadResult:
        post_id = _post_id(job.url)
        cf = cookie_opts(ctx.cookiefile).get("cookiefile")
        token = _token(Path(cf)) if cf else None
        if not token:
            raise RuntimeError(
                "myfans needs your login token — paste '_mfans_token=<value>' into "
                "the cookie field (DevTools ▸ Application ▸ Local Storage on myfans.jp)."
            )

        auth = f"Token token={token}"
        req = urllib.request.Request(
            API_POST.format(post_id=post_id),
            headers={"Authorization": auth, "User-Agent": BROWSER_UA, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("myfans token rejected (expired or invalid) — grab a fresh one")
            raise RuntimeError(f"myfans API error {exc.code} for post {post_id}") from exc

        # free=True is watchable by anyone; a paid post needs an active sub/purchase.
        if data.get("free") is False and not data.get("subscribed"):
            raise RuntimeError(
                "No access to this post — your account hasn't subscribed to / purchased it"
            )

        video_url = _best_video_url(data)
        if not video_url:
            raise RuntimeError("Post has no downloadable video (image post, or preview-only)")

        # The CDN (content.mfcdn.jp) auth is signed into the URL path, not a
        # header — it sends NO Authorization and only checks Origin/Referer. So
        # the token stays on the API call; forwarding it to the CDN would risk a
        # reject. Origin/Referer must be myfans.jp for the signed URL to serve.
        ctx.headers["Origin"] = "https://myfans.jp"
        ctx.headers["Referer"] = "https://myfans.jp/"
        ctx.headers.setdefault("User-Agent", BROWSER_UA)
        logger.info("Job %s: myfans post %s, downloading paid stream", job.id, post_id)
        return run_hls(job, ctx, video_url)
