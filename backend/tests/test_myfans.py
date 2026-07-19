"""Self-check for myfans URL/token/resolution parsing — no network. Run:
python -m pytest, or `python backend/tests/test_myfans.py`."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.handlers.myfans import _best_video_url, _post_id, _token


def test_post_id():
    assert _post_id("https://myfans.jp/creatorname/posts/abc123-def") == "abc123-def"
    assert _post_id("https://www.myfans.jp/posts/xyz789") == "xyz789"
    assert _post_id("https://example.com/posts/nope") is None
    assert _post_id("https://myfans.jp/creatorname") is None


def _cookiefile(body: str) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write(body)
    f.close()
    return Path(f.name)


def test_token_from_named_cookie():
    cf = _cookiefile(
        "# Netscape HTTP Cookie File\n"
        ".myfans.jp\tTRUE\t/\tTRUE\t0\tsomething\telse\n"
        ".myfans.jp\tTRUE\t/\tTRUE\t0\t_mfans_token\tSECRET123\n"
    )
    assert _token(cf) == "SECRET123"


def test_token_fallback_to_any_token_named_cookie():
    cf = _cookiefile(".myfans.jp\tTRUE\t/\tTRUE\t0\tauth_token\tFALLBACK\n")
    assert _token(cf) == "FALLBACK"


def test_token_missing():
    cf = _cookiefile(".myfans.jp\tTRUE\t/\tTRUE\t0\tsession\tnope\n")
    assert _token(cf) is None
    assert _token(None) is None


def test_best_video_url_priority():
    data = {
        "videos": {
            "main": [
                {"resolution": "sd", "url": "https://cdn/sd.m3u8"},
                {"resolution": "fhd", "url": "https://cdn/fhd.m3u8"},
                {"resolution": "hd", "url": "https://cdn/hd.m3u8"},
            ]
        }
    }
    assert _best_video_url(data) == "https://cdn/fhd.m3u8"


def test_best_video_url_none_when_no_videos():
    assert _best_video_url({"videos": {"main": []}}) is None
    assert _best_video_url({}) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
