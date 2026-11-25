"""Tests for `tiktok download` — client and post_page fully mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from tiktok_cli.commands import download as download_cmd
from tiktok_cli.core.errors import UserError

runner = CliRunner()
app = typer.Typer()


@app.command()
def _noop() -> None:
    """Keep >1 command: single-command Typer apps misparsed args in tests."""


app.command(name="download")(download_cmd.download)

VIDEO_URL = "https://www.tiktok.com/@u/video/123"
PHOTO_URL = "https://www.tiktok.com/@u/photo/456"


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "dl"


def _client_mock(**methods):
    client = download_cmd.YtdlpClient()
    for name, value in methods.items():
        setattr(client, name, value)
    return client


class TestDownloadOne:
    def test_video_download(self, out_dir, tmp_path):
        video = tmp_path / "u-123.mp4"
        video.write_bytes(b"mp4")
        info = {"id": "123", "webpage_url": VIDEO_URL}
        client = _client_mock(
            extract_info=lambda url: info,
            download_video=lambda url, d: (video, info),
        )
        with patch.object(download_cmd, "YtdlpClient", return_value=client):
            paths = download_cmd._download_one(VIDEO_URL, out_dir, client, refresh=False)
        assert paths == [video]

    def test_photo_url_goes_to_images(self, out_dir, tmp_path):
        img = tmp_path / "image_01.jpg"
        img.write_bytes(b"x")
        item = {"id": "456", "imagePost": {"images": []}}
        with (
            patch.object(download_cmd.post_page, "fetch_item_struct", return_value=item) as fetch,
            patch.object(download_cmd.post_page, "download_post_images", return_value=[img]),
            patch.object(download_cmd.post_page, "write_images_manifest"),
        ):
            paths = download_cmd._download_one(PHOTO_URL, out_dir, _client_mock(), refresh=False)
        assert paths == [img]
        # /photo/ pages don't SSR itemStruct — must fetch the /video/ twin
        fetch.assert_called_once_with("https://www.tiktok.com/@u/video/456")

    def test_disguised_photo_post_detected_via_info(self, out_dir, tmp_path):
        """A /video/ URL whose info says playlist routes to the image path."""
        img = tmp_path / "image_01.jpg"
        img.write_bytes(b"x")
        info = {"id": "789", "_type": "playlist", "webpage_url": VIDEO_URL}
        item = {"id": "789"}
        client = _client_mock(extract_info=lambda url: info)
        with (
            patch.object(download_cmd.post_page, "fetch_item_struct", return_value=item),
            patch.object(download_cmd.post_page, "download_post_images", return_value=[img]),
            patch.object(download_cmd.post_page, "write_images_manifest"),
        ):
            paths = download_cmd._download_one(VIDEO_URL, out_dir, client, refresh=False)
        assert paths == [img]

    def test_cached_video_skips_download(self, out_dir, tmp_path):
        existing = out_dir / "u-123.mp4"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"old")
        client = _client_mock(
            extract_info=lambda url: {"id": "123", "webpage_url": VIDEO_URL},
            download_video=lambda *a: pytest.fail("should not download"),
        )
        paths = download_cmd._download_one(VIDEO_URL, out_dir, client, refresh=False)
        assert paths == [existing]

    def test_cached_photo_skips_refetch(self, out_dir):
        image_dir = out_dir / "456" / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "image_01.jpg").write_bytes(b"x")
        with patch.object(
            download_cmd.post_page, "fetch_item_struct", side_effect=AssertionError("no fetch")
        ):
            paths = download_cmd._download_one(PHOTO_URL, out_dir, _client_mock(), refresh=False)
        assert [p.name for p in paths] == ["image_01.jpg"]


class TestDownloadCommand:
    def test_video_end_to_end(self, tmp_path):
        video = tmp_path / "u-123.mp4"
        video.write_bytes(b"mp4")
        info = {"id": "123", "webpage_url": VIDEO_URL}
        client = _client_mock(
            extract_info=lambda url: info,
            download_video=lambda url, d: (video, info),
        )
        with patch.object(download_cmd, "YtdlpClient", return_value=client):
            result = runner.invoke(app, ["download", VIDEO_URL, "-o", str(tmp_path / "dl")])
        assert result.exit_code == 0, result.output
        assert str(video) in result.output

    def test_non_tiktok_url_fails(self, tmp_path):
        result = runner.invoke(app, ["download", "https://example.com/x", "-o", str(tmp_path)])
        assert result.exit_code == 1
        assert "not a TikTok URL" in result.output

    def test_mixed_urls_exit_code(self, tmp_path):
        video = tmp_path / "u-123.mp4"
        video.write_bytes(b"mp4")
        info = {"id": "123", "webpage_url": VIDEO_URL}
        client = _client_mock(
            extract_info=lambda url: info,
            download_video=lambda url, d: (video, info),
        )
        with patch.object(download_cmd, "YtdlpClient", return_value=client):
            result = runner.invoke(
                app,
                ["download", VIDEO_URL, "https://example.com/x", "-o", str(tmp_path / "dl")],
            )
        assert result.exit_code == 1
        assert str(video) in result.output

    def test_user_error_per_url(self, tmp_path):
        client = _client_mock(
            extract_info=lambda url: (_ for _ in ()).throw(UserError("Download failed: nope")),
        )
        with patch.object(download_cmd, "YtdlpClient", return_value=client):
            result = runner.invoke(app, ["download", VIDEO_URL, "-o", str(tmp_path / "dl")])
        assert result.exit_code == 1
        assert "Download failed" in result.output
