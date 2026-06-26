"""Self-check for PNG-prefixed-HLS de-stuffing logic — the TS-offset finder
and playlist parser. No network. Run: `python backend/tests/test_hls_png.py`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.handlers._hls_png import _hls_total_seconds, _parse_playlist, _ts_offset

TS = b"\x47" + b"\x00" * 187


def test_ts_offset_plain():
    assert _ts_offset(TS * 8) == 0


def test_ts_offset_png_prefixed():
    # The real javplayer case: 1x1 PNG (~120B) + 0xFF padding, TS at 205.
    blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * 112 + b"\xff" * 85 + TS * 8
    off = _ts_offset(blob)
    assert off == 205, off
    assert blob[off:].startswith(b"\x47")


def test_ts_offset_none_when_no_ts():
    assert _ts_offset(b"\x89PNG" + b"\x11" * 3000) is None


def test_parse_master_playlist():
    master = (
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nlow.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2\nhttps://h/hi.m3u8\n"
    )
    segs, variants = _parse_playlist(master, "https://h/a/")
    assert segs == []
    assert variants == ["https://h/a/low.m3u8", "https://h/hi.m3u8"]


def test_parse_media_playlist_relative_and_absolute():
    media = "#EXTM3U\n#EXTINF:5,\nseg0.ts\n#EXTINF:5,\nhttps://c/seg1.ts\n#EXT-X-ENDLIST\n"
    segs, variants = _parse_playlist(media, "https://h/a/")
    assert segs == ["https://h/a/seg0.ts", "https://c/seg1.ts"]
    assert variants == []


def test_hls_total_seconds():
    pl = "#EXTM3U\n#EXTINF:4.004000,\na.ts\n#EXTINF:6.706700,\nb.ts\n#EXTINF:1.9,\nc.ts\n"
    assert abs(_hls_total_seconds(pl) - 12.6107) < 1e-4


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
