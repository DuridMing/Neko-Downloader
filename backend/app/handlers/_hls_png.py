"""HLS where each segment is real MPEG-TS hidden behind a fake image header
(e.g. a 1x1 PNG + padding), an anti-leech trick used by some sites: CDNs/WAFs
and yt-dlp see "an image" and the muxed output has no playable video. The real
player strips the prefix before MSE; we do the same here.

yt-dlp can't strip a per-segment byte prefix, so for these playlists we fetch
segments ourselves, cut each down to its first MPEG-TS sync, concatenate, and
let ffmpeg remux to mp4. Non-prefixed playlists fall back to plain yt-dlp.
"""

import logging
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ..models import DownloadContext, DownloadResult, Job
from ._ytdlp_common import run_ytdlp

logger = logging.getLogger("neko.hls")

TS_PACKET = 188
# How far into a segment we'll scan for the hidden TS payload before giving up.
MAX_PREFIX = 4096


def _ts_offset(data: bytes) -> int | None:
    """First offset whose 0x47 repeats every 188 bytes for several packets —
    the start of the real MPEG-TS payload. None if the segment is plain TS at 0
    already, or no TS found."""
    limit = min(len(data) - TS_PACKET * 6, MAX_PREFIX)
    for i in range(max(limit, 1)):
        if data[i] == 0x47 and all(data[i + TS_PACKET * k] == 0x47 for k in range(1, 6)):
            return i
    return None


