"""Unit tests for core/url.py - no network."""

from __future__ import annotations

import pytest

from tiktok_cli.core.url import (
    classify_url,
    is_tiktok_url,
    photo_to_video_url,
    video_id_from_url,
)

VIDEO_URL = "https://www.tiktok.com/@someuser/video/7312345678901234567"
VIDEO_ID = "7312345678901234567"


@pytest.mark.parametrize(
    "url",
    [
        VIDEO_URL,
        "https://www.tiktok.com/@user/video/123/extra",
        "https://tiktok.com/@someuser/video/1234567890123456789",
        "https://m.tiktok.com/@someuser/video/111",
        "https://www.tiktok.com/v/2222222222",
        "https://www.tiktok.com/video/3333333333",
    ],
)
def test_classify_video(url: str) -> None:
    assert classify_url(url) == "video"


def test_classify_photo() -> None:
    assert classify_url("https://www.tiktok.com/@user/photo/7312345678901234567") == "photo"


@pytest.mark.parametrize(
    "url",
    [
        "https://vm.tiktok.com/ZMxxxxxx/",
        "https://vt.tiktok.com/ZSxxxxxx/",
        "https://www.tiktok.com/t/ZTRabcde/",
    ],
)
def test_classify_short(url: str) -> None:
    assert classify_url(url) == "short"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/",
        "https://www.tiktok.com/foryou",
        "https://www.tiktok.com/following",
        "https://www.tiktok.com/explore",
        "https://www.tiktok.com/friends",
        "https://www.tiktok.com/live",
        "https://www.tiktok.com/foryou/",
    ],
)
def test_classify_feed(url: str) -> None:
    assert classify_url(url) == "feed"


def test_classify_profile() -> None:
    assert classify_url("https://www.tiktok.com/@someuser") == "profile"
    assert classify_url("https://www.tiktok.com/@some.user-name/") == "profile"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/tag/funny",
        "not a url",
        "",
        "https://example.com/@user/video/123",
        "https://evil-tiktok.com/@user/video/123",
    ],
)
def test_classify_other(url: str) -> None:
    assert classify_url(url) == "other"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com",
        "https://tiktok.com",
        "https://www.tiktok.com/@u/video/1",
        "https://m.tiktok.com/foryou",
        "https://vm.tiktok.com/abc/",
        "https://vt.tiktok.com/abc/",
        "http://www.tiktok.com/@u",
    ],
)
def test_is_tiktok_url_true(url: str) -> None:
    assert is_tiktok_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/@user/video/123",
        "https://evil-tiktok.com/",
        "https://tiktok.com.evil.com/",
        "ftp://www.tiktok.com/@u",
        "not a url",
        "",
    ],
)
def test_is_tiktok_url_false(url: str) -> None:
    assert is_tiktok_url(url) is False


def test_video_id_from_url() -> None:
    assert video_id_from_url(VIDEO_URL) == VIDEO_ID
    assert video_id_from_url("https://tiktok.com/@u/video/42") == "42"
    assert video_id_from_url("https://www.tiktok.com/v/777") == "777"
    assert video_id_from_url("https://www.tiktok.com/video/888") == "888"


@pytest.mark.parametrize(
    "url",
    [
        "https://vm.tiktok.com/ZMxxxxxx/",
        "https://www.tiktok.com/t/ZTRabcde/",
        "https://www.tiktok.com/@user",
        "https://www.tiktok.com/foryou",
        "not a url",
        "",
    ],
)
def test_video_id_from_url_none(url: str) -> None:
    assert video_id_from_url(url) is None


class TestPhotoPosts:
    PHOTO = "https://www.tiktok.com/@user/photo/7707892619572972813"
    VIDEO = "https://www.tiktok.com/@user/video/7707892619572972813"

    def test_classify_photo(self):
        assert classify_url(self.PHOTO) == "photo"

    def test_video_id_from_photo_url(self):
        assert video_id_from_url(self.PHOTO) == "7707892619572972813"

    def test_photo_to_video_url_rewrites(self):
        assert photo_to_video_url(self.PHOTO) == self.VIDEO

    def test_photo_to_video_url_passthrough(self):
        assert photo_to_video_url(self.VIDEO) == self.VIDEO
        assert photo_to_video_url("https://vm.tiktok.com/abc/") == "https://vm.tiktok.com/abc/"
