"""Shared per-video transcript pipeline.

Used by ``commands/transcript.py`` and ``commands/batch.py``: one URL in,
one :class:`VideoResult` out. Per-video failures never raise — they come
back as ``status="failed"`` so a batch run survives a bad link. Only
argument-validation problems (bad ``--whisper``/``--engine``/``--format``,
non-TikTok URL) raise :class:`UserError`.

Flow (PLAN.md section 5):

1. ``is_tiktok_url`` gate, then ``YtdlpClient.extract_info`` — the video id
   ALWAYS comes from ``info["id"]``, never parsed from the URL (shortlinks).
2. Photo/slideshow posts -> ``photo-post`` (metadata + index, no transcripts).
3. Cache: ``VideoDir.is_processed()`` and not ``refresh`` -> ``skipped-cached``.
4. Caption path (skipped when ``whisper="always"``): download .vtt subs into
   ``<video_dir>/subs``, pick the best file, parse, render, write.
5. Whisper path (when no usable captions and ``whisper != "never"``):
   download audio to a temp dir inside the video dir, transcribe, render,
   write; audio deleted unless ``keep_audio``.
6. ``whisper="never"`` with no captions -> ``no-captions`` (metadata + index).
7. ``append_index`` runs for every outcome.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tiktok_cli.core import captions, post_page, stt
from tiktok_cli.core.artifacts import (
    STATUS_CAPTION,
    STATUS_FAILED,
    STATUS_NO_AUDIO,
    STATUS_NO_CAPTIONS,
    STATUS_PHOTO_POST,
    STATUS_SKIPPED_CACHED,
    STATUS_WHISPER,
    VideoDir,
    append_index,
    compact_metadata,
)
from tiktok_cli.core.captions import Cue
from tiktok_cli.core.downloader import YtdlpClient
from tiktok_cli.core.errors import UserError
from tiktok_cli.core.url import (
    classify_url,
    is_tiktok_url,
    photo_to_video_url,
    video_id_from_url,
)

_WHISPER_MODES = frozenset({"auto", "always", "never"})
_ENGINE_NAMES = frozenset({"auto", "faster", "mlx"})
_FORMAT_NAMES = frozenset({"txt", "srt", "vtt", "json", "md", "all"})

# yt-dlp/faster-whisper phrasing that means "this post has no audio track".
_NO_AUDIO_MARKERS = (
    "no audio",
    "has no audio",
    "does not have any audio",
    "requested format is not available",
)

ProgressFn = Callable[[str], None]


@dataclass
class VideoResult:
    """Outcome of processing one URL."""

    video_id: str
    url: str
    status: str  # caption|whisper|no-captions|no-audio|photo-post|failed|skipped-cached
    artifact_dir: Path
    transcript_txt: Path | None
    cue_count: int
    language: str | None
    error: str | None = None


def _validate_args(whisper: str, engine: Any, fmt: str) -> None:
    """Reject bad flag values before any network work; raises UserError."""
    if whisper not in _WHISPER_MODES:
        raise UserError(
            f"invalid --whisper value {whisper!r}.",
            hint="Choose one of: auto, always, never.",
        )
    if isinstance(engine, str) and engine not in _ENGINE_NAMES:
        raise UserError(
            f"invalid --engine value {engine!r}.",
            hint="Choose one of: auto, faster, mlx.",
        )
    if fmt not in _FORMAT_NAMES:
        raise UserError(
            f"invalid --format value {fmt!r}.",
            hint="Choose one of: txt, srt, vtt, json, md, all.",
        )


def _is_photo_post(url: str, info: dict[str, Any]) -> bool:
    """True for TikTok photo/slideshow posts (no video, no captions)."""
    if classify_url(url) == "photo":
        return True
    webpage_url = str(info.get("webpage_url") or "")
    if "/photo/" in webpage_url:
        return True
    # yt-dlp surfaces multi-image posts as playlists; a real video never is.
    return info.get("_type") == "playlist" or bool(info.get("is_image_post"))


def _caption_lang(path: Path) -> str | None:
    """Language tag from a yt-dlp caption filename: ``<id>.<lang>.vtt``."""
    parts = path.stem.split(".")
    if len(parts) < 2:
        return None
    return parts[-1].lower() or None


def _is_no_audio_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _NO_AUDIO_MARKERS)


def _run_stt(
    audio_path: Path,
    *,
    model: str,
    language: str | None,
    engine: Any,
) -> stt.STTResult:
    """Transcribe via the ``engine`` param: a selector string or an engine object.

    Accepting an engine instance lets callers (batch) reuse one loaded model
    across many videos; a string goes through ``stt.transcribe_media``.
    """
    if isinstance(engine, str):
        return stt.transcribe_media(audio_path, model=model, language=language, engine=engine)
    return engine.transcribe(audio_path, language=language)


def _dicts_to_cues(cue_dicts: list[dict[str, Any]]) -> list[Cue]:
    """Convert STTResult cue dicts to captions.Cue with formatted times."""
    cues: list[Cue] = []
    for item in cue_dicts:
        start = float(item.get("start") or 0.0)
        end = float(item.get("end") or start)
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cues.append(
            Cue(
                start=round(start, 3),
                end=round(end, 3),
                start_time=captions.format_time(start),
                end_time=captions.format_time(end),
                text=text,
            )
        )
    return cues


def _render_and_write(
    video_dir: VideoDir,
    cues: list[Cue],
    info: dict[str, Any],
    fmt: str,
    transcript_source: str,
    language: str | None,
) -> Path | None:
    """Render transcripts + metadata.json; return the transcript.txt path."""
    meta = compact_metadata(info, transcript_source, len(cues), language)
    rendered = captions.render_all(cues, meta, fmt)
    if isinstance(rendered, str):
        rendered = {fmt: rendered}
    written = video_dir.write_transcripts(rendered)
    video_dir.write_metadata(meta)
    return written.get("txt")


def _result(
    video_dir: VideoDir,
    url: str,
    status: str,
    *,
    transcript_txt: Path | None = None,
    cue_count: int = 0,
    language: str | None = None,
    duration: float | None = None,
    transcript_source: str | None = None,
    error: str | None = None,
) -> VideoResult:
    """Build a VideoResult and append its index.jsonl record."""
    record: dict[str, Any] = {
        "video_id": video_dir.video_id,
        "url": url,
        "status": status,
        "language": language,
        "cue_count": cue_count,
        "duration": duration,
        "artifact_dir": str(video_dir.path),
        "transcript_source": transcript_source,
    }
    if error:
        record["error"] = error
    append_index(video_dir.path.parent, record)
    return VideoResult(
        video_id=video_dir.video_id,
        url=url,
        status=status,
        artifact_dir=video_dir.path,
        transcript_txt=transcript_txt,
        cue_count=cue_count,
        language=language,
        error=error,
    )


def _write_stub_metadata(
    video_dir: VideoDir, info: dict[str, Any], transcript_source: str = "none"
) -> None:
    """metadata.json only (no transcripts) for skip/failure statuses."""
    video_dir.write_metadata(compact_metadata(info, transcript_source, 0, None))


def _caption_path(
    client: YtdlpClient,
    url: str,
    video_dir: VideoDir,
) -> tuple[list[Cue], str | None, str] | None:
    """Try the caption path; return (cues, lang, source) or None if no captions."""
    vtt_files = client.download_subtitles(url, video_dir.subs_dir)
    picked = captions.pick_caption_file(vtt_files)
    if picked is None:
        return None
    cues = captions.parse_vtt(picked)
    if not cues:
        return None
    lang = _caption_lang(picked)
    return cues, lang, f"tiktok-captions:{lang or 'unknown'}"


def _whisper_path(
    client: YtdlpClient,
    url: str,
    video_dir: VideoDir,
    info: dict[str, Any],
    *,
    model: str,
    language: str | None,
    engine: Any,
    fmt: str,
    keep_audio: bool,
) -> VideoResult:
    """Download audio, transcribe, render. Raises; caller maps to failed/no-audio."""
    video_dir.ensure()
    with tempfile.TemporaryDirectory(prefix="audio-", dir=video_dir.path) as tmp:
        audio_path = client.download_audio(url, Path(tmp))
        stt_result = _run_stt(audio_path, model=model, language=language, engine=engine)
        if keep_audio:
            dest = video_dir.path / f"audio{audio_path.suffix or '.audio'}"
            shutil.move(str(audio_path), dest)
    cues = _dicts_to_cues(stt_result.cues)
    lang = stt_result.language or language or None
    engine_name = stt_result.engine or (
        engine if isinstance(engine, str) else getattr(engine, "name", "custom")
    )
    source = f"whisper:{engine_name}:{stt_result.model or model}:{lang or 'auto'}"
    transcript_txt = _render_and_write(video_dir, cues, info, fmt, source, lang)
    return _result(
        video_dir,
        url,
        STATUS_WHISPER,
        transcript_txt=transcript_txt,
        cue_count=len(cues),
        language=lang,
        duration=stt_result.duration or None,
        transcript_source=source,
    )


def _download_images_for_photo_post(url: str, video_dir: VideoDir) -> int:
    """Best-effort slideshow image download for ``/photo/`` posts.

    Fetches ``itemStruct`` from the public post page (JS-challenge solved),
    downloads ``imagePost.images`` into ``VIDEO_ID/images/`` and writes
    ``images.json``. Returns the number of images saved; raises on hard
    failures (caller treats as best-effort).
    """
    item = post_page.fetch_item_struct(photo_to_video_url(url))
    if not item:
        return 0
    files = post_page.download_post_images(item, video_dir.path / "images")
    if files:
        post_page.write_images_manifest(video_dir.path, item, files)
    return len(files)


def process_video(
    url: str,
    output_dir: Path | str,
    *,
    model: str = "small",
    language: str | None = None,
    whisper: str = "auto",
    engine: Any = "auto",
    fmt: str = "all",
    keep_audio: bool = False,
    refresh: bool = False,
    cookies_from_browser: str | None = None,
    cookies_file: str | Path | None = None,
    verbose: bool = False,
    progress: ProgressFn | None = None,
) -> VideoResult:
    """Process one TikTok URL end-to-end; never raises for per-video failures.

    ``engine`` may be a selector string (``"auto"|"faster"|"mlx"``) or an
    already-constructed engine object with ``.transcribe(path, language=...)``
    so batch runs can reuse a loaded Whisper model.
    """
    _validate_args(whisper, engine, fmt)
    if not is_tiktok_url(url):
        raise UserError(
            f"not a TikTok URL: {url}",
            hint="Pass a tiktok.com video/photo link (vm./vt. shortlinks OK).",
        )

    def note(msg: str) -> None:
        if progress is not None:
            progress(msg)

    client = YtdlpClient(
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        verbose=verbose,
    )
    output_dir = Path(output_dir)
    video_dir: VideoDir | None = None
    info: dict[str, Any] = {}

    # Photo posts (/photo/<id>) are rejected by yt-dlp's TikTok extractor,
    # but the same id resolves under /video/ and carries an audio track.
    fetch_url = photo_to_video_url(url)

    try:
        note("fetching video info")
        info = client.extract_info(fetch_url) or {}
        video_id = str(info.get("id") or "")
        video_dir = VideoDir(output_dir, video_id)
        video_dir.write_source_info(info, refresh=refresh)

        if _is_photo_post(fetch_url, info):
            if classify_url(url) == "photo":
                note("downloading slideshow images")
                try:
                    _download_images_for_photo_post(url, video_dir)
                except Exception as exc:  # noqa: BLE001 - images are best-effort
                    note(f"warning: could not fetch slideshow images: {exc}")
            _write_stub_metadata(video_dir, info)
            return _result(video_dir, url, STATUS_PHOTO_POST)

        if video_dir.is_processed() and not refresh:
            return _result(video_dir, url, STATUS_SKIPPED_CACHED)

        if classify_url(url) == "photo":
            note("downloading slideshow images")
            try:
                _download_images_for_photo_post(url, video_dir)
            except Exception as exc:  # noqa: BLE001 - images are best-effort
                note(f"warning: could not fetch slideshow images: {exc}")

        caption_data: tuple[list[Cue], str | None, str] | None = None
        if whisper != "always":
            note("downloading captions")
            caption_data = _caption_path(client, fetch_url, video_dir)

        if caption_data is not None:
            cues, lang, source = caption_data
            transcript_txt = _render_and_write(video_dir, cues, info, fmt, source, lang)
            return _result(
                video_dir,
                url,
                STATUS_CAPTION,
                transcript_txt=transcript_txt,
                cue_count=len(cues),
                language=lang,
                duration=info.get("duration"),
                transcript_source=source,
            )

        if whisper != "never":
            note("no captions - transcribing audio")
            try:
                return _whisper_path(
                    client,
                    fetch_url,
                    video_dir,
                    info,
                    model=model,
                    language=language,
                    engine=engine,
                    fmt=fmt,
                    keep_audio=keep_audio,
                )
            except Exception as exc:
                if _is_no_audio_error(exc):
                    _write_stub_metadata(video_dir, info)
                    return _result(video_dir, url, STATUS_NO_AUDIO, error=str(exc))
                raise

        # Captions wanted but none exist and whisper is disabled.
        _write_stub_metadata(video_dir, info)
        return _result(video_dir, url, STATUS_NO_CAPTIONS)

    except Exception as exc:  # noqa: BLE001 - per-video isolation for batch
        error = str(exc)
        if video_dir is not None:
            try:
                _write_stub_metadata(video_dir, info)
            except Exception as meta_exc:  # noqa: BLE001 - metadata is best-effort
                note(f"warning: could not write metadata.json: {meta_exc}")
            return _result(video_dir, url, STATUS_FAILED, error=error)
        # Failure before we had a video id: still log to index.jsonl.
        append_index(output_dir, _index_record_for_failure(url, error))
        return VideoResult(
            video_id=video_id_from_url(url) or "",
            url=url,
            status=STATUS_FAILED,
            artifact_dir=output_dir,
            transcript_txt=None,
            cue_count=0,
            language=None,
            error=error,
        )


def _index_record_for_failure(url: str, error: str) -> dict[str, Any]:
    return {
        "video_id": video_id_from_url(url),
        "url": url,
        "status": STATUS_FAILED,
        "language": None,
        "cue_count": 0,
        "duration": None,
        "artifact_dir": None,
        "error": error,
    }
