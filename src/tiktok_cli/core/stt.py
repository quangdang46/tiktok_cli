"""Speech-to-text engines: dual-backend Whisper wrapper.

Two interchangeable backends with the same contract
(``transcribe(audio_path, language) -> STTResult``):

- ``mlx``    — mlx-whisper, macOS Apple Silicon only (GPU via Metal).
               Used by ``engine="auto"`` when ``sys.platform == "darwin"``,
               ``platform.machine() == "arm64"`` and ``mlx_whisper`` imports.
- ``faster`` — faster-whisper (CTranslate2 + bundled PyAV), Linux/Windows/
               macOS, CPU or CUDA. The fallback everywhere else.

Anti-hallucination settings are mandatory on both backends (ported from
douyin-teardown's ``transcribe.py``):

- ``condition_on_previous_text=False`` — prevents cascade hallucinations.
- ``temperature=0.0`` — greedy decoding.
- Segments with ``no_speech_prob > 0.6`` are dropped.
- faster-whisper additionally uses ``vad_filter=True``, ``beam_size=1``.

faster-whisper is constructed with ``device="auto"`` and
``compute_type="auto"``. ``compute_type="auto"`` picks int8 on CPU and float16
on CUDA, which is what we want: explicit ``"int8"`` would force CPU-precision
math even on a GPU. mlx-whisper has no compute-type knob (it is always MLX
float16-ish on Apple Silicon), so there is nothing to configure there.

Model name mapping:

- faster-whisper accepts names as-is: ``tiny|base|small|medium|large-v3|turbo|
  distil-large-v3``, a HuggingFace repo id, or a local directory. Default
  ``"small"``.
- mlx-whisper needs an HF repo id; short names go through ``_MLX_MODEL_MAP``
  to ``mlx-community/whisper-*-mlx`` repos. Names already containing ``/``
  (HF repo ids or local paths) pass through unchanged.

Heavy imports (``faster_whisper``, ``mlx_whisper``) happen inside functions
only — importing this module must stay cheap so ``tiktok --help`` is fast.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tiktok_cli.core.errors import UserError

_NO_SPEECH_THRESHOLD = 0.6
_DEFAULT_MODEL = "small"

# Short model name -> mlx-community HuggingFace repo id.
# Names containing "/" are treated as HF repo ids / local paths and pass through.
_MLX_MODEL_MAP: dict[str, str] = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


@dataclass
class STTResult:
    """Transcription output, dependency-free (commands convert cues -> captions.Cue).

    ``cues`` is a list of plain dicts ``{"start": float, "end": float,
    "text": str}`` so this module never imports ``captions`` (avoids circulars).
    """

    cues: list[dict[str, Any]] = field(default_factory=list)
    language: str = ""
    duration: float = 0.0
    engine: str = ""
    model: str = ""
    elapsed_s: float = 0.0


def mlx_available() -> bool:
    """True when the mlx backend can run: Apple Silicon macOS + mlx_whisper."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401
    except Exception:  # noqa: BLE001 - a broken mlx install must not crash --help/doctor
        return False
    return True


def faster_available() -> bool:
    """True when faster-whisper is importable."""
    try:
        import faster_whisper  # noqa: F401
    except Exception:  # noqa: BLE001 - same rationale as mlx_available
        return False
    return True


def resolve_engine(name: str = "auto") -> str:
    """Resolve an engine selector to a concrete backend name.

    ``"auto"`` picks ``"mlx"`` on Apple Silicon macOS with mlx_whisper
    importable, else ``"faster"``. Explicit ``"mlx"``/``"faster"`` are
    validated and raise :class:`UserError` with an install hint when the
    backend is missing. Unknown names raise :class:`UserError`.
    """
    if name == "auto":
        return "mlx" if mlx_available() else "faster"
    if name == "mlx":
        if mlx_available():
            return "mlx"
        raise UserError(
            "mlx-whisper engine requested but not available.",
            hint="mlx-whisper requires Apple Silicon macOS. Install it with: "
            "pip install 'tiktok-cli[mlx]'  (or use --engine faster).",
        )
    if name == "faster":
        if faster_available():
            return "faster"
        raise UserError(
            "faster-whisper engine requested but not installed.",
            hint="Install it with: pip install 'tiktok-cli'  (faster-whisper is a "
            "core dependency; on Apple Silicon you may prefer --engine mlx).",
        )
    raise UserError(
        f"Unknown engine {name!r}.",
        hint="Choose one of: auto, faster, mlx.",
    )


def get_engine(name: str = "auto", model: str = _DEFAULT_MODEL) -> FasterEngine | MlxEngine:
    """Instantiate the resolved engine (cached model loading happens inside)."""
    backend = resolve_engine(name)
    if backend == "mlx":
        return MlxEngine(model=model)
    return FasterEngine(model=model)


