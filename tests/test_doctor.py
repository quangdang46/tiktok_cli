"""Tests for commands/doctor.py — all externals are mocked."""

from __future__ import annotations

import builtins
import socket
import sys
import types
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from tiktok_cli.commands import doctor

runner = CliRunner()

app = typer.Typer()
app.command()(doctor.doctor)


def _block_imports(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make `import <name>` raise ImportError unless a fake is in sys.modules."""
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root in names and root not in sys.modules:
            raise ImportError(f"blocked: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def _fake_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _fake_ytdlp(version: str = "2026.11.23") -> types.ModuleType:
    return _fake_module("yt_dlp", version=types.SimpleNamespace(__version__=version))


def _ctx_manager():
    """A socket-like object usable as a context manager."""
    return MagicMock()


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Hermetic doctor run: blocked imports, no binaries, no network."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    (tmp_path / "home").mkdir()
    (tmp_path / "hf").mkdir()
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(socket, "create_connection", MagicMock(side_effect=OSError("down")))
    monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    _block_imports(monkeypatch, "yt_dlp", "faster_whisper", "mlx_whisper")
    return tmp_path


class TestDoctor:
    def test_missing_critical_deps_exit_1(self, isolated_env):
        result = runner.invoke(app, [])
        assert result.exit_code == 1
        out = result.output
        assert "yt-dlp" in out and "FAIL" in out
        assert "pip install yt-dlp" in out or "uv tool install" in out
        assert "faster-whisper" in out and "FAIL" in out
        # non-fatal checks still render
        assert "ffmpeg" in out and "WARN" in out
        assert "mlx-whisper" in out and "INFO" in out
        assert "whisper model" in out and "WARN" in out
        assert "tt binary" in out and "WARN" in out
        assert "network" in out and "FAIL" in out
        assert "output dir" in out and "PASS" in out

    def test_all_good_exit_0(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        (tmp_path / "home").mkdir()
        hub = tmp_path / "hf" / "hub"
        (hub / "models--Systran--faster-whisper-small").mkdir(parents=True)

        monkeypatch.setitem(sys.modules, "yt_dlp", _fake_ytdlp())
        monkeypatch.setitem(
            sys.modules, "faster_whisper", _fake_module("faster_whisper", __version__="1.2.1")
        )
        monkeypatch.setitem(sys.modules, "mlx_whisper", _fake_module("mlx_whisper"))

        monkeypatch.setattr(
            doctor.shutil,
            "which",
            lambda name: {"ffmpeg": "/usr/bin/ffmpeg", "tt": "/usr/local/bin/tt"}.get(name),
        )
        monkeypatch.setattr(socket, "create_connection", MagicMock(return_value=_ctx_manager()))
        monkeypatch.setattr(
            doctor.subprocess,
            "run",
            lambda *a, **k: types.SimpleNamespace(stdout="tt 0.1.0\n", stderr=""),
        )
        monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(doctor.sys, "platform", "linux")

        result = runner.invoke(app, [])
        assert result.exit_code == 0, result.output
        assert result.output.count("PASS") >= 4
        assert "cached in HF hub" in result.output

    def test_old_ytdlp_warns_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.setitem(sys.modules, "yt_dlp", _fake_ytdlp("2024.01.01"))
        monkeypatch.setitem(sys.modules, "faster_whisper", _fake_module("faster_whisper"))
        monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/" + name)
        monkeypatch.setattr(socket, "create_connection", MagicMock(return_value=_ctx_manager()))
        monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(doctor.sys, "platform", "linux")

        name, status, detail = doctor._check_ytdlp()
        assert name == "yt-dlp"
        assert status == "WARN"
        assert "2024.01.01" in detail

    def test_network_failure_nonfatal(self, isolated_env, monkeypatch):
        # only yt-dlp/faster-whisper FAILs are fatal; network FAIL -> exit 0
        monkeypatch.setitem(sys.modules, "yt_dlp", _fake_ytdlp())
        monkeypatch.setitem(sys.modules, "faster_whisper", _fake_module("faster_whisper"))
        result = runner.invoke(app, [])
        assert result.exit_code == 0, result.output
        assert "network" in result.output and "FAIL" in result.output

    def test_faster_whisper_missing_is_fatal(self, isolated_env, monkeypatch):
        monkeypatch.setitem(sys.modules, "yt_dlp", _fake_ytdlp())
        result = runner.invoke(app, [])
        assert result.exit_code == 1
        assert "faster-whisper" in result.output and "FAIL" in result.output

    def test_model_cache_detected(self, tmp_path, monkeypatch):
        hub = tmp_path / "hf" / "hub"
        (hub / "models--Systran--faster-whisper-small").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        name, status, detail = doctor._check_whisper_model()
        assert name == "whisper model"
        assert status == "INFO"
        assert "small" in detail

    def test_model_cache_absent_warns(self, tmp_path, monkeypatch):
        (tmp_path / "home").mkdir()
        (tmp_path / "hf").mkdir()
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        _, status, detail = doctor._check_whisper_model()
        assert status == "WARN"
        assert "466MB" in detail

    def test_mlx_skipped_off_apple_silicon(self, monkeypatch):
        monkeypatch.setattr(doctor.sys, "platform", "linux")
        monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
        _, status, detail = doctor._check_mlx_whisper()
        assert status == "INFO"
        assert "skipped" in detail

    def test_mlx_checked_on_arm64(self, monkeypatch):
        monkeypatch.setattr(doctor.sys, "platform", "darwin")
        monkeypatch.setattr(doctor.platform, "machine", lambda: "arm64")
        _block_imports(monkeypatch, "mlx_whisper")
        _, status, detail = doctor._check_mlx_whisper()
        assert status == "WARN"
        assert "faster-whisper" in detail

    def test_mlx_pass_on_arm64(self, monkeypatch):
        monkeypatch.setattr(doctor.sys, "platform", "darwin")
        monkeypatch.setattr(doctor.platform, "machine", lambda: "arm64")
        monkeypatch.setitem(sys.modules, "mlx_whisper", _fake_module("mlx_whisper"))
        _, status, _ = doctor._check_mlx_whisper()
        assert status == "PASS"
