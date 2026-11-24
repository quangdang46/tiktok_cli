"""Tests for core/downloader.py with yt_dlp fully mocked.

``_import_ytdlp`` is patched to return a fake ``yt_dlp`` module, so no real
network or yt-dlp install is needed. ``core.errors`` is the real module.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import ClassVar, Self

import pytest

from tiktok_cli.core import downloader
from tiktok_cli.core.downloader import YtdlpClient, _enabled_js_runtimes, _import_ytdlp
from tiktok_cli.core.errors import UserError

URL = "https://www.tiktok.com/@user/video/1234567890"


class FakeYoutubeDL:
    """Stand-in for yt_dlp.YoutubeDL.

    ``behavior`` is a callable ``(ydl, url, download) -> info`` set per test;
    it may write files into the directory named by ``opts['outtmpl']`` to
    simulate yt-dlp's output.
    """

    behavior: ClassVar = None
    instances: ClassVar[list[FakeYoutubeDL]] = []

    def __init__(self, opts: dict) -> None:
        self.opts = opts
        self.extract_calls: list[tuple[str, bool]] = []
        FakeYoutubeDL.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False):
        self.extract_calls.append((url, download))
        assert FakeYoutubeDL.behavior is not None, "test must set FakeYoutubeDL.behavior"
        # Access via the class so the plain function is not bound as a method.
        return FakeYoutubeDL.behavior(self, url, download)

    def prepare_filename(self, info: dict) -> str:
        return str(Path(self.opts["outtmpl"]).parent / f"{info.get('id')}.m4a")


@pytest.fixture
def fake_ytdlp(monkeypatch):
    FakeYoutubeDL.behavior = None
    FakeYoutubeDL.instances = []
    fake_module = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_import_ytdlp", lambda: fake_module)
    return fake_module


def _out_dir(ydl: FakeYoutubeDL) -> Path:
    return Path(ydl.opts["outtmpl"]).parent


class TestYdlOpts:
    def test_shared_keys(self, tmp_path):
        client = YtdlpClient()
        opts = client._ydl_opts(tmp_path)
        assert opts["quiet"] is True
        assert opts["no_warnings"] is True
        assert opts["noplaylist"] is True
        assert opts["socket_timeout"] == 30
        assert opts["retries"] == 3
        assert opts["noprogress"] is True
        assert "js_runtimes" in opts
        assert isinstance(opts["logger"], downloader._StderrLogger)
        assert opts["outtmpl"] == str(tmp_path / "%(id)s.%(ext)s")
        # no postprocessors ever
        assert "postprocessors" not in opts

    def test_cookies_only_when_provided(self, tmp_path):
        plain = YtdlpClient()._ydl_opts(tmp_path)
        assert "cookiesfrombrowser" not in plain
        assert "cookiefile" not in plain

        with_browser = YtdlpClient(cookies_from_browser="firefox")._ydl_opts(tmp_path)
        assert with_browser["cookiesfrombrowser"] == ("firefox",)

        cookie_file = tmp_path / "cookies.txt"
        with_file = YtdlpClient(cookies_file=cookie_file)._ydl_opts(tmp_path)
        assert with_file["cookiefile"] == str(cookie_file)

    def test_verbose_relaxes_quiet(self, tmp_path):
        opts = YtdlpClient(verbose=True)._ydl_opts(tmp_path)
        assert opts["quiet"] is False
        assert opts["no_warnings"] is False

    def test_overrides_win(self, tmp_path):
        opts = YtdlpClient()._ydl_opts(tmp_path, noplaylist=False, skip_download=True)
        assert opts["noplaylist"] is False
        assert opts["skip_download"] is True


class TestEnabledJsRuntimes:
    def test_returns_dict(self):
        runtimes = _enabled_js_runtimes()
        assert isinstance(runtimes, dict)
        assert runtimes  # never empty: falls back to {"deno": {}}
        for name, cfg in runtimes.items():
            assert name in ("deno", "node", "quickjs", "bun")
            assert isinstance(cfg, dict)


class TestImportYtdlp:
    def test_missing_ytdlp_is_user_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yt_dlp", None)
        with pytest.raises(UserError, match="yt-dlp is required"):
            _import_ytdlp()

    def test_module_does_not_bind_ytdlp(self):
        # yt_dlp must stay lazily imported inside functions.
        assert not hasattr(downloader, "yt_dlp")
        assert "yt_dlp" not in vars(downloader)


class TestExtractInfo:
    def test_returns_info_without_download(self, fake_ytdlp):
        def behavior(ydl, url, download):
            assert download is False
            return {"id": "vid123", "title": "hello"}

        FakeYoutubeDL.behavior = behavior
        client = YtdlpClient()
        info = client.extract_info(URL)
        assert info == {"id": "vid123", "title": "hello"}
        assert FakeYoutubeDL.instances[0].extract_calls == [(URL, False)]
        # metadata fetch needs no outtmpl
        assert "outtmpl" not in FakeYoutubeDL.instances[0].opts

    def test_empty_info_returns_dict(self, fake_ytdlp):
        FakeYoutubeDL.behavior = lambda ydl, url, download: None
        assert YtdlpClient().extract_info(URL) == {}

    def test_error_translated_to_user_error(self, fake_ytdlp):
        def boom(ydl, url, download):
            raise RuntimeError("Private video. Sign in if you've been granted access")

        FakeYoutubeDL.behavior = boom
        with pytest.raises(UserError) as excinfo:
            YtdlpClient().extract_info(URL)
        assert "private" in str(excinfo.value).lower()


class TestDownloadSubtitles:
    def test_globs_vtt_files(self, fake_ytdlp, tmp_path):
        def behavior(ydl, url, download):
            out_dir = _out_dir(ydl)
            (out_dir / "vid123.vie.vtt").write_text("WEBVTT", encoding="utf-8")
            (out_dir / "vid123.en.vtt").write_text("WEBVTT", encoding="utf-8")
            return {"id": "vid123"}

        FakeYoutubeDL.behavior = behavior
        paths = YtdlpClient().download_subtitles(URL, tmp_path)
        assert paths == sorted(paths)
        assert [p.name for p in paths] == ["vid123.en.vtt", "vid123.vie.vtt"]

    def test_subtitle_opts(self, fake_ytdlp, tmp_path):
        FakeYoutubeDL.behavior = lambda ydl, url, download: {"id": "vid123"}
        YtdlpClient().download_subtitles(URL, tmp_path, langs="vi.*,all")
        opts = FakeYoutubeDL.instances[-1].opts
        assert opts["skip_download"] is True
        assert opts["writesubtitles"] is True
        assert opts["writeautomaticsub"] is True
        assert opts["subformats"] == ["vtt"]
        assert opts["sublangs"] == "vi.*,all"
        assert opts["outtmpl"] == str(tmp_path / "%(id)s.%(ext)s")

    def test_no_subtitles_returns_empty(self, fake_ytdlp, tmp_path):
        FakeYoutubeDL.behavior = lambda ydl, url, download: {"id": "vid123"}
        assert YtdlpClient().download_subtitles(URL, tmp_path) == []

    def test_error_translated(self, fake_ytdlp, tmp_path):
        def boom(ydl, url, download):
            raise RuntimeError("Unsupported URL")

        FakeYoutubeDL.behavior = boom
        with pytest.raises(UserError):
            YtdlpClient().download_subtitles(URL, tmp_path)


class TestDownloadAudio:
    def test_returns_audio_path(self, fake_ytdlp, tmp_path):
        audio = tmp_path / "vid123.m4a"

        def behavior(ydl, url, download):
            assert download is True
            audio.write_bytes(b"fake-audio")
            return {
                "id": "vid123",
                "requested_downloads": [{"filepath": str(audio)}],
            }

        FakeYoutubeDL.behavior = behavior
        result = YtdlpClient().download_audio(URL, tmp_path)
        assert result == audio
        assert result.exists()

    def test_audio_opts(self, fake_ytdlp, tmp_path):
        audio = tmp_path / "vid123.m4a"

        def behavior(ydl, url, download):
            audio.write_bytes(b"x")
            return {"id": "vid123", "filepath": str(audio)}

        FakeYoutubeDL.behavior = behavior
        YtdlpClient().download_audio(URL, tmp_path)
        opts = FakeYoutubeDL.instances[-1].opts
        assert opts["format"] == "bestaudio/best"
        assert opts["outtmpl"] == str(tmp_path / "%(id)s.%(ext)s")
        assert "postprocessors" not in opts

    def test_no_file_produced_raises_user_error(self, fake_ytdlp, tmp_path):
        FakeYoutubeDL.behavior = lambda ydl, url, download: {"id": "vid123"}
        with pytest.raises(UserError, match="no audio file"):
            YtdlpClient().download_audio(URL, tmp_path)

    def test_error_translated(self, fake_ytdlp, tmp_path):
        def boom(ydl, url, download):
            raise RuntimeError("Unable to download webpage")

        FakeYoutubeDL.behavior = boom
        with pytest.raises(UserError):
            YtdlpClient().download_audio(URL, tmp_path)


class TestListSubtitleLangs:
    def test_parses_vtt_filenames(self, fake_ytdlp):
        def behavior(ydl, url, download):
            out_dir = _out_dir(ydl)
            (out_dir / "vid123.vie.vtt").write_text("WEBVTT", encoding="utf-8")
            (out_dir / "vid123.en.vtt").write_text("WEBVTT", encoding="utf-8")
            (out_dir / "vid123.en-US.vtt").write_text("WEBVTT", encoding="utf-8")
            (out_dir / "not-a-sub.txt").write_text("x", encoding="utf-8")
            return {"id": "vid123"}

        FakeYoutubeDL.behavior = behavior
        langs = YtdlpClient().list_subtitle_langs(URL)
        assert langs == {"en": ["vtt"], "en-US": ["vtt"], "vie": ["vtt"]}

    def test_requests_all_languages(self, fake_ytdlp):
        FakeYoutubeDL.behavior = lambda ydl, url, download: {"id": "vid123"}
        YtdlpClient().list_subtitle_langs(URL)
        opts = FakeYoutubeDL.instances[-1].opts
        assert opts["sublangs"] == "all"
        assert opts["skip_download"] is True
        assert opts["writesubtitles"] is True
        assert opts["writeautomaticsub"] is True

    def test_no_captions_returns_empty(self, fake_ytdlp):
        FakeYoutubeDL.behavior = lambda ydl, url, download: {"id": "vid123"}
        assert YtdlpClient().list_subtitle_langs(URL) == {}

    def test_error_translated(self, fake_ytdlp):
        def boom(ydl, url, download):
            raise RuntimeError("Sign in to confirm your age")

        FakeYoutubeDL.behavior = boom
        with pytest.raises(UserError):
            YtdlpClient().list_subtitle_langs(URL)