def resolve_mlx_model(model: str) -> str:
    """Map a short model name to an mlx-community HF repo id.

    Names containing ``/`` (HF repo ids, local paths) pass through unchanged.
    Unknown short names fall back to the turbo repo.
    """
    if "/" in model:
        return model
    return _MLX_MODEL_MAP.get(model, _MLX_MODEL_MAP["turbo"])


# faster-whisper model instances are cached module-level, keyed by config —
# model load takes seconds and one run may transcribe many files.
# mlx-whisper caches downloaded repos itself; nothing to cache here.
_FW_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


def _get_fw_model(model: str, device: str, compute_type: str) -> Any:
    """Return a cached faster-whisper WhisperModel, loading if necessary."""
    key = (model, device, compute_type)
    if key not in _FW_MODEL_CACHE:
        from faster_whisper import WhisperModel  # lazy import

        _FW_MODEL_CACHE[key] = WhisperModel(
            model_size_or_path=model,
            device=device,
            compute_type=compute_type,
        )
    return _FW_MODEL_CACHE[key]


def _no_speech_prob(segment: Any) -> float:
    """Extract no_speech_prob from a faster-whisper segment or an mlx dict."""
    prob = (
        segment.get("no_speech_prob")
        if isinstance(segment, dict)
        else getattr(segment, "no_speech_prob", None)
    )
    try:
        return float(prob) if prob is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


class FasterEngine:
    """faster-whisper (CTranslate2) backend."""

    name = "faster"

    def __init__(
        self, model: str = _DEFAULT_MODEL, device: str = "auto", compute_type: str = "auto"
    ) -> None:
        if not faster_available():
            raise UserError(
                "faster-whisper engine requested but not installed.",
                hint="Install it with: pip install 'tiktok-cli'  (faster-whisper is a "
                "core dependency; on Apple Silicon you may prefer --engine mlx).",
            )
        self.model = model
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio_path: Path, language: str | None = None) -> STTResult:
        model = _get_fw_model(self.model, self.device, self.compute_type)
        t0 = time.monotonic()

        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            condition_on_previous_text=False,
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
        )

        cues: list[dict[str, Any]] = []
        for seg in segments_iter:
            if _no_speech_prob(seg) > _NO_SPEECH_THRESHOLD:
                continue
            text = (getattr(seg, "text", "") or "").strip()
            if not text:
                continue
            cues.append(
                {
                    "start": float(getattr(seg, "start", 0.0) or 0.0),
                    "end": float(getattr(seg, "end", 0.0) or 0.0),
                    "text": text,
                }
            )

        elapsed = time.monotonic() - t0
        return STTResult(
            cues=cues,
            language=getattr(info, "language", "") or "",
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            engine=self.name,
            model=self.model,
            elapsed_s=elapsed,
        )


class MlxEngine:
    """mlx-whisper backend (Apple Silicon macOS only)."""

    name = "mlx"

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        if not mlx_available():
            raise UserError(
                "mlx-whisper engine requested but not available.",
                hint="mlx-whisper requires Apple Silicon macOS. Install it with: "
                "pip install 'tiktok-cli[mlx]'  (or use --engine faster).",
            )
        self.model = model
        self.repo = resolve_mlx_model(model)

    def transcribe(self, audio_path: Path, language: str | None = None) -> STTResult:
        import mlx_whisper  # lazy import; availability checked in __init__

        t0 = time.monotonic()
        result: dict[str, Any] = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=self.repo,
            language=language,
            condition_on_previous_text=False,
            temperature=0.0,
            word_timestamps=False,
            verbose=False,
        )
        elapsed = time.monotonic() - t0

        cues: list[dict[str, Any]] = []
        max_end = 0.0
        for seg in result.get("segments") or []:
            if _no_speech_prob(seg) > _NO_SPEECH_THRESHOLD:
                continue
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or start)
            max_end = max(max_end, end)
            cues.append({"start": start, "end": end, "text": text})

        info = result.get("info") or {}
        duration = float(info.get("duration") or max_end or 0.0)
        language_out = result.get("language") or info.get("language") or language or ""
        return STTResult(
            cues=cues,
            language=str(language_out),
            duration=duration,
            engine=self.name,
            model=self.model,
            elapsed_s=elapsed,
        )


def transcribe_media(
    audio_path: Path,
    model: str = _DEFAULT_MODEL,
    language: str | None = None,
    engine: str = "auto",
) -> STTResult:
    """Top-level convenience: resolve the engine and transcribe one file."""
    eng = get_engine(engine, model=model)
    return eng.transcribe(Path(audio_path), language=language)
