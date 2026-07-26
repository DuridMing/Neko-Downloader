"""Indexing rules: primary-key dedup, cross-channel file dedup, and a
watermark that only ever moves forward."""

from datetime import datetime, timezone

import pytest

from app.telegram.index import TgIndex
from app.telegram.kurigram_source import _media_kind, _normalize_ref, _to_media_item
from app.telegram.types import TgChannel, TgMediaItem, parse_ref


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, _name):  # unset media attributes read as None
        return None


class _Msg(_Stub):
    """Minimal stand-in for a library Message."""

    def __init__(self, media_kind=None, message_id=1, **attrs):
        super().__init__(
            id=message_id,
            chat=_Stub(id=-100_1),
            date=datetime(2026, 7, 25, tzinfo=timezone.utc),
            media=_Stub(value=media_kind) if media_kind else None,
            **attrs,
        )


def _file(**kw):
    kw.setdefault("file_unique_id", "AgADfile")
    return _Stub(**kw)


def item(channel_id=-100_1, message_id=1, document_id=None, **kw) -> TgMediaItem:
    return TgMediaItem(
        channel_id=channel_id,
        message_id=message_id,
        date=datetime(2026, 7, 25, tzinfo=timezone.utc),
        kind=kw.pop("kind", "video"),
        document_id=document_id,
        **kw,
    )


def test_channel_message_pair_is_the_primary_key():
    index = TgIndex()
    assert index.add(item(message_id=7)) is True
    assert index.add(item(message_id=7)) is False, "re-index must not duplicate"
    assert len(index) == 1


def test_same_message_id_in_a_different_channel_is_a_different_item():
    index = TgIndex()
    index.add(item(channel_id=-100_1, message_id=7))
    index.add(item(channel_id=-100_2, message_id=7))
    assert len(index) == 2


def test_same_file_reposted_elsewhere_is_found_for_hardlinking():
    index = TgIndex()
    first = item(channel_id=-100_1, message_id=7, document_id="AgADxyz")
    repost = item(channel_id=-100_2, message_id=99, document_id="AgADxyz")
    index.add(first)
    index.add(repost)
    # Both stay indexed; stage 3 hardlinks the second instead of downloading.
    assert len(index) == 2
    assert index.duplicate_of(repost) == first
    assert index.duplicate_of(first) is None, "first sighting has no original"


def test_items_without_a_document_id_are_never_treated_as_duplicates():
    index = TgIndex()
    a, b = item(message_id=1), item(channel_id=-100_2, message_id=2)
    index.add(a)
    index.add(b)
    assert index.duplicate_of(b) is None


def test_watermark_tracks_the_highest_id_and_tolerates_gaps():
    index = TgIndex()
    for mid in (3, 4, 9, 10, 57):  # deletions leave holes; that is normal
        index.add(item(message_id=mid))
    assert index.watermark(-100_1) == 57


def test_watermark_never_rewinds_when_an_older_message_arrives_late():
    index = TgIndex()
    index.add(item(message_id=100))
    index.add(item(message_id=42))
    assert index.watermark(-100_1) == 100


def test_watermark_advances_past_skipped_non_media_posts():
    """Otherwise a channel whose newest posts are text would be rescanned
    from the same point forever."""
    index = TgIndex()
    index.add(item(message_id=10))
    index.note_scanned(-100_1, 11)  # a text post
    assert index.watermark(-100_1) == 11


def test_unscanned_channel_starts_at_zero():
    assert TgIndex().watermark(-100_999) == 0


def test_filters_narrow_the_browse_list_before_downloading():
    index = TgIndex()
    index.add(item(message_id=1, kind="video", file_size=500 * 1024 * 1024,
                   file_name="ep01.mp4"))
    index.add(item(message_id=2, kind="photo", file_size=2048, file_name="thumb.jpg"))
    index.add(item(message_id=3, kind="video", file_size=10 * 1024,
                   caption="tiny clip"))

    assert [i.message_id for i in index.items(kind="video")] == [1, 3]
    assert [i.message_id for i in index.items(min_size=1024 * 1024)] == [1]
    assert [i.message_id for i in index.items(search="TINY")] == [3]
    assert [i.message_id for i in index.items(search="ep01")] == [1]


def test_kind_video_also_matches_videos_uploaded_as_documents():
    """Whole channels post their videos as files; --kind video listing none of
    them is what made the filter useless."""
    index = TgIndex()
    index.add(item(message_id=1, kind="document", mime_type="video/x-matroska"))
    index.add(item(message_id=2, kind="document", mime_type="application/zip"))
    assert [i.message_id for i in index.items(kind="video")] == [1]


def test_channel_is_private_when_it_has_no_public_username():
    assert TgChannel(id=-1, title="x").is_private is True
    assert TgChannel(id=-1, title="x", username="pub").is_private is False


@pytest.mark.parametrize(
    "kind",
    ["video", "document", "audio", "photo", "animation", "video_note", "voice"],
)
def test_every_file_bearing_media_type_gets_indexed(kind):
    """animation/video_note/voice were originally missed, so a channel posting
    only GIFs or round videos indexed empty."""
    msg = _Msg(media_kind=kind, **{kind: _file(file_size=123)})
    item = _to_media_item(msg)
    assert item is not None, f"{kind} was not indexed"
    assert item.kind == kind
    assert item.document_id == "AgADfile"


@pytest.mark.parametrize("kind", ["poll", "web_page", "location", "contact", "dice"])
def test_media_without_a_real_file_is_not_indexed(kind):
    msg = _Msg(media_kind=kind, **{kind: _Stub(question="?")})
    assert _to_media_item(msg) is None


def test_plain_text_post_is_skipped_and_reports_no_kind():
    msg = _Msg(media_kind=None)
    assert _to_media_item(msg) is None
    assert _media_kind(msg) is None


def test_kind_is_reported_even_when_nothing_is_downloadable():
    """This is what makes an empty index explainable instead of a silent zero."""
    assert _media_kind(_Msg(media_kind="web_page", web_page=_Stub())) == "web_page"


def test_video_sent_as_a_document_keeps_its_filename_and_size():
    msg = _Msg(
        media_kind="document",
        document=_file(file_name="ep02.mkv", mime_type="video/x-matroska",
                       file_size=900),
    )
    item = _to_media_item(msg)
    assert (item.file_name, item.mime_type, item.file_size) == (
        "ep02.mkv", "video/x-matroska", 900,
    )


def test_channel_refs_users_actually_paste_are_understood():
    assert _normalize_ref("@news") == "news"
    assert _normalize_ref("news") == "news"
    assert _normalize_ref("https://t.me/news") == "news"
    assert _normalize_ref("https://t.me/news/1234") == "news"
    assert _normalize_ref("tg://resolve?domain=news") == "news"
    # Private-channel link: the -100 supergroup prefix has to be restored.
    assert _normalize_ref("https://t.me/c/1234567890/55") == -1001234567890
    assert _normalize_ref("-1001234567890") == -1001234567890


def test_post_link_keeps_its_message_id():
    # Dropping this is why `--kind video` on a post link listed nothing:
    # the scan started at the channel's first message instead of the post.
    assert parse_ref("https://t.me/news/130170") == ("news", 130170)
    assert parse_ref("https://t.me/c/1234567890/55") == (-1001234567890, 55)
    assert parse_ref("https://t.me/news/12/34") == ("news", 34)  # topic link
    assert parse_ref("@news") == ("news", None)
