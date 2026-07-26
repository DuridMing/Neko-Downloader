"""Picking the output file when yt-dlp's filename guess was wrong.

The job's cookie jar lives in the same directory, so this is the difference
between returning a video and returning the user's credentials.
"""

import pytest

from app.handlers._ytdlp_common import COOKIEFILE_NAME, largest_output


def write(dir_, name, size):
    (dir_ / name).write_bytes(b"x" * size)


def test_biggest_media_file_wins(tmp_path):
    write(tmp_path, "video.mp4", 5000)
    write(tmp_path, "thumb.jpg", 200)
    assert largest_output(tmp_path).name == "video.mp4"


def test_cookie_jar_is_never_returned_as_the_download(tmp_path):
    """It would be the only (thus 'largest') file when nothing downloaded."""
    write(tmp_path, COOKIEFILE_NAME, 9000)
    write(tmp_path, "video.mp4", 100)
    assert largest_output(tmp_path).name == "video.mp4"


def test_no_usable_file_raises_instead_of_leaking_the_cookie_jar(tmp_path):
    write(tmp_path, COOKIEFILE_NAME, 9000)
    with pytest.raises(RuntimeError):
        largest_output(tmp_path)


def test_partial_downloads_are_skipped(tmp_path):
    write(tmp_path, "video.mp4.part", 9000)
    write(tmp_path, "video.mp4", 100)
    assert largest_output(tmp_path).name == "video.mp4"
