"""Unit tests for tiktok_cli.pipeline — YtdlpClient/STT fully mocked, no network."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import ClassVar

import pytest

from tiktok_cli import pipeline
from tiktok_cli.core import stt
from tiktok_cli.core.errors import UserError
from tiktok_cli.pipeline import process_video

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_VTT = FIXTURES / "sample.vtt"
INFO = json.loads((FIXTURES / "tiktok_info.json").read_text(encoding="utf-8"))

VIDEO_ID = INFO["id"]
VIDEO_URL = INFO["webpage_url"]
PHOTO_URL = "https://www.tiktok.com/@dev.daily/photo/7350000000000000001"


def _write_vtt(out_dir: Path, name: str = f"{VIDEO_ID}.en.vtt") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / name
    shutil.copy(SAMPLE_VTT, dest)
    return dest


class StubClient:
    """Configurable YtdlpClient stand-in."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.sub_calls = 0
        self.audio_calls = 0
        self.info_calls = 0

    # Behaviors are set as class attrs by the fixture below.
    info: ClassVar[dict] = INFO
    sub_files: ClassVar[list[str]] = [f"{VIDEO_ID}.en.vtt"]
    audio_name: ClassVar[str] = "audio.webm"
    extract_error: ClassVar[Exception | None] = None
    audio_error: ClassVar[Exception | None] = None
    sub_calls_log: ClassVar[list[str]] = []
    audio_calls_log: ClassVar[list[str]] = []
    info_urls_log: ClassVar[list[str]] = []

    def extract_info(self, url, download=False):
        self.info_calls += 1
        StubClient.info_urls_log.append(url)
        if self.extract_error is not None:
            raise self.extract_error
        return dict(self.info)

    def download_subtitles(self, url, out_dir):
        self.sub_calls += 1
        StubClient.sub_calls_log.append(url)
        out_dir.mkdir(parents=True, exist_ok=True)
        return [_write_vtt(out_dir, name) for name in self.sub_files]

    def download_audio(self, url, tmp_dir):
        self.audio_calls += 1
        StubClient.audio_calls_log.append(url)
        if self.audio_error is not None:
            raise self.audio_error
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / self.audio_name
        path.write_bytes(b"fake-audio")
        return path


@pytest.fixture
def stub_client(monkeypatch):
    """Patch pipeline.YtdlpClient; returns the StubClient class for config."""
    monkeypatch.setattr(pipeline, "YtdlpClient", StubClient)
    StubClient.info = dict(INFO)
    StubClient.sub_files = [f"{VIDEO_ID}.en.vtt"]
    StubClient.extract_error = None
    StubClient.audio_error = None
    StubClient.sub_calls_log = []
    StubClient.audio_calls_log = []
    return StubClient


