"""CLI tests for `tiktok transcript` — pipeline mocked, no network."""

from __future__ import annotations

import pytest
import typer
from test_pipeline import INFO, VIDEO_ID, VIDEO_URL, StubClient, _fake_transcribe
from typer.testing import CliRunner

from tiktok_cli import pipeline
from tiktok_cli.commands import transcript as transcript_cmd
from tiktok_cli.core import stt
from tiktok_cli.core.errors import UserError

app = typer.Typer()
app.command()(transcript_cmd.transcript)

runner = CliRunner()


@pytest.fixture
def stub_client(monkeypatch):
    monkeypatch.setattr(pipeline, "YtdlpClient", StubClient)
    StubClient.info = dict(INFO)
    StubClient.sub_files = [f"{VIDEO_ID}.en.vtt"]
    StubClient.extract_error = None
    StubClient.audio_error = None
    StubClient.sub_calls_log = []
    StubClient.audio_calls_log = []
    return StubClient


def test_transcript_caption_url(tmp_path, stub_client):
    result = runner.invoke(app, [VIDEO_URL, "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    # stdout: exactly one summary line per video, machine-parseable.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert VIDEO_ID in lines[0]
    assert "tiktok-captions" in lines[0]
    assert "cues=" in lines[0]

    video_dir = tmp_path / VIDEO_ID
    assert (video_dir / "transcript.txt").exists()
    assert (video_dir / "transcript.json").exists()


def test_transcript_whisper_fallback(tmp_path, stub_client, monkeypatch):
    stub_client.sub_files = []
    monkeypatch.setattr(stt, "transcribe_media", _fake_transcribe)

    result = runner.invoke(app, [VIDEO_URL, "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "whisper" in result.stdout
    assert (tmp_path / VIDEO_ID / "transcript.txt").exists()


def test_transcript_failed_url_isolated(tmp_path, stub_client, monkeypatch):
    """One bad URL fails; the good URL still produces artifacts; exit 1."""
    good = VIDEO_URL
    bad = "https://www.tiktok.com/@dev.daily/video/9999999999999999999"

    def extract(self, url, download=False):
        if "9999999999999999999" in url:
            raise UserError("That video is unavailable.")
        return dict(INFO)

    monkeypatch.setattr(StubClient, "extract_info", extract)

    result = runner.invoke(app, [bad, good, "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert VIDEO_ID in result.stdout  # good URL summary still printed
    assert (tmp_path / VIDEO_ID / "transcript.txt").exists()


def test_transcript_non_tiktok_url_continues(tmp_path, stub_client):
    result = runner.invoke(app, ["https://example.com/nope", VIDEO_URL, "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert VIDEO_ID in result.stdout
    assert (tmp_path / VIDEO_ID / "transcript.txt").exists()


def test_transcript_whisper_never(tmp_path, stub_client):
    stub_client.sub_files = []
    result = runner.invoke(app, [VIDEO_URL, "-o", str(tmp_path), "--whisper", "never"])
    assert result.exit_code == 0, result.output
    assert "no-captions" in result.stdout
    assert not (tmp_path / VIDEO_ID / "transcript.json").exists()


def test_transcript_invalid_flag_rejected(tmp_path, stub_client):
    result = runner.invoke(app, [VIDEO_URL, "-o", str(tmp_path), "--whisper", "bogus"])
    assert result.exit_code != 0


def test_transcript_stdout_has_only_summary(tmp_path, stub_client):
    """stdout must contain only 'vid | source | cues=N | dir' lines."""
    result = runner.invoke(app, [VIDEO_URL, "-o", str(tmp_path)])
    assert result.exit_code == 0
    for line in result.stdout.splitlines():
        if line.strip():
            assert " | " in line and "cues=" in line
