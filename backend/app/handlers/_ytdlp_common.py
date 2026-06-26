"""Shared yt-dlp plumbing reusable by any handler built on yt-dlp."""

import re
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

from ..config import settings
from ..models import DownloadContext, DownloadResult, Job

# Single recent-Chrome UA shared by yt-dlp requests and the browser sniffer so
# the two never disagree (a mismatch is itself a bot tell).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _default_impersonate():
    """Best available curl_cffi Chrome TLS/HTTP2 fingerprint, or None if the
    optional curl_cffi dependency is missing (then yt-dlp uses plain urllib)."""
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        if ydl._get_available_impersonate_targets():
            return ImpersonateTarget.from_str("chrome")
    except Exception:
        pass
    return None


# Resolved once at import: impersonating a real browser's TLS handshake defeats
# JA3/fingerprint-based bot blocks (Cloudflare et al.) that a bare client trips.
IMPERSONATE_TARGET = _default_impersonate()


def derive_stream_headers(url: str, referer: str | None = None) -> dict[str, str]:
    """Derive Origin/Referer for raw stream URLs whose CDN checks them.

    Falls back to the stream URL's own origin; a user-supplied referer wins.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "Origin": origin,
        "Referer": referer or f"{origin}/",
        "User-Agent": BROWSER_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "cors",
    }


def _looks_like_netscape(text: str) -> bool:
    head = text.lstrip()
    return "\t" in text or head.startswith("# Netscape") or head.startswith("# HTTP Cookie")


def write_cookiefile(text: str, url: str, dest: Path) -> None:
    """Write user-supplied cookies to a Netscape cookies.txt yt-dlp can read.

    Accepts either a Netscape body or a raw "name=value; name2=value2" header
    (in which case it's bound to the target URL's domain).
    """
    text = text.strip()
    if _looks_like_netscape(text):
        content = text if text.lstrip().startswith("#") else "# Netscape HTTP Cookie File\n" + text
    else:
        host = (urlparse(url).hostname or "").lstrip(".")
        domain = f".{host}" if host else ""
        lines = ["# Netscape HTTP Cookie File"]
        for pair in text.split(";"):
            name, sep, value = pair.strip().partition("=")
            if not sep or not name:
                continue
            lines.append("\t".join([domain, "TRUE", "/", "TRUE", "0", name.strip(), value.strip()]))
        content = "\n".join(lines)
    dest.write_text(content + "\n", encoding="utf-8")
    dest.chmod(0o600)  # cookies are credentials


def cookie_opts(cookiefile: Path | None = None) -> dict:
    """yt-dlp cookie source. Priority: per-request cookie file (user's browser)
    > system cookies_file > system browser profile > none (no auth)."""
    if cookiefile and cookiefile.is_file():
        return {"cookiefile": str(cookiefile)}
    if settings.cookies_file and Path(settings.cookies_file).is_file():
        return {"cookiefile": settings.cookies_file}
    if settings.cookies_from_browser:
        browser, _, profile = settings.cookies_from_browser.partition(":")
        return {
            "cookiesfrombrowser": (browser.strip().lower(), profile.strip() or None, None, None)
        }
    return {}


class _ErrorCapture:
    """Buffers yt-dlp/ffmpeg output so a generic failure can be explained.

    yt-dlp's ffmpeg postprocessor raises with only the *last* line of ffmpeg
    stderr (usually the useless "Conversion failed!"); the real cause (e.g.
    "No space left on device") is dumped via write_debug, which is a no-op
    unless verbose + a logger are set. We buffer the tail and append it to the
    raised error so failures are diagnosable.
    """

    def __init__(self) -> None:
        self.lines: deque[str] = deque(maxlen=80)

    def debug(self, msg: str) -> None:
        self.lines.append(msg)

    def info(self, msg: str) -> None:  # progress noise; ignore
        pass

    def warning(self, msg: str) -> None:
        self.lines.append(msg)

    def error(self, msg: str) -> None:
        self.lines.append(msg)

    def tail(self, n: int = 6) -> str:
        # Flatten (the ffmpeg stderr arrives as one multi-line entry) and keep
        # the last n lines — the real cause sits just above "Conversion failed!".
        flat: list[str] = []
        for entry in self.lines:
            flat.extend(str(entry).splitlines())
        meaningful = [ln for ln in flat if ln.strip() and not ln.startswith("[debug] ")]
        return "\n".join(meaningful[-n:]).strip()


def run_ytdlp(
    job: Job,
    ctx: DownloadContext,
    extra_opts: dict | None = None,
    url: str | None = None,
) -> DownloadResult:
    """Run a yt-dlp download with progress/cancel bridged through the context.

    `url` overrides job.url — used by handlers that discover the real stream
    URL themselves (e.g. browser sniffing).
    """

    def progress_hook(d: dict) -> None:
        ctx.check_cancelled()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            ctx.on_progress(
                {
                    "status": "downloading",
                    "progress": round(downloaded / total * 100, 1) if total else 0.0,
                    "speed": _ANSI_RE.sub("", d.get("_speed_str", "")).strip() or None,
                    "eta": _ANSI_RE.sub("", d.get("_eta_str", "")).strip() or None,
                    "downloaded": downloaded or None,
                    "total": total or None,
                }
            )
        elif d["status"] == "finished":
            ctx.on_progress({"status": "processing", "progress": 100.0})

    opts: dict = {
        "outtmpl": str(ctx.output_dir / "%(title).120B.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "http_headers": ctx.headers,
        "progress_hooks": [progress_hook],
        "retries": 5,
        "fragment_retries": 10,
        "socket_timeout": 30,
        # verbose + logger route ffmpeg stderr into errlog so postprocessing
        # failures carry their real cause; logger keeps it off the screen.
        "verbose": True,
        "no_warnings": True,
        "noprogress": True,
    }
    errlog = _ErrorCapture()
    opts["logger"] = errlog
    if IMPERSONATE_TARGET is not None:
        opts["impersonate"] = IMPERSONATE_TARGET
    opts.update(cookie_opts(ctx.cookiefile))
    if extra_opts:
        opts.update(extra_opts)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url or job.url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            file_path = Path(ydl.prepare_filename(info))
            # After merge the extension may differ from prepare_filename's guess.
            if not file_path.exists():
                candidates = sorted(
                    ctx.output_dir.glob("*"), key=lambda p: p.stat().st_size, reverse=True
                )
                if not candidates:
                    raise RuntimeError("Download produced no output file")
                file_path = candidates[0]
    except Exception as exc:
        detail = errlog.tail()
        if detail and str(exc) not in detail:
            raise RuntimeError(f"{exc}\n--- ffmpeg/yt-dlp output ---\n{detail}") from exc
        raise

    return DownloadResult(
        file_path=file_path,
        title=info.get("title") or file_path.stem,
        filename=file_path.name,
        filesize=file_path.stat().st_size,
    )
