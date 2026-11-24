"""Unit tests for tiktok_cli.core.stt — no real models, no network.

Heavy backends are faked by injecting ModuleType stubs into sys.modules
BEFORE the availability helpers / engines try to import them. stt.py keeps
all heavy imports lazy, so importing the module itself is always safe.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from tiktok_cli.core import stt
from tiktok_cli.core.stt import (
    FasterEngine,
    MlxEngine,
    STTResult,
    faster_available,
    get_engine,
    mlx_available,
    resolve_engine,
    resolve_mlx_model,
    transcribe_media,
)

# ---------------------------------------------------------------------------
# Fake backends
# ---------------------------------------------------------------------------


class _FakeSegment:
    """Mimics a faster-whisper segment object (attribute access)."""

    def __init__(self, text, start, end, no_speech_prob=0.0):
        self.text = text
        self.start = start
        self.end = end
        self.no_speech_prob = no_speech_prob


class _FakeFWModel:
    """Mimics faster_whisper.WhisperModel."""

    instances: ClassVar[list[_FakeFWModel]] = []

    def __init__(self, model_size_or_path, device="auto", compute_type="auto"):
        self.model_size_or_path = model_size_or_path
        self.device = device
        self.compute_type = compute_type
        self.calls: list[dict] = []
        _FakeFWModel.instances.append(self)

    def transcribe(self, audio_path, **kwargs):
        self.calls.append({"audio_path": audio_path, **kwargs})
        segments = iter(
            [
                _FakeSegment("  hello world  ", 0.0, 1.5),
                _FakeSegment("noise", 1.5, 2.0, no_speech_prob=0.9),  # dropped
                _FakeSegment("", 2.0, 2.5),  # empty text dropped
                _FakeSegment("second cue", 2.5, 4.0),
            ]
        )
        info = SimpleNamespace(language="en", duration=4.0)
        return segments, info


def _install_faster(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _FakeFWModel
    _FakeFWModel.instances.clear()
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    stt._FW_MODEL_CACHE.clear()


def _install_mlx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_transcribe(audio_path, **kwargs):
        calls.append({"audio_path": audio_path, **kwargs})
        return {
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": " hi there ", "no_speech_prob": 0.1},
                {"start": 1.0, "end": 1.5, "text": "hallucination", "no_speech_prob": 0.95},
                {"start": 1.5, "end": 3.0, "text": "  ", "no_speech_prob": 0.0},
                {"start": 1.5, "end": 3.0, "text": "bye", "no_speech_prob": 0.0},
            ],
            "info": {"duration": 3.0, "language": "en"},
        }

    mod = types.ModuleType("mlx_whisper")
    mod.transcribe = fake_transcribe
    mod._test_calls = calls
    monkeypatch.setitem(sys.modules, "mlx_whisper", mod)


def _block_faster(monkeypatch: pytest.MonkeyPatch) -> None:
    # sys.modules[name] = None makes `import faster_whisper` raise ImportError.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    stt._FW_MODEL_CACHE.clear()


def _block_mlx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)


def _set_platform(monkeypatch: pytest.MonkeyPatch, sys_platform: str, machine: str) -> None:
    monkeypatch.setattr(sys, "platform", sys_platform)
    monkeypatch.setattr(stt.platform, "machine", lambda: machine)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch):
    stt._FW_MODEL_CACHE.clear()
    _block_faster(monkeypatch)
    _block_mlx(monkeypatch)
    yield
    stt._FW_MODEL_CACHE.clear()


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_faster_available_false_when_missing(self):
        assert faster_available() is False

    def test_faster_available_true_when_present(self, monkeypatch):
        _install_faster(monkeypatch)
        assert faster_available() is True

    def test_mlx_available_false_off_darwin(self, monkeypatch):
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "linux", "x86_64")
        assert mlx_available() is False

    def test_mlx_available_false_on_intel_mac(self, monkeypatch):
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "x86_64")
        assert mlx_available() is False

    def test_mlx_available_true_on_apple_silicon(self, monkeypatch):
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")
        assert mlx_available() is True

    def test_mlx_available_false_when_not_importable(self, monkeypatch):
        _set_platform(monkeypatch, "darwin", "arm64")
        assert mlx_available() is False


# ---------------------------------------------------------------------------
# resolve_engine
# ---------------------------------------------------------------------------


class TestResolveEngine:
    def test_auto_picks_faster_on_linux(self, monkeypatch):
        _install_faster(monkeypatch)
        _set_platform(monkeypatch, "linux", "x86_64")
        assert resolve_engine("auto") == "faster"

    def test_auto_picks_mlx_on_apple_silicon(self, monkeypatch):
        _install_faster(monkeypatch)
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")
        assert resolve_engine("auto") == "mlx"

    def test_auto_falls_back_to_faster_without_mlx(self, monkeypatch):
        _install_faster(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")  # mlx blocked by fixture
        assert resolve_engine("auto") == "faster"

    def test_auto_faster_when_neither_available(self):
        # faster missing too -> 'auto' still returns 'faster'; the error
        # surfaces when the engine is instantiated / transcribe runs.
        assert resolve_engine("auto") == "faster"

    def test_explicit_faster_ok(self, monkeypatch):
        _install_faster(monkeypatch)
        assert resolve_engine("faster") == "faster"

    def test_explicit_faster_missing_raises(self):
        with pytest.raises(stt.UserError, match="faster-whisper"):
            resolve_engine("faster")

    def test_explicit_mlx_ok(self, monkeypatch):
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")
        assert resolve_engine("mlx") == "mlx"

    def test_explicit_mlx_unavailable_raises(self):
        with pytest.raises(stt.UserError, match="mlx-whisper"):
            resolve_engine("mlx")

    def test_unknown_engine_raises(self):
        with pytest.raises(stt.UserError, match="Unknown engine"):
            resolve_engine("whisper.cpp")


# ---------------------------------------------------------------------------
# Model name mapping
# ---------------------------------------------------------------------------


class TestModelMapping:
    @pytest.mark.parametrize(
        ("short", "repo"),
        [
            ("tiny", "mlx-community/whisper-tiny-mlx"),
            ("base", "mlx-community/whisper-base-mlx"),
            ("small", "mlx-community/whisper-small-mlx"),
            ("medium", "mlx-community/whisper-medium-mlx"),
            ("large-v3", "mlx-community/whisper-large-v3-mlx"),
            ("turbo", "mlx-community/whisper-large-v3-turbo"),
            ("large-v3-turbo", "mlx-community/whisper-large-v3-turbo"),
        ],
    )
    def test_mlx_map(self, short, repo):
        assert resolve_mlx_model(short) == repo

    def test_mlx_passthrough_hf_repo(self):
        assert resolve_mlx_model("mlx-community/whisper-small-mlx") == (
            "mlx-community/whisper-small-mlx"
        )

    def test_mlx_passthrough_local_path(self):
        assert resolve_mlx_model("/models/whisper-custom") == "/models/whisper-custom"

    def test_mlx_unknown_falls_back_to_turbo(self):
        assert resolve_mlx_model("not-a-model") == ("mlx-community/whisper-large-v3-turbo")

    def test_faster_model_name_passed_as_is(self, monkeypatch):
        _install_faster(monkeypatch)
        eng = FasterEngine(model="distil-large-v3")
        eng.transcribe(Path("a.mp3"), language="en")
        assert _FakeFWModel.instances[-1].model_size_or_path == "distil-large-v3"

    def test_faster_default_model_is_small(self, monkeypatch):
        _install_faster(monkeypatch)
        FasterEngine().transcribe(Path("a.mp3"))
        assert _FakeFWModel.instances[-1].model_size_or_path == "small"


# ---------------------------------------------------------------------------
# Engine transcribe -> STTResult
# ---------------------------------------------------------------------------


class TestSTTResult:
    def test_shape_and_fields(self):
        r = STTResult()
        assert r.cues == []
        assert r.language == ""
        assert r.duration == 0.0
        assert r.engine == ""
        assert r.model == ""
        assert r.elapsed_s == 0.0

    def test_cue_dict_keys(self):
        r = STTResult(cues=[{"start": 0.0, "end": 1.0, "text": "hi"}])
        assert set(r.cues[0]) == {"start", "end", "text"}


class TestFasterEngineTranscribe:
    def test_result_shape_and_filters(self, monkeypatch):
        _install_faster(monkeypatch)
        eng = FasterEngine(model="small")
        result = eng.transcribe(Path("clip.mp3"), language="en")

        assert isinstance(result, STTResult)
        assert result.engine == "faster"
        assert result.model == "small"
        assert result.language == "en"
        assert result.duration == 4.0
        assert result.elapsed_s >= 0.0

        # no_speech_prob>0.6 and empty-text segments are dropped.
        assert result.cues == [
            {"start": 0.0, "end": 1.5, "text": "hello world"},
            {"start": 2.5, "end": 4.0, "text": "second cue"},
        ]

    def test_anti_hallucination_kwargs(self, monkeypatch):
        _install_faster(monkeypatch)
        eng = FasterEngine(model="small")
        eng.transcribe(Path("clip.mp3"), language="vi")
        call = _FakeFWModel.instances[-1].calls[-1]
        assert call["language"] == "vi"
        assert call["condition_on_previous_text"] is False
        assert call["beam_size"] == 1
        assert call["temperature"] == 0.0
        assert call["vad_filter"] is True

    def test_model_cached_by_config(self, monkeypatch):
        _install_faster(monkeypatch)
        FasterEngine(model="small").transcribe(Path("a.mp3"))
        FasterEngine(model="small").transcribe(Path("b.mp3"))
        FasterEngine(model="medium").transcribe(Path("c.mp3"))
        # small loaded once despite two transcribes; medium is a second load.
        assert [i.model_size_or_path for i in _FakeFWModel.instances] == ["small", "medium"]

    def test_missing_backend_raises(self):
        with pytest.raises(stt.UserError):
            FasterEngine()


class TestMlxEngineTranscribe:
    def test_result_shape_and_filters(self, monkeypatch):
        _install_faster(monkeypatch)
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")

        eng = MlxEngine(model="small")
        assert eng.repo == "mlx-community/whisper-small-mlx"
        result = eng.transcribe(Path("clip.m4a"), language="en")

        assert result.engine == "mlx"
        assert result.model == "small"
        assert result.language == "en"
        assert result.duration == 3.0
        assert result.elapsed_s >= 0.0
        # no_speech_prob>0.6 and blank text dropped.
        assert result.cues == [
            {"start": 0.0, "end": 1.0, "text": "hi there"},
            {"start": 1.5, "end": 3.0, "text": "bye"},
        ]

    def test_mlx_kwargs(self, monkeypatch):
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")
        eng = MlxEngine(model="turbo")
        eng.transcribe(Path("clip.m4a"), language="vi")
        call = sys.modules["mlx_whisper"]._test_calls[-1]
        assert call["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
        assert call["language"] == "vi"
        assert call["condition_on_previous_text"] is False
        assert call["temperature"] == 0.0
        assert call["verbose"] is False

    def test_mlx_unavailable_raises(self):
        with pytest.raises(stt.UserError):
            MlxEngine()


# ---------------------------------------------------------------------------
# get_engine / transcribe_media
# ---------------------------------------------------------------------------


class TestConvenience:
    def test_get_engine_returns_faster(self, monkeypatch):
        _install_faster(monkeypatch)
        _set_platform(monkeypatch, "linux", "x86_64")
        eng = get_engine("auto", model="base")
        assert isinstance(eng, FasterEngine)
        assert eng.model == "base"

    def test_get_engine_returns_mlx(self, monkeypatch):
        _install_mlx(monkeypatch)
        _set_platform(monkeypatch, "darwin", "arm64")
        eng = get_engine("auto")
        assert isinstance(eng, MlxEngine)

    def test_get_engine_forced_missing_raises(self):
        with pytest.raises(stt.UserError):
            get_engine("faster")  # faster blocked by fixture

    def test_transcribe_media_end_to_end(self, monkeypatch, tmp_path):
        _install_faster(monkeypatch)
        _set_platform(monkeypatch, "linux", "x86_64")
        audio = tmp_path / "clip.mp3"
        audio.write_bytes(b"fake")
        result = transcribe_media(audio, model="small", language="en", engine="auto")
        assert isinstance(result, STTResult)
        assert result.engine == "faster"
        assert len(result.cues) == 2
