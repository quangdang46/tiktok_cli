"""Tests for commands/batch.py — pipeline.process_video is always faked."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from tiktok_cli.commands import batch
from tiktok_cli.core.errors import UserError

runner = CliRunner()

app = typer.Typer()
app.command()(batch.batch)


def _install_fake_pipeline(monkeypatch: pytest.MonkeyPatch, fn) -> list:
    """Put a fake tiktok_cli.pipeline module in sys.modules; return call log."""
    calls: list[tuple] = []

    def process_video(url, output_dir, **kwargs):
        calls.append((url, output_dir, kwargs))
        return fn(url, output_dir, **kwargs)

    module = types.ModuleType("tiktok_cli.pipeline")
    module.process_video = process_video
    monkeypatch.setitem(sys.modules, "tiktok_cli.pipeline", module)
    return calls


def _result(url: str, status: str = "caption", **overrides):
    base = {
        "video_id": "12345",
        "url": url,
        "status": status,
        "artifact_dir": Path("out/12345"),
        "transcript_txt": Path("out/12345/transcript.txt"),
        "cue_count": 7,
        "language": "en",
        "error": None,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _write_urls(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "urls.txt"
    f.write_text(content, encoding="utf-8")
    return f


class TestReadUrls:
    def test_skips_comments_blanks_and_dedupes(self, tmp_path):
        f = _write_urls(
            tmp_path,
            "# header\n\n  https://a  \nhttps://b\nhttps://a\n   # indented comment\n",
        )
        assert batch._read_urls(f) == ["https://a", "https://b"]

    def test_empty_file_raises_user_error(self, tmp_path):
        f = _write_urls(tmp_path, "# only comments\n\n")
        with pytest.raises(UserError, match="(?i)no urls"):
            batch._read_urls(f)

    def test_missing_file_raises_user_error(self, tmp_path):
        with pytest.raises(UserError):
            batch._read_urls(tmp_path / "nope.txt")


class TestBatchCommand:
    def test_happy_path_order_and_summary(self, tmp_path, monkeypatch):
        calls = _install_fake_pipeline(monkeypatch, lambda u, o, **k: _result(u))
        urls = _write_urls(
            tmp_path,
            "# c\nhttps://a\nhttps://b\nhttps://a\n",
        )
        result = runner.invoke(app, [str(urls), "-o", str(tmp_path / "out")])
        assert result.exit_code == 0, result.output
        assert [c[0] for c in calls] == ["https://a", "https://b"]
        assert calls[0][1] == tmp_path / "out"
        # options forwarded with transcript-mirroring defaults
        assert calls[0][2]["model"] == "small"
        assert calls[0][2]["whisper"] == "auto"
        assert calls[0][2]["engine"] == "auto"
        assert calls[0][2]["fmt"] == "all"
        assert "batch summary: total=2 ok=2 caption=2" in result.output
        assert "transcript.txt" in result.output

    def test_photo_post_counts_as_success(self, tmp_path, monkeypatch):
        """A transcribed photo post is a success, not a failure.

        Regression: `ok` summed a hand-written list of statuses that omitted
        `photo-post`, so a batch of one photo post plus one bad URL reported
        ok=0 and exited 1 even though the photo post wrote a transcript.
        """
        statuses = iter(["photo-post", "failed"])
        _install_fake_pipeline(
            monkeypatch, lambda u, o, **k: _result(u, status=next(statuses))
        )
        urls = _write_urls(tmp_path, "https://a\nhttps://b\n")
        result = runner.invoke(app, [str(urls), "-o", str(tmp_path / "out")])

        assert "ok=1" in result.output
        # every status is reported, so the buckets add up to the total
        assert "total=2" in result.output
        assert "photo-post=1" in result.output
        assert "failed=1" in result.output
        assert result.exit_code == 0, result.output

    def test_summary_buckets_sum_to_total(self, tmp_path, monkeypatch):
        """No status may drop out of the summary.

        The summary used to be a hand-written f-string; any status missing from
        it vanished from the output and from `ok`.
        """
        statuses = iter(["photo-post", "no-audio", "skipped-cached"])
        _install_fake_pipeline(
            monkeypatch, lambda u, o, **k: _result(u, status=next(statuses))
        )
        urls = _write_urls(tmp_path, "https://a\nhttps://b\nhttps://c\n")
        result = runner.invoke(app, [str(urls), "-o", str(tmp_path / "out")])

        assert result.exit_code == 0, result.output
        # rich wraps the summary across lines at console width, so join the
        # whole output before parsing rather than assuming one line.
        flat = " ".join(result.output.split())
        summary = flat[flat.index("batch summary") :]
        total = int(summary.split("total=")[1].split()[0])
        buckets = {
            part.split("=")[0]: int(part.split("=")[1])
            for part in summary.split()
            if "=" in part and not part.startswith(("total=", "ok="))
        }
        assert sum(buckets.values()) == total, summary

    def test_flags_forwarded(self, tmp_path, monkeypatch):
        calls = _install_fake_pipeline(monkeypatch, lambda u, o, **k: _result(u))
        urls = _write_urls(tmp_path, "https://a\n")
        result = runner.invoke(
            app,
            [
                str(urls),
                "-m",
                "turbo",
                "-l",
                "vi",
                "--whisper",
                "always",
                "--engine",
                "faster",
                "--format",
                "txt",
                "--keep-audio",
                "--refresh",
                "--cookies-from-browser",
                "firefox",
                "--cookies",
                "ck.txt",
                "-v",
            ],
        )
        assert result.exit_code == 0, result.output
        kw = calls[0][2]
        assert kw["model"] == "turbo"
        assert kw["language"] == "vi"
        assert kw["whisper"] == "always"
        assert kw["engine"] == "faster"
        assert kw["fmt"] == "txt"
        assert kw["keep_audio"] is True
        assert kw["refresh"] is True
        assert kw["cookies_from_browser"] == "firefox"
        assert str(kw["cookies_file"]) == "ck.txt"
        assert kw["verbose"] is True

    def test_one_bad_url_never_kills_batch(self, tmp_path, monkeypatch):
        def flaky(url, output_dir, **kwargs):
            if "bad" in url:
                raise RuntimeError("boom")
            return _result(url, status="whisper", language="vi")

        _install_fake_pipeline(monkeypatch, flaky)
        urls = _write_urls(tmp_path, "https://good\nhttps://bad\nhttps://also-good\n")
        result = runner.invoke(app, [str(urls)])
        assert result.exit_code == 0, result.output
        assert "total=3" in result.output
        assert "failed=1" in result.output
        assert "whisper=2" in result.output

    def test_failed_video_result_counted(self, tmp_path, monkeypatch):
        _install_fake_pipeline(
            monkeypatch,
            lambda u, o, **k: _result(
                u, status="failed", transcript_txt=None, error="private video", cue_count=0
            ),
        )
        urls = _write_urls(tmp_path, "https://x\n")
        result = runner.invoke(app, [str(urls)])
        assert result.exit_code == 1  # nothing succeeded
        assert "failed=1" in result.output

    def test_empty_file_exits_nonzero(self, tmp_path, monkeypatch):
        _install_fake_pipeline(monkeypatch, lambda u, o, **k: _result(u))
        urls = _write_urls(tmp_path, "# nothing here\n")
        result = runner.invoke(app, [str(urls)])
        assert result.exit_code != 0
        assert "error:" in result.output.lower() or "no urls" in result.output.lower()
