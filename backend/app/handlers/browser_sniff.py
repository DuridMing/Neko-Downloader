"""Headless-browser fallback: load the page, intercept network traffic to
find the real media stream (m3u8/mpd/mp4) and its required headers, then
hand the captured URL to yt-dlp."""

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from ..config import settings
from ..models import DownloadContext, DownloadResult, Job, NeedsSelection
from ._hls_png import run_hls
from ._ytdlp_common import BROWSER_UA, cookie_opts, run_ytdlp
from .base import DownloadHandler

# Patches the navigator properties headless Chromium gives away, which
# Cloudflare/DataDome and friends fingerprint. Runs before any page script.
STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}};
const _query = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (
    p && p.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : _query(p)
);
const _getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';            // UNMASKED_VENDOR_WEBGL
    if (p === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
    return _getParameter.call(this, p);
};
"""

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
    # Fake-player overlays (ad-monetized sites hide the real player behind a
    # poster div that must be clicked to load the stream) come first.
    "#clickfakeplayer",
    ".fakeplayer",
    ".vjs-big-play-button",
    ".plyr__control--overlaid",
    ".jw-display-icon-display",
    "button[aria-label*='play' i]",
    "button[title*='play' i]",
    "video",
)

FORWARDED_HEADERS = ("referer", "origin", "user-agent", "cookie")

# Many players don't request the media directly — they fetch a JSON/JS config
# (XHR/fetch) that *contains* the real m3u8/mp4 URL. This pulls those URLs out
# of a response body. \\/ handles JSON-escaped slashes.
MEDIA_URL_RE = re.compile(
    r"https?://[^\s\"'<>\\)]+?\.(?:m3u8|m3u|mpd|mp4|m4v|webm|mkv|mov|flv|ts)"
    r"(?:\?[^\s\"'<>\\)]*)?",
    re.IGNORECASE,
)
# Don't scan binary bodies for embedded URLs.
SKIP_SCAN_CT = ("image/", "video/", "audio/", "font/")
MAX_SCAN_BYTES = 2_000_000

# Ad/tracker hosts to abort outright: kills pop-unders, speeds up sniffing, and
# stops their media from polluting the candidate list. Substring match on host.
# ponytail: small denylist; extend when a new ad network slips through.
AD_HOST_FRAGMENTS = (
    "doubleclick", "exoclick", "juicyads", "trafficjunky", "popads", "popcash",
    "propellerads", "adsterra", "pemsrv", "dtscout", "crwdcntrl", "sexchatters",
    "bkcdn", "saawsedge", "adnxs", "outbrain", "taboola", "mgid", "medfoodsafety",
    # tsyndicate ("traffic syndicate") injects pre-roll ad clips from the *main*
    # frame, so the same-site frame filter can't catch them — deny by host.
    "tsyndicate",
)

# A third-party (cross-site) media smaller than this is almost certainly an ad
# clip, not the real video. Same-site media of any size is kept.
MIN_THIRD_PARTY_BYTES = 3 * 1024 * 1024


def _reg_domain(netloc: str) -> str:
    """Registrable-domain approximation: last two labels. ponytail: good enough
    to tell 'same site' from 'third-party ad frame'; swap in tldextract only if
    a multi-part TLD (.co.uk) actually misfires in practice."""
    host = netloc.split(":")[0].lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _is_ad_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(frag in host for frag in AD_HOST_FRAGMENTS)


def _cookies_for_playwright(cookiefile: str) -> list[dict]:
    """Netscape cookies.txt -> Playwright add_cookies() dicts.

    Parsed by hand rather than stdlib MozillaCookieJar because browser exports
    prefix auth cookies with '#HttpOnly_', which MozillaCookieJar silently
    drops as comments — and those are exactly the cookies a login wall needs.
    """
    cookies = []
    for line in Path(cookiefile).read_text(encoding="utf-8").splitlines():
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_") :]
        elif not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _flag, path, secure, expires, name, value = parts
        try:
            exp = float(expires)
        except ValueError:
            exp = 0.0
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path or "/",
                "expires": exp if exp > 0 else -1,  # 0/blank = session cookie
                "secure": secure.strip().upper() == "TRUE",
                "httpOnly": http_only,
            }
        )
    return cookies


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
        # A user-selected candidate (resume after NEEDS_SELECTION) skips sniffing.
        if job.selected:
            return self._download_candidate(job, ctx, job.selected)

        # Fake-player sites are probabilistic: sometimes the real player just
        # doesn't initialize in one pass. A second attempt with a fresh browser
        # markedly raises the hit rate for a few extra seconds.
        candidates = self._sniff(job, ctx)
        if not candidates:
            logger.info("Job %s: first sniff empty, retrying once", job.id)
            candidates = self._sniff(job, ctx)
        if not candidates:
            raise RuntimeError("Browser sniffing found no media stream on the page")

        # One playlist is authoritative; a single survivor is unambiguous too.
        playlists = [c for c in candidates if c["kind"] in ("m3u8", "mpd")]
        if len(playlists) == 1:
            return self._download_candidate(job, ctx, playlists[0])
        if len(candidates) == 1:
            return self._download_candidate(job, ctx, candidates[0])
        # Genuinely ambiguous (e.g. multiple progressive MP4s, multi-quality):
        # let the user pick rather than guess and hand back the wrong video.
        logger.info("Job %s: %d ambiguous streams, asking user", job.id, len(candidates))
        raise NeedsSelection(candidates)

    def _download_candidate(self, job: Job, ctx: DownloadContext, cand: dict) -> DownloadResult:
        logger.info("Job %s sniffed %s stream: %s", job.id, cand["kind"], cand["url"])
        ctx.headers.update(cand["headers"])
        if cand["kind"] == "m3u8":
            # HLS may serve image-prefixed segments; run_hls de-stuffs or defers.
            return run_hls(job, ctx, cand["url"])
        return run_ytdlp(job, ctx, url=cand["url"])

    def _sniff(self, job: Job, ctx: DownloadContext) -> list[dict]:
        page_domain = _reg_domain(urlparse(job.url).netloc)
        # url -> candidate; we keep the originating frame + size to filter ads.
        found: dict[str, dict] = {}

        def record(url, kind, req_headers, frame_url, size):
            if url in found or _is_ad_host(url):
                return
            headers = {
                k.title(): v for k, v in req_headers.items() if k.lower() in FORWARDED_HEADERS
            }
            found[url] = {
                "url": url,
                "kind": kind,
                "headers": headers,
                "frame": _reg_domain(urlparse(frame_url or "").netloc),
                "size": size,
            }

        def on_request(req):
            kind = _classify(req.url)
            if kind:
                fr = req.frame.url if req.frame else ""
                record(req.url, kind, req.headers, fr, None)

        def on_response(resp):
            ct = resp.headers.get("content-type", "")
            kind = _classify(resp.url, ct)
            fr = resp.frame.url if resp.frame else ""
            if kind:
                try:
                    size = int(resp.headers.get("content-length", "") or 0) or None
                except ValueError:
                    size = None
                if resp.url in found and size and not found[resp.url].get("size"):
                    found[resp.url]["size"] = size
                else:
                    record(resp.url, kind, resp.request.headers, fr, size)
                return
            # Not a media URL itself: scan XHR/fetch response bodies for an
            # embedded stream URL (players often get the m3u8 from a JSON API).
            # Only XHR/fetch — scanning static .js libraries picks up their demo
            # URLs (e.g. plyr.io's blank.mp4). Same-site only, so an ad API
            # returning a media URL can't hijack the result.
            ctl = ct.lower()
            if (
                resp.request.resource_type in ("xhr", "fetch")
                and not ctl.startswith(SKIP_SCAN_CT)
                and not _is_ad_host(resp.url)
                and _reg_domain(urlparse(fr).netloc) == page_domain
            ):
                try:
                    body = resp.text()
                except Exception:
                    return
                if not body or len(body) > MAX_SCAN_BYTES:
                    return
                for mt in MEDIA_URL_RE.finditer(body.replace("\\/", "/")):
                    u = mt.group(0)
                    k = _classify(u)
                    if k:
                        record(u, k, resp.request.headers, fr, None)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--autoplay-policy=no-user-gesture-required",
                    "--mute-audio",
                    # Prevents Chromium from advertising automation to bot-detection.
                    "--disable-blink-features=AutomationControlled",
                    # Containers (Podman/Docker) give /dev/shm only 64MB by
                    # default, which crashes Chromium; use /tmp instead.
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=BROWSER_UA,
                    locale="en-US",
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                # Abort ad/tracker hosts before they load: no pop-unders to fight
                # and no ad media in the candidate pool.
                context.route(
                    "**/*",
                    lambda route: route.abort()
                    if _is_ad_host(route.request.url)
                    else route.continue_(),
                )
                # Login-walled sites (paid fan platforms etc.): browse with the
                # user's session, same source priority as yt-dlp (per-job paste
                # > system cookies file). Sniffed requests then carry the auth
                # cookie, which FORWARDED_HEADERS passes on to the downloader.
                cookiefile = cookie_opts(ctx.cookiefile).get("cookiefile")
                if cookiefile:
                    try:
                        context.add_cookies(_cookies_for_playwright(cookiefile))
                    except Exception:
                        logger.warning("Job %s: cookie injection failed", job.id, exc_info=True)
                page = context.new_page()
                page.add_init_script(STEALTH_INIT_JS)
                # Pop-unders/new tabs are ads; close them so the click that
                # spawned one still falls through to the real player.
                context.on("page", lambda pg: pg.close() if pg != page else None)
                page.on("request", on_request)
                page.on("response", on_response)
                page.goto(job.url, wait_until="domcontentloaded", timeout=30_000)

                # JS .click() dispatches straight to the element, bypassing ad
                # overlays that hit-test-steal a coordinate click (even a forced
                # one, since the browser still hit-tests the point).
                trigger_js = (
                    "(sels) => { for (const s of sels) "
                    "document.querySelectorAll(s).forEach(e => { try { e.click(); } catch(_){} }); }"
                )
                deadline = time.time() + settings.sniff_timeout_seconds
                while time.time() < deadline:
                    ctx.check_cancelled()
                    # A playlist is authoritative; stop as soon as one shows up.
                    if any(c["kind"] in ("m3u8", "mpd") for c in found.values()):
                        break
                    # These fake players need several clicks (the first ones open
                    # ads) before the real player loads, so re-click every round.
                    try:
                        page.evaluate(trigger_js, list(PLAY_SELECTORS))
                    except Exception:
                        pass
                    # A real pointer click too, for handlers that want a trusted
                    # pointer event at the element's coordinates.
                    for selector in ("#clickfakeplayer", "video"):
                        try:
                            page.click(selector, timeout=300, force=True)
                        except Exception:
                            continue
                    page.wait_for_timeout(1_500)
            finally:
                browser.close()

        return self._filter(found.values(), page_domain)

    @staticmethod
    def _filter(cands, page_domain: str) -> list[dict]:
        """Drop obvious ad clips (third-party frame AND small), then rank:
        playlists first, then larger media. Same-site media is always kept."""
        kept = [
            c
            for c in cands
            if c["frame"] == page_domain
            or not c.get("size")
            or c["size"] >= MIN_THIRD_PARTY_BYTES
        ]
        return sorted(
            kept,
            key=lambda c: (KIND_PRIORITY[c["kind"]], -(c.get("size") or 0)),
        )
