"""`tiktok doctor` — dependency and environment health check.

Prints a PASS/WARN/FAIL/INFO table to stdout. All heavy imports (yt_dlp,
faster_whisper, mlx_whisper) happen lazily inside the check functions so
the module itself — and `tiktok --help` — stays fast.

Exit code is 0 unless yt-dlp or faster-whisper is missing (exit 1), so it
is safe to wire into CI/scripts.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

_STATUS_STYLES = {
    "PASS": "green",
    "WARN": "yellow",
    "FAIL": "red",
    "INFO": "cyan",
}

# Checks whose FAIL is fatal for the CLI's core path.
_FATAL_CHECKS = {"yt-dlp", "faster-whisper"}


def _version_at_least(version: str, major: int, minor: int) -> bool:
    try:
        parts = [int(p) for p in version.split(".")[:2]]
    except ValueError:
        return True  # unparseable -> don't warn
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts) >= (major, minor)


def _check_ytdlp() -> tuple[str, str, str]:
    try:
        import yt_dlp

        version = yt_dlp.version.__version__
    except Exception:  # noqa: BLE001 — any import/attr failure means unusable
        return (
            "yt-dlp",
            "FAIL",
            "not installed — fix: pip install yt-dlp  (or: uv tool install --with yt-dlp)",
        )
    if _version_at_least(version, 2025, 1):
        return ("yt-dlp", "PASS", f"{version}")
    return ("yt-dlp", "WARN", f"{version} — old; fix: pip install -U yt-dlp")


def _check_ffmpeg() -> tuple[str, str, str]:
    path = shutil.which("ffmpeg")
    if path:
        return ("ffmpeg", "PASS", path)
    return (
        "ffmpeg",
        "WARN",
        "not on PATH — not required (faster-whisper/PyAV decodes audio directly)",
    )


def _check_faster_whisper() -> tuple[str, str, str]:
    try:
        import faster_whisper

        version = getattr(faster_whisper, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        return ("faster-whisper", "FAIL", "not installed — fix: pip install faster-whisper")
    return ("faster-whisper", "PASS", str(version))


def _check_mlx_whisper() -> tuple[str, str, str]:
    is_apple_silicon = sys.platform == "darwin" and platform.machine() == "arm64"
    if not is_apple_silicon:
        return ("mlx-whisper", "INFO", "skipped — only relevant on macOS arm64")
    try:
        import mlx_whisper  # noqa: F401
    except Exception:  # noqa: BLE001
        return (
            "mlx-whisper",
            "WARN",
            (
                "not installed — engine auto falls back to faster-whisper "
                "(fix: pip install 'tiktok-cli[mlx]')"
            ),
        )
    return ("mlx-whisper", "PASS", "installed — engine auto will prefer it")


def _whisper_model_cache_dirs() -> list[Path]:
    # huggingface_hub resolves its cache from HF_HOME (default ~/.cache/huggingface);
    # Path.home() alone misses custom HF_HOME and HOME-on-Windows cases.
    hf_home = os.environ.get("HF_HOME")
    base = Path(hf_home) if hf_home else Path.home() / ".cache" / "huggingface"
    hub = base / "hub"
    return sorted(hub.glob("models--Systran--faster-whisper-*")) + sorted(
        hub.glob("models--mlx-community--whisper-*")
    )


def _check_whisper_model() -> tuple[str, str, str]:
    cached = _whisper_model_cache_dirs()
    if cached:
        names = ", ".join(sorted(d.name for d in cached))
        return ("whisper model", "INFO", f"cached in HF hub: {names}")
    return (
        "whisper model",
        "WARN",
        "no faster-whisper model cached — first transcribe downloads ~466MB (small)",
    )


def _check_tt() -> tuple[str, str, str]:
    path = shutil.which("tt")
    if not path:
        return (
            "tt binary",
            "WARN",
            (
                "optional — needed for search/list/tag/trending/discover "
                "(install: go install github.com/tamnd/tiktok-cli/cmd/tt@latest)"
            ),
        )
    try:
        out = subprocess.run(
            ["tt", "--version"], check=False, capture_output=True, text=True, timeout=5
        )
        version = (out.stdout or out.stderr).strip().splitlines()
        detail = f"{path} ({version[0]})" if version and version[0] else path
    except Exception:  # noqa: BLE001 — version probe is best-effort
        detail = path
    return ("tt binary", "PASS", detail)


def _check_network() -> tuple[str, str, str]:
    try:
        with socket.create_connection(("www.tiktok.com", 443), timeout=5):
            pass
    except OSError as exc:
        return ("network", "FAIL", f"cannot reach www.tiktok.com:443 ({exc})")
    return ("network", "PASS", "www.tiktok.com:443 reachable")


def _check_output_dir() -> tuple[str, str, str]:
    out_dir = Path("tiktok-transcripts")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = Path(tempfile.mkdtemp(dir=out_dir))
        probe.rmdir()
    except OSError as exc:
        return ("output dir", "FAIL", f"{out_dir} not writable ({exc})")
    return ("output dir", "PASS", f"{out_dir.resolve()} is writable")


_CHECKS = (
    _check_ytdlp,
    _check_ffmpeg,
    _check_faster_whisper,
    _check_mlx_whisper,
    _check_whisper_model,
    _check_tt,
    _check_network,
    _check_output_dir,
)


def doctor() -> None:
    """Run all health checks and print a PASS/WARN/FAIL table."""
    table = Table(title="tiktok doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    fatal = False
    for check in _CHECKS:
        name, status, detail = check()
        if status == "FAIL" and name in _FATAL_CHECKS:
            fatal = True
        table.add_row(name, f"[{_STATUS_STYLES[status]}]{status}[/]", detail)

    console.print(table)
    if fatal:
        raise typer.Exit(code=1)
