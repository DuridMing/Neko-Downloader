"""Handler-level rules: which URLs it claims, and what a flood wait does."""

from pathlib import Path

import pytest

from app.handlers.telegram_handler import TelegramHandler
from app.models import CancelledByUser, DownloadContext, DownloadResult, Job
from app.telegram.types import TgFloodWait


@pytest.fixture
def handler(monkeypatch):
    h = TelegramHandler()
    monkeypatch.setattr("app.handlers.telegram_handler.settings.telegram_api_id", 1234)
    monkeypatch.setattr("app.handlers.telegram_handler.tg.AVAILABLE", True)
    return h


def ctx(tmp_path: Path, events: list) -> DownloadContext:
    return DownloadContext(
        output_dir=tmp_path,
        headers={},
        on_progress=events.append,
        is_cancelled=lambda: False,
    )


def test_only_single_post_links_are_claimed(handler):
    assert handler.can_handle("https://t.me/AnimeNep/130170") is True
    assert handler.can_handle("https://t.me/c/1234567890/55") is True
    # A channel with no message id has nothing to download, only to browse.
    assert handler.can_handle("https://t.me/AnimeNep") is False
    assert handler.can_handle("https://example.com/v/123") is False


def test_unconfigured_branch_leaves_the_link_to_the_catch_all(monkeypatch):
    monkeypatch.setattr("app.handlers.telegram_handler.settings.telegram_api_id", 0)
    assert TelegramHandler().can_handle("https://t.me/AnimeNep/130170") is False


def test_flood_wait_is_waited_out_and_retried_once(handler, monkeypatch, tmp_path):
    """A flood wait is throttling, not a failure: sleep it off, then retry."""
    slept: list[int] = []
    monkeypatch.setattr("app.handlers.telegram_handler.time.sleep", lambda s: slept.append(s))
    calls = []
    result = DownloadResult(file_path=tmp_path / "f", title="t", filename="f")

    async def fake(job, c):
        calls.append(1)
        if len(calls) == 1:
            raise TgFloodWait(3)
        return result

    monkeypatch.setattr(handler, "_download", fake)
    events: list = []
    job = Job.new("https://t.me/x/1", handler="telegram")

    assert handler.download(job, ctx(tmp_path, events)) is result
    assert len(calls) == 2
    assert len(slept) == 3, "waited the full flood wait before retrying"
    assert events[0]["speed"].endswith("3s"), "the wait is visible in the UI"


def test_long_flood_wait_fails_instead_of_parking_a_worker(handler, monkeypatch, tmp_path):
    async def fake(job, c):
        raise TgFloodWait(3600)

    monkeypatch.setattr(handler, "_download", fake)
    with pytest.raises(TgFloodWait):
        handler.download(Job.new("https://t.me/x/1", handler="telegram"), ctx(tmp_path, []))


def test_cancel_during_a_flood_wait_stops_the_job(handler, monkeypatch, tmp_path):
    monkeypatch.setattr("app.handlers.telegram_handler.time.sleep", lambda s: None)

    async def fake(job, c):
        raise TgFloodWait(30)

    monkeypatch.setattr(handler, "_download", fake)
    c = DownloadContext(
        output_dir=tmp_path, headers={}, on_progress=lambda e: None,
        is_cancelled=lambda: True,
    )
    with pytest.raises(CancelledByUser):
        handler.download(Job.new("https://t.me/x/1", handler="telegram"), c)
