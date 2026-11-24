"""``tiktok transcript <urls...>`` — caption-first transcripts with Whisper fallback.

Sequential per-URL processing via ``pipeline.process_video``. stdout carries
ONLY the per-video summary lines (``VIDEO_ID | source | cues=N | dir``);
everything else — stage notes, yt-dlp warnings, the final counts — goes to
stderr through a rich Console so agents can pipe stdout safely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from tiktok_cli.core.errors import UserError
from tiktok_cli.pipeline import VideoResult, process_video

err_console = Console(stderr=True)

_FORMATS = ("txt", "srt", "vtt", "json", "md", "all")

# status -> short source label for the stdout summary line.
_SOURCE_LABELS = {
    "caption": "tiktok-captions",
    "whisper": "whisper",
}


def _progress(msg: str) -> None:
    err_console.print(f"  [dim]{msg}[/dim]")


def _summary_line(result: VideoResult) -> str:
    vid = result.video_id or result.url
    source = _SOURCE_LABELS.get(result.status, result.status)
    line = f"{vid} | {source} | cues={result.cue_count} | {result.artifact_dir}"
    if result.error:
        line += f" | error: {result.error}"
    return line


def transcript(
    urls: Annotated[
        list[str],
        typer.Argument(help="One or more TikTok video URLs (shortlinks OK)."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory for per-video artifact folders.",
        ),
    ] = Path("tiktok-transcripts"),
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Whisper model name (fallback path)."),
    ] = "small",
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Whisper language hint; auto-detect by default."),
    ] = None,
    whisper: Annotated[
        str,
        typer.Option(
            "--whisper",
            help="auto = whisper only when no captions; always = skip captions; never = captions only.",
        ),
    ] = "auto",
    engine: Annotated[
        str,
        typer.Option("--engine", help="auto|faster|mlx (Whisper backend)."),
    ] = "auto",
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output formats: txt|srt|vtt|json|md|all."),
    ] = "all",
    keep_audio: Annotated[
        bool,
        typer.Option("--keep-audio", help="Keep the downloaded audio after transcribing."),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Bypass the transcript.json cache and reprocess."),
    ] = False,
    cookies_from_browser: Annotated[
        str | None,
        typer.Option("--cookies-from-browser", help="Browser to read cookies from (e.g. firefox)."),
    ] = None,
    cookies: Annotated[
        str | None,
        typer.Option("--cookies", help="Netscape cookies.txt file for authenticated requests."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show yt-dlp/whisper debug output on stderr."),
    ] = False,
) -> None:
    """Transcribe TikTok videos to txt/srt/vtt/json/md via captions or Whisper."""
    if whisper not in ("auto", "always", "never"):
        raise typer.BadParameter("--whisper must be auto, always, or never")
    if engine not in ("auto", "faster", "mlx"):
        raise typer.BadParameter("--engine must be auto, faster, or mlx")
    if fmt not in _FORMATS:
        raise typer.BadParameter(f"--format must be one of: {', '.join(_FORMATS)}")

    counts: dict[str, int] = {}
    failures = 0

    for url in urls:
        err_console.print(f"[bold]{url}[/bold]")
        try:
            result = process_video(
                url,
                output_dir,
                model=model,
                language=language,
                whisper=whisper,
                engine=engine,
                fmt=fmt,
                keep_audio=keep_audio,
                refresh=refresh,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies,
                verbose=verbose,
                progress=_progress,
            )
        except UserError as exc:
            err_console.print(str(exc))
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - never let one URL kill the batch
            err_console.print(f"error: {exc}")
            failures += 1
            continue

        counts[result.status] = counts.get(result.status, 0) + 1
        if result.status == "failed":
            failures += 1
        typer.echo(_summary_line(result))

    summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    err_console.print(f"done: {summary or 'nothing processed'} -> {output_dir}")
    if failures:
        raise typer.Exit(code=1)
