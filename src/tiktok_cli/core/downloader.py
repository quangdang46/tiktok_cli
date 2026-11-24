"""yt-dlp wrapper for TikTok: metadata, captions, audio.

This is the ONLY module in tiktok-cli allowed to import ``yt_dlp`` - all
upstream churn is contained here (same isolation rule as omni-transcriber's
``downloader.py``). If the Python API ever breaks, the escape hatch is
``subprocess`` + ``--dump-json`` right inside this file.

Standing rules:
  * ``yt_dlp`` is imported lazily inside ``_import_ytdlp()`` so
    ``tiktok --help`` stays fast and the module imports without yt-dlp.
  * Every public method converts yt-dlp failures into ``UserError`` via
    ``core.errors.translate_download_error`` - callers never see a
    ``yt_dlp`` exception.
  * ``format`` is ``bestaudio/best`` and there is deliberately NO
    ``FFmpegExtractAudio`` postprocessor: faster-whisper/PyAV decodes
    whatever container arrives.
  * yt-dlp gets a logger that writes to stderr. stdout carries only
    transcript/plain output.
"""

from __future__ import annotations

import glob
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from tiktok_cli.core.errors import UserError, translate_download_error

__all__ = ["YtdlpClient"]


# yt-dlp priority order; every runtime found on PATH is enabled and yt-dlp
# picks the highest-priority one it can use. Ported from omni-transcriber's
# downloader.py: as of recent yt-dlp only "deno" is enabled by default, and an
# installed Node would otherwise go unused.
_JS_RUNTIMES = ("deno", "node", "quickjs", "bun")


def _enabled_js_runtimes() -> dict[str, dict[str, str | None]]:
    """Enable every JavaScript runtime that is actually installed."""
    found: dict[str, dict[str, str | None]] = {}
    for name in _JS_RUNTIMES:
        binary = shutil.which(name)
        if binary:
            found[name] = {"path": binary}
    # Falling back to the default keeps yt-dlp's own actionable warning intact.
    return found or {"deno": {}}