def _last_index(output_dir: Path) -> dict:
    lines = (output_dir / "index.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


# --- caption path -------------------------------------------------------------


def test_caption_path_end_to_end(tmp_path, stub_client):
    result = process_video(VIDEO_URL, tmp_path)

    assert result.status == "caption"
    assert result.video_id == VIDEO_ID
    assert result.cue_count > 0
    assert result.language == "en"
    assert result.transcript_txt is not None
    assert result.transcript_txt.exists()

    video_dir = tmp_path / VIDEO_ID
    for fmt in ("txt", "srt", "vtt", "json", "md"):
        assert (video_dir / f"transcript.{fmt}").exists(), fmt
    assert (video_dir / "subs" / f"{VIDEO_ID}.en.vtt").exists()
    assert (video_dir / "source.info.json").exists()

    meta = json.loads((video_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["transcript_source"] == "tiktok-captions:en"
    assert meta["cue_count"] == result.cue_count

    index = _last_index(tmp_path)
    assert index["status"] == "caption"
    assert index["video_id"] == VIDEO_ID
    assert index["artifact_dir"].endswith(VIDEO_ID)


def test_caption_single_format(tmp_path, stub_client):
    result = process_video(VIDEO_URL, tmp_path, fmt="txt")
    assert result.status == "caption"
    video_dir = tmp_path / VIDEO_ID
    assert (video_dir / "transcript.txt").exists()
    assert not (video_dir / "transcript.srt").exists()
    assert result.transcript_txt == video_dir / "transcript.txt"


def test_caption_language_from_filename(tmp_path, stub_client):
    stub_client.sub_files = [f"{VIDEO_ID}.vi.vtt"]
    result = process_video(VIDEO_URL, tmp_path)
    assert result.status == "caption"
    assert result.language == "vi"
    meta = json.loads((tmp_path / VIDEO_ID / "metadata.json").read_text())
    assert meta["transcript_source"] == "tiktok-captions:vi"


# --- whisper fallback ---------------------------------------------------------


def _fake_transcribe(audio_path, model="small", language=None, engine="auto"):
    return stt.STTResult(
        cues=[
            {"start": 0.0, "end": 1.5, "text": "xin chao"},
            {"start": 1.5, "end": 3.0, "text": "the gioi"},
        ],
        language="vi",
        duration=14.0,
        engine="faster",
        model=model,
        elapsed_s=0.01,
    )


def test_whisper_fallback_when_no_captions(tmp_path, stub_client, monkeypatch):
    stub_client.sub_files = []  # no caption tracks
    monkeypatch.setattr(stt, "transcribe_media", _fake_transcribe)

    result = process_video(VIDEO_URL, tmp_path)

    assert result.status == "whisper"
    assert result.language == "vi"
    assert result.cue_count == 2
    video_dir = tmp_path / VIDEO_ID
    assert (video_dir / "transcript.txt").exists()
    assert (video_dir / "transcript.srt").exists()

    meta = json.loads((video_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["transcript_source"] == "whisper:faster:small:vi"

    # Audio temp dir is cleaned up; nothing audio-ish remains.
    assert not list(video_dir.glob("audio-*"))
    assert not list(video_dir.glob("audio.*"))

    index = _last_index(tmp_path)
    assert index["status"] == "whisper"
    assert index["language"] == "vi"


def test_whisper_always_skips_caption_attempt(tmp_path, stub_client, monkeypatch):
    monkeypatch.setattr(stt, "transcribe_media", _fake_transcribe)
    stub_client.sub_files = [f"{VIDEO_ID}.en.vtt"]  # captions DO exist

    result = process_video(VIDEO_URL, tmp_path, whisper="always")

    assert result.status == "whisper"
    assert stub_client.sub_calls_log == []  # caption path never attempted
    assert stub_client.audio_calls_log == [VIDEO_URL]


def test_keep_audio_retains_file(tmp_path, stub_client, monkeypatch):
    stub_client.sub_files = []
    monkeypatch.setattr(stt, "transcribe_media", _fake_transcribe)

    result = process_video(VIDEO_URL, tmp_path, keep_audio=True)

    assert result.status == "whisper"
    assert (tmp_path / VIDEO_ID / "audio.webm").exists()


def test_whisper_never_no_captions_status(tmp_path, stub_client):
    stub_client.sub_files = []
    result = process_video(VIDEO_URL, tmp_path, whisper="never")

    assert result.status == "no-captions"
    assert result.transcript_txt is None
    video_dir = tmp_path / VIDEO_ID
    assert (video_dir / "metadata.json").exists()
    assert not (video_dir / "transcript.json").exists()
    assert _last_index(tmp_path)["status"] == "no-captions"


def test_no_audio_status(tmp_path, stub_client, monkeypatch):
    stub_client.sub_files = []
    stub_client.audio_error = UserError("requested format is not available")

    result = process_video(VIDEO_URL, tmp_path)

    assert result.status == "no-audio"
    assert result.error is not None
    assert (tmp_path / VIDEO_ID / "metadata.json").exists()
    assert _last_index(tmp_path)["status"] == "no-audio"


# --- cache / photo / failure ---------------------------------------------------


def test_cached_video_skipped(tmp_path, stub_client):
    video_dir = tmp_path / VIDEO_ID
    video_dir.mkdir(parents=True)
    (video_dir / "transcript.json").write_text("{}", encoding="utf-8")

    result = process_video(VIDEO_URL, tmp_path)

    assert result.status == "skipped-cached"
    assert result.transcript_txt is None
    assert _last_index(tmp_path)["status"] == "skipped-cached"


def test_refresh_bypasses_cache(tmp_path, stub_client):
    video_dir = tmp_path / VIDEO_ID
    video_dir.mkdir(parents=True)
    (video_dir / "transcript.json").write_text("{}", encoding="utf-8")

    result = process_video(VIDEO_URL, tmp_path, refresh=True)

    assert result.status == "caption"


def test_photo_post_caption_becomes_the_transcript(tmp_path, stub_client):
    """A photo post's caption is its content and must land in transcript.txt.

    Regression: this path used to write metadata only, so a caption that plainly
    held the whole post produced an empty transcript.txt and callers had to open
    source.info.json by hand.
    """
    caption = "1. Two minute rule. 2. Cut the task until it is funny-small."
    stub_client.info = {
        **INFO,
        "id": "7350000000000000001",
        "webpage_url": PHOTO_URL,
        "description": caption,
    }
    result = process_video(PHOTO_URL, tmp_path)

    assert result.status == "photo-post"
    video_dir = tmp_path / "7350000000000000001"
    assert (video_dir / "transcript.txt").read_text(encoding="utf-8").strip() == caption
    md = (video_dir / "transcript.md").read_text(encoding="utf-8")
    assert "## Caption" in md
    # a written caption must not get an invented timestamp
    assert "00:00:00 -> 00:00:00" not in md
    meta = json.loads((video_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["description"] == caption
    assert meta["transcript_source"] == "photo-post"


def test_photo_post_without_caption_still_skips_transcripts(tmp_path, stub_client):
    stub_client.info = {
        **INFO,
        "id": "7350000000000000002",
        "webpage_url": PHOTO_URL,
        "description": "",
    }
    result = process_video(PHOTO_URL, tmp_path)

    assert result.status == "photo-post"
    video_dir = tmp_path / "7350000000000000002"
    assert (video_dir / "metadata.json").exists()
    assert not (video_dir / "transcript.json").exists()


def test_photo_post_skipped(tmp_path, stub_client):
    stub_client.info = {
        **INFO,
        "id": "7350000000000000001",
        "webpage_url": PHOTO_URL,
        "description": "",
    }
    result = process_video(PHOTO_URL, tmp_path)

    assert result.status == "photo-post"
    video_dir = tmp_path / "7350000000000000001"
    assert (video_dir / "metadata.json").exists()
    assert not (video_dir / "transcript.json").exists()
    assert _last_index(tmp_path)["status"] == "photo-post"


def test_photo_post_uses_cache_on_rerun(tmp_path, stub_client):
    """A processed photo post must short-circuit to skipped-cached.

    Regression: the photo-post branch returned before the shared cache guard, so
    re-running fetched the post again and re-downloaded every image, which made
    `batch` over a photo-heavy list pay full cost on each run.
    """
    stub_client.info = {
        **INFO,
        "id": "7350000000000000001",
        "webpage_url": PHOTO_URL,
        "description": "A caption worth keeping.",
    }
    first = process_video(PHOTO_URL, tmp_path)
    assert first.status == "photo-post"
    extract_calls = len(stub_client.info_urls_log)

    second = process_video(PHOTO_URL, tmp_path)

    assert second.status == "skipped-cached"
    assert second.transcript_txt == first.transcript_txt
    # the post was not fetched again just to decide it was already done
    assert len(stub_client.info_urls_log) == extract_calls
    assert _last_index(tmp_path)["status"] == "skipped-cached"


def test_photo_post_refresh_bypasses_cache(tmp_path, stub_client):
    stub_client.info = {
        **INFO,
        "id": "7350000000000000001",
        "webpage_url": PHOTO_URL,
        "description": "A caption worth keeping.",
    }
    process_video(PHOTO_URL, tmp_path)
    again = process_video(PHOTO_URL, tmp_path, refresh=True)

    assert again.status == "photo-post"
    assert _last_index(tmp_path)["status"] == "photo-post"


def test_failed_url_isolated(tmp_path, stub_client):
    """A failing URL returns status=failed; the next URL still processes."""
    stub_client.extract_error = UserError("That video is unavailable.")
    bad = process_video(VIDEO_URL, tmp_path / "bad")
    assert bad.status == "failed"
    assert bad.error is not None
    assert _last_index(tmp_path / "bad")["status"] == "failed"

    stub_client.extract_error = None
    good = process_video(VIDEO_URL, tmp_path / "good")
    assert good.status == "caption"


def test_non_tiktok_url_raises_user_error(tmp_path, stub_client):
    with pytest.raises(UserError):
        process_video("https://example.com/not-tiktok", tmp_path)


def test_invalid_args_raise_user_error(tmp_path, stub_client):
    with pytest.raises(UserError):
        process_video(VIDEO_URL, tmp_path, whisper="bogus")
    with pytest.raises(UserError):
        process_video(VIDEO_URL, tmp_path, engine="bogus")
    with pytest.raises(UserError):
        process_video(VIDEO_URL, tmp_path, fmt="bogus")
