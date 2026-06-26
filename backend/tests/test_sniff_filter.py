"""Self-check for the sniffer's ad-filter + candidate ranking — the logic that
decides 'is this the real video or an ad clip'. Run: python -m pytest, or just
`python backend/tests/test_sniff_filter.py`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.handlers.browser_sniff import (
    MEDIA_URL_RE,
    BrowserSniffHandler,
    _is_ad_host,
    _reg_domain,
)


def _extract(body):
    """Mirror the handler: unescape JSON slashes, then find media URLs."""
    return [m.group(0) for m in MEDIA_URL_RE.finditer(body.replace("\\/", "/"))]


def c(url, kind="media", frame="javplayer.org", size=None):
    return {"url": url, "kind": kind, "headers": {}, "frame": frame, "size": size}


def test_reg_domain():
    assert _reg_domain("z6v2p9a8.bkcdn.net") == "bkcdn.net"
    assert _reg_domain("javplayer.org") == "javplayer.org"
    assert _reg_domain("cdn.surrit.com:443") == "surrit.com"


def test_ad_host():
    assert _is_ad_host("https://s.pemsrv.com/iframe.php")
    assert _is_ad_host("https://video.saawsedge.com/v/x.mp4")
    assert not _is_ad_host("https://surrit.com/abc/playlist.m3u8")


def test_javplayer_ads_all_dropped():
    # The real failure: three small third-party ad mp4s, no real video present.
    ads = [
        c("https://z6v2p9a8.bkcdn.net/a.mp4", frame="cgw46pe4.xyz", size=89515),
        c("https://z6v2p9a8.bkcdn.net/b.mp4", frame="cgw46pe4.xyz", size=640702),
        c("https://video.saawsedge.com/x.mp4", frame="sexchatters.com", size=1458040),
    ]
    assert BrowserSniffHandler._filter(ads, "javplayer.org") == []


def test_cross_domain_cdn_kept():
    # missav: page is missav.ai, the m3u8 request fires from the MAIN frame
    # (same registrable domain) even though the URL host is surrit.com.
    cands = [c("https://surrit.com/x/playlist.m3u8", kind="m3u8", frame="missav.ai")]
    out = BrowserSniffHandler._filter(cands, "missav.ai")
    assert len(out) == 1 and out[0]["kind"] == "m3u8"


def test_playlist_ranked_above_media_and_largest_first():
    cands = [
        c("https://x/small.mp4", size=5 * 1024 * 1024),
        c("https://x/big.mp4", size=50 * 1024 * 1024),
        c("https://x/p.m3u8", kind="m3u8"),
    ]
    out = BrowserSniffHandler._filter(cands, "x")  # frame defaults to javplayer.org
    # all same-site? no — frame is 'javplayer.org' but page 'x'; sizes >= 3MB keep them
    assert out[0]["kind"] == "m3u8"
    medias = [m["url"] for m in out if m["kind"] == "media"]
    assert medias == ["https://x/big.mp4", "https://x/small.mp4"]


def test_large_third_party_media_survives():
    # A real video served from a third-party embed CDN (big) must NOT be dropped.
    cands = [c("https://cdn.example.net/real.mp4", frame="example.net", size=200 * 1024 * 1024)]
    assert len(BrowserSniffHandler._filter(cands, "javplayer.org")) == 1


def test_extract_json_escaped_url():
    body = '{"sources":[{"file":"https:\\/\\/cdn.x.com\\/a\\/master.m3u8?t=1","type":"hls"}]}'
    assert _extract(body) == ["https://cdn.x.com/a/master.m3u8?t=1"]


def test_extract_multiple_and_ignore_non_media():
    body = '{"poster":"https://x.com/p.jpg","mp4":"https://x.com/v.mp4","hls":"https://x.com/s.m3u8"}'
    assert _extract(body) == ["https://x.com/v.mp4", "https://x.com/s.m3u8"]


def test_extract_none_when_no_media_url():
    assert _extract('{"poster":"https://x.com/p.jpg","api":"https://x.com/data.json"}') == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