def _import_ytdlp() -> Any:
    """Import yt_dlp lazily; missing install is a UserError, not ImportError."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise UserError(
            "yt-dlp is required but not installed.",
            hint="Install it with your package manager (pip install yt-dlp, "
            "brew install yt-dlp) or reinstall tiktok-cli.",
        ) from exc
    return yt_dlp


class _StderrLogger:
    """Routes every yt-dlp message to stderr and collects fatal errors.

    ``warning``/``info``/``debug`` print only in verbose mode (warnings are
    deduplicated - YouTube repeats the same degraded-metadata warning per
    entry). ``error`` is collected so callers can resurface it translated.
    """

    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.errors: list[str] = []
        self._warned: set[str] = set()

    def debug(self, msg: str) -> None:
        if self.verbose:
            sys.stderr.write(f"{msg}\n")

    def info(self, msg: str) -> None:
        if self.verbose:
            sys.stderr.write(f"{msg}\n")

    def warning(self, msg: str) -> None:
        text = msg.strip()
        if self.verbose:
            sys.stderr.write(f"warning: {text}\n")
        elif text not in self._warned:
            self._warned.add(text)
            sys.stderr.write(f"warning: {text}\n")

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        if self.verbose:
            sys.stderr.write(f"error: {msg}\n")


def _resolve_path(ydl: Any, info: dict[str, Any]) -> Path | None:
    """Find what yt-dlp actually wrote; the extension is not knowable up front."""
    for download in info.get("requested_downloads") or ():
        candidate = download.get("filepath") or download.get("_filename")
        if candidate and Path(candidate).exists():
            return Path(candidate)

    candidate = info.get("filepath") or info.get("_filename")
    if candidate and Path(candidate).exists():
        return Path(candidate)

    try:
        guess = Path(ydl.prepare_filename(info))
    except Exception:  # noqa: BLE001 - yt-dlp may raise anything here; path is best-effort
        return None
    if guess.exists():
        return guess
    siblings = sorted(guess.parent.glob(f"{glob.escape(guess.stem)}.*"))
    return siblings[0] if siblings else None


def _lang_from_filename(name: str, video_id: str | None) -> str | None:
    """Extract the subtitle language from a ``<id>.<lang>.vtt`` filename."""
    stem = name.removesuffix(".vtt")
    if video_id:
        prefix = f"{video_id}."
        return stem[len(prefix) :] or None if stem.startswith(prefix) else None
    # No id to strip: the last dot-component is the lang, the rest is the id.
    parts = stem.split(".")
    return parts[-1] if len(parts) > 1 and parts[-1] else None


class YtdlpClient:
    """Thin wrapper around ``yt_dlp.YoutubeDL`` for TikTok URLs.

    Cookies are opt-in: ``cookies_from_browser``/``cookies_file`` map to
    yt-dlp's ``cookiesfrombrowser``/``cookiefile`` options and are only set
    when provided.
    """

    def __init__(
        self,
        cookies_from_browser: str | None = None,
        cookies_file: str | Path | None = None,
        verbose: bool = False,
    ) -> None:
        self.cookies_from_browser = cookies_from_browser
        self.cookies_file = Path(cookies_file) if cookies_file else None
        self.verbose = verbose

    def _ydl_opts(self, base_dir: Path | None, **overrides: Any) -> dict[str, Any]:
        """Shared YoutubeDL options; ``overrides`` wins on conflicts."""
        opts: dict[str, Any] = {
            "quiet": not self.verbose,
            "no_warnings": not self.verbose,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            "noprogress": True,  # callers draw their own progress
            "js_runtimes": _enabled_js_runtimes(),
            "logger": _StderrLogger(self.verbose),
            # Deliberately no "postprocessors": no FFmpegExtractAudio, ever.
        }
        if base_dir is not None:
            opts["outtmpl"] = str(Path(base_dir) / "%(id)s.%(ext)s")
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        if self.cookies_file is not None:
            opts["cookiefile"] = str(self.cookies_file)
        opts.update(overrides)
        return opts

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
        """Fetch video metadata without downloading media."""
        yt_dlp = _import_ytdlp()
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts(None)) as ydl:
                info = ydl.extract_info(url, download=download)
        except Exception as exc:
            raise translate_download_error(exc) from exc
        return info or {}

    def download_subtitles(
        self, url: str, out_dir: Path, langs: str = "vi.*,en.*,vi,en,all"
    ) -> list[Path]:
        """Download caption tracks as .vtt files into ``out_dir``.

        TIKTOK GOTCHA: yt-dlp's ``extract_info`` JSON does NOT list caption
        tracks for TikTok even when they exist, so ``info['subtitles']`` /
        ``info['automatic_captions']`` cannot be trusted here. The only
        reliable probe is to actually request the subtitle download and see
        what lands on disk - hence the ``*.vtt`` glob below instead of
        inspecting the returned info dict. TODO: re-verify against a real
        TikTok URL at runtime; if yt-dlp ever starts reporting captions in
        extract_info, keep the download path anyway (it is the source of the
        files we return).
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        yt_dlp = _import_ytdlp()
        opts = self._ydl_opts(
            out_dir,
            skip_download=True,
            writesubtitles=True,
            writeautomaticsub=True,
            subformats=["vtt"],
            sublangs=langs,
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # download=True is required: with download=False yt-dlp only
                # extracts metadata and never writes subtitle files, even
                # though skip_download suppresses the A/V download itself.
                ydl.extract_info(url, download=True)
        except Exception as exc:
            raise translate_download_error(exc) from exc
        # Whatever yt-dlp wrote is the truth; return every .vtt, sorted.
        return sorted(out_dir.glob("*.vtt"))

    def download_audio(self, url: str, tmp_dir: Path) -> Path:
        """Download the best audio stream into ``tmp_dir``; return its path."""
        tmp_dir.mkdir(parents=True, exist_ok=True)
        yt_dlp = _import_ytdlp()
        opts = self._ydl_opts(tmp_dir, format="bestaudio/best")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True) or {}
                path = _resolve_path(ydl, info)
        except Exception as exc:
            raise translate_download_error(exc) from exc
        if path is None:
            raise UserError(
                f"yt-dlp produced no audio file for {url}.",
                hint="Check that the link has an audio track and is reachable.",
            )
        return path

    def list_subtitle_langs(self, url: str) -> dict[str, list[str]]:
        """Best-effort map of available caption languages to formats.

        Works around the same TikTok gotcha as ``download_subtitles``: a
        throwaway download-into-tempdir pass is the only reliable way to see
        which caption tracks exist, so this globs the resulting ``*.vtt``
        filenames (``<id>.<lang>.vtt``) rather than trusting
        ``info['subtitles']``.
        """
        yt_dlp = _import_ytdlp()
        with tempfile.TemporaryDirectory(prefix="tiktok-cli-subs-") as tmp:
            out_dir = Path(tmp)
            opts = self._ydl_opts(
                out_dir,
                skip_download=True,
                writesubtitles=True,
                writeautomaticsub=True,
                subformats=["vtt"],
                sublangs="all",
            )
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True) or {}
            except Exception as exc:
                raise translate_download_error(exc) from exc
            video_id = info.get("id")
            langs: dict[str, list[str]] = {}
            for path in sorted(out_dir.glob("*.vtt")):
                lang = _lang_from_filename(path.name, video_id)
                if lang is None:
                    continue
                langs.setdefault(lang, [])
                if "vtt" not in langs[lang]:
                    langs[lang].append("vtt")
            return langs
