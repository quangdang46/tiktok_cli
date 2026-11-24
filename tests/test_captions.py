"""Unit tests for tiktok_cli.core.captions — pure, no network/models."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from tiktok_cli.core import captions
from tiktok_cli.core.captions import Cue

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_VTT = FIXTURES / "sample.vtt"
EXPECTED_CUES = FIXTURES / "expected_cues.json"

META = {
    "title": "POV: your code works on the first try",
    "uploader": "dev.daily",
    "duration": 14,
    "language": "en",
    "webpage_url": "https://www.tiktok.com/@dev.daily/video/7350000000000000000",
}


def sample_cues() -> list[Cue]:
    return captions.parse_vtt(SAMPLE_VTT)


# --- parse_vtt ---------------------------------------------------------------


def test_parse_vtt_golden():
    """parse_vtt(sample.vtt) must equal the golden expected_cues.json."""
    expected = json.loads(EXPECTED_CUES.read_text(encoding="utf-8"))
    assert [asdict(c) for c in sample_cues()] == expected


def test_parse_vtt_strips_markup_and_dedupes():
    cues = sample_cues()
    texts = [c.text for c in cues]
    # <c>, karaoke <00:...>, {\an8}, entities all removed; consecutive
    # duplicate "duplicate text" cues collapsed to one.
    assert texts == [
        "hello world",
        "this is a test of the system",
        "duplicate text",
        "gap & entities <here> & there",
    ]
    # The dropped duplicate cue's timing is gone entirely.
    assert not any(c.start == 7.0 for c in cues)


def test_parse_vtt_timing_fields():
    cue = sample_cues()[0]
    assert cue.start == 0.0 and cue.end == 2.0
    assert cue.start_time == "00:00:00.000"
    assert cue.end_time == "00:00:02.000"


def test_strip_vtt_markup_edge_cases():
    assert captions.strip_vtt_markup("a <00:00:01.500>b <c>c</c> {\\an8}d") == "a b c d"
    assert captions.strip_vtt_markup("x &amp; y &lt;3") == "x & y <3"
    assert captions.strip_vtt_markup("multi   \n   space") == "multi space"


def test_parse_time_and_format_time():
    assert captions.parse_time("00:01:02.500") == 62.5
    assert captions.parse_time("01:02.500") == 62.5
    assert captions.parse_time("62.5") == 62.5
    assert captions.format_time(62.5) == "00:01:02.500"
    assert captions.format_time(3661.25) == "01:01:01.250"


# --- pick_caption_file --------------------------------------------------------


def test_pick_caption_prefers_manual_over_auto(tmp_path):
    auto = tmp_path / "12345.en.auto.vtt"
    manual = tmp_path / "12345.en.vtt"
    auto.write_text("WEBVTT\n")
    manual.write_text("WEBVTT\n")
    assert captions.pick_caption_file([auto, manual]) == manual


def test_pick_caption_language_preference(tmp_path):
    en = tmp_path / "12345.en.vtt"
    vie = tmp_path / "12345.vie.vtt"
    other = tmp_path / "12345.fr.vtt"
    for p in (en, vie, other):
        p.write_text("WEBVTT\n")
    # Default preference: vie > vi > en > en-US.
    assert captions.pick_caption_file([en, other, vie]) == vie
    # Custom preference flips the order.
    assert captions.pick_caption_file([en, vie], preference=("en", "vie")) == en
    # No preference match -> first sorted name.
    assert captions.pick_caption_file([other]) == other


def test_pick_caption_empty():
    assert captions.pick_caption_file([]) is None


# --- cues_to_paragraphs -------------------------------------------------------


def test_cues_to_paragraphs_breaks_on_gap():
    cues = [
        Cue(0.0, 1.0, "00:00:00.000", "00:00:01.000", "one"),
        Cue(1.0, 2.0, "00:00:01.000", "00:00:02.000", "two"),
        Cue(5.0, 6.0, "00:00:05.000", "00:00:06.000", "three"),  # 3s gap
    ]
    assert captions.cues_to_paragraphs(cues, gap_threshold=2.0) == ["one two", "three"]


def test_cues_to_paragraphs_single_flow():
    cues = sample_cues()
    paragraphs = captions.cues_to_paragraphs(cues)
    # cue at 12s is >2s after cue ending at 7s -> new paragraph.
    assert len(paragraphs) == 2
    assert paragraphs[0] == "hello world this is a test of the system duplicate text"
    assert paragraphs[1] == "gap & entities <here> & there"


# --- renderers ----------------------------------------------------------------


def _assert_single_trailing_newline(text: str):
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_render_txt_plain():
    out = captions.render_txt(sample_cues())
    _assert_single_trailing_newline(out)
    assert "\n\n" in out  # paragraph break
    assert "00:00:00" not in out


def test_render_txt_timestamps():
    out = captions.render_txt(sample_cues(), timestamps=True)
    _assert_single_trailing_newline(out)
    lines = out.strip().split("\n")
    assert lines[0].startswith("[00:00]")
    assert "hello world" in lines[0]


def test_render_srt_shape():
    out = captions.render_srt(sample_cues())
    _assert_single_trailing_newline(out)
    blocks = out.strip().split("\n\n")
    assert len(blocks) == 4
    assert blocks[0].split("\n")[0] == "1"
    assert "00:00:00,000 --> 00:00:02,000" in blocks[0]


def test_render_vtt_shape():
    out = captions.render_vtt(sample_cues())
    _assert_single_trailing_newline(out)
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:02.000" in out


def test_render_json_shape():
    out = captions.render_json(sample_cues(), META)
    _assert_single_trailing_newline(out)
    data = json.loads(out)
    assert set(data) == {"source", "language", "duration", "segments"}
    assert data["language"] == "en"
    assert data["duration"] == 14
    assert data["source"]["title"] == META["title"]
    assert len(data["segments"]) == 4
    assert data["segments"][0] == {"start": 0.0, "end": 2.0, "text": "hello world"}


def test_render_md_shape():
    out = captions.render_md(sample_cues(), META)
    _assert_single_trailing_newline(out)
    assert out.startswith("# POV: your code works on the first try\n")
    assert "- Creator: dev.daily" in out
    assert "## Transcript" in out
    assert "[00:00:00.000 -> 00:00:02.000] hello world" in out


def test_render_all_dispatch():
    for fmt in ("txt", "srt", "vtt", "json", "md"):
        out = captions.render_all(sample_cues(), META, fmt)
        assert isinstance(out, str)
        _assert_single_trailing_newline(out)
    everything = captions.render_all(sample_cues(), META, "all")
    assert isinstance(everything, dict)
    assert set(everything) == {"txt", "srt", "vtt", "json", "md"}
    with pytest.raises(ValueError):
        captions.render_all(sample_cues(), META, "bogus")