def _fetch(url: str, headers: dict[str, str], timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_playlist(text: str, base: str) -> tuple[list[str], list[str]]:
    """Return (segment_urls, variant_urls). A master playlist has variants
    (EXT-X-STREAM-INF); a media playlist has segments."""
    segments, variants = [], []
    lines = text.splitlines()
    is_variant = False
    for line in lines:
        s = line.strip()
        if s.startswith("#EXT-X-STREAM-INF"):
            is_variant = True
            continue
        if not s or s.startswith("#"):
            continue
        url = urljoin(base, s)
        (variants if is_variant else segments).append(url)
        is_variant = False
    return segments, variants


def _resolve_media_playlist(url: str, headers: dict) -> tuple[str, str, list[str]]:
    """Follow a master playlist to its highest-quality variant. Returns
    (playlist_url, playlist_text, segment_urls)."""
    text = _fetch(url, headers).decode("utf-8", "replace")
    segments, variants = _parse_playlist(text, url)
    if segments:
        return url, text, segments
    if variants:
        # Variants are listed low->high bandwidth; take the last (best).
        best = variants[-1]
        text = _fetch(best, headers).decode("utf-8", "replace")
        segs, _ = _parse_playlist(text, best)
        return best, text, segs
    return url, text, []


def run_hls(job: Job, ctx: DownloadContext, url: str) -> DownloadResult:
    """Download an HLS stream, transparently de-stuffing PNG-prefixed segments.
    Falls back to yt-dlp for ordinary (non-prefixed, or encrypted) playlists."""
    try:
        media_url, text, segments = _resolve_media_playlist(url, ctx.headers)
    except Exception as exc:
        logger.info("Job %s: HLS probe failed (%s); using yt-dlp", job.id, exc)
        return run_ytdlp(job, ctx, extra_opts={"hls_prefer_native": True}, url=url)

    # AES-128: ffmpeg fetches the key and decrypts natively. We drive ffmpeg
    # ourselves (not via yt-dlp) because yt-dlp's native HLS silently falls back
    # to ffmpeg for these and then reports no per-fragment progress — the bar
    # would sit at 0%. Driving ffmpeg with -progress gives a real percentage.
    if "METHOD=AES-128" in text and segments:
        return _download_ffmpeg_hls(job, ctx, media_url, text)
    # Other encryption (SAMPLE-AES etc.) or no segments: defer to yt-dlp.
    if not segments or "#EXT-X-KEY" in text:
        return run_ytdlp(job, ctx, extra_opts={"hls_prefer_native": True}, url=url)

    # Peek the first segment: only take over if it's actually image-prefixed TS.
    try:
        first = _fetch(segments[0], ctx.headers)
    except Exception:
        return run_ytdlp(job, ctx, extra_opts={"hls_prefer_native": True}, url=url)
    offset = _ts_offset(first)
    if offset is None or offset == 0:
        # Plain TS (or not TS at all): let yt-dlp do its normal thing.
        return run_ytdlp(job, ctx, extra_opts={"hls_prefer_native": True}, url=url)

    logger.info(
        "Job %s: PNG-prefixed HLS (offset ~%d, %d segments); de-stuffing",
        job.id, offset, len(segments),
    )
    return _download_destuffed(job, ctx, media_url, segments, first)


def _hls_total_seconds(playlist_text: str) -> float:
    return sum(float(m) for m in re.findall(r"#EXTINF:([0-9.]+)", playlist_text))


def _ffmpeg_header_args(headers: dict[str, str]) -> list[str]:
    """ffmpeg CLI args carrying the captured request headers (UA + the rest)."""
    args: list[str] = []
    ua = headers.get("User-Agent")
    if ua:
        args += ["-user_agent", ua]
    other = "".join(f"{k}: {v}\r\n" for k, v in headers.items() if k.lower() != "user-agent")
    if other:
        args += ["-headers", other]
    return args


def _download_ffmpeg_hls(
    job: Job, ctx: DownloadContext, media_url: str, playlist_text: str
) -> DownloadResult:
    """Download (and AES-decrypt) an HLS stream with ffmpeg, reporting real
    progress parsed from ffmpeg's -progress output against the playlist's total
    duration. ffmpeg handles the AES-128 key fetch + decrypt itself."""
    total = _hls_total_seconds(playlist_text)
    out_path = ctx.output_dir / f"{urlparse(job.url).hostname}_{job.id}.mp4"
    errfile = ctx.output_dir / f"{job.id}.ffmpeg.log"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-y", "-loglevel", "error", *_ffmpeg_header_args(ctx.headers),
           "-i", media_url, "-c", "copy", "-movflags", "+faststart",
           "-progress", "pipe:1", str(out_path)]
    logger.info("Job %s: AES-128 HLS via ffmpeg (%.0fs, progress-tracked)", job.id, total)

    with open(errfile, "w") as ef:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True)
        try:
            for line in proc.stdout:
                ctx.check_cancelled()
                line = line.strip()
                if line.startswith("out_time_us=") and total:
                    try:
                        us = int(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    # Cap at 99.9 until ffmpeg exits cleanly (then 100 below).
                    ctx.on_progress({"status": "downloading",
                                     "progress": min(round(us / 1e6 / total * 100, 1), 99.9)})
                elif line.startswith("total_size="):
                    try:
                        ctx.on_progress({"status": "downloading",
                                         "downloaded": int(line.split("=", 1)[1])})
                    except ValueError:
                        pass
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        proc.wait()

    if proc.returncode != 0 or not out_path.exists():
        tail = "\n".join(errfile.read_text(errors="replace").strip().splitlines()[-6:])
        errfile.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg HLS download failed\n--- ffmpeg output ---\n{tail}")
    errfile.unlink(missing_ok=True)
    ctx.on_progress({"status": "processing", "progress": 100.0})
    return DownloadResult(
        file_path=out_path,
        title=urlparse(job.url).hostname or out_path.stem,
        filename=out_path.name,
        filesize=out_path.stat().st_size,
    )


def _download_destuffed(
    job: Job, ctx: DownloadContext, media_url: str, segments: list[str], first: bytes
) -> DownloadResult:
    ts_path = ctx.output_dir / f"{job.id}.ts"
    total = len(segments)
    with open(ts_path, "wb") as out:
        for i, seg_url in enumerate(segments):
            ctx.check_cancelled()
            data = first if i == 0 else _fetch(seg_url, ctx.headers)
            off = _ts_offset(data)
            out.write(data[off:] if off else data)
            ctx.on_progress(
                {
                    "status": "downloading",
                    "progress": round((i + 1) / total * 100, 1),
                    "downloaded": out.tell(),
                }
            )

    ctx.on_progress({"status": "processing", "progress": 100.0})
    out_path = ctx.output_dir / f"{urlparse(job.url).hostname}_{job.id}.mp4"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(ts_path), "-c", "copy",
         "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True,
    )
    ts_path.unlink(missing_ok=True)
    if proc.returncode != 0 or not out_path.exists():
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise RuntimeError(f"ffmpeg remux failed\n--- ffmpeg output ---\n{tail}")

    return DownloadResult(
        file_path=out_path,
        title=urlparse(job.url).hostname or out_path.stem,
        filename=out_path.name,
        filesize=out_path.stat().st_size,
    )
