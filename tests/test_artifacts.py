"""Tests for tiktok_cli.core.artifacts — no network, no models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tiktok_cli.core.artifacts import (
    VideoDir,
    append_index,
    compact_metadata,
    read_index,
    sanitize_video_id,
)
from tiktok_cli.core.errors import UserError


def test_sanitize_video_id_accepts_valid_ids():
    assert sanitize_video_id("7312345678901234567") == "7312345678901234567"
    assert sanitize_video_id("abc_DEF-123") == "abc_DEF-123"
    # exactly 6 chars is the minimum
    assert sanitize_video_id("abcdef") == "abcdef"


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "abc",  # too short (<6)
        "has space1",  # space
        "slash/id1",  # path separator
        "dot.name",  # dot
        "../evil1",  # traversal
        "uni-é-1234",  # non-ascii
    ],
)
def test_sanitize_video_id_rejects_invalid_ids(bad):
    with pytest.raises(UserError):
        sanitize_video_id(bad)


def test_video_dir_paths(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    assert vd.path == tmp_path / "7312345678901234567"
    assert vd.subs_dir == vd.path / "subs"


def test_is_processed(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    assert not vd.is_processed()
    vd.ensure()
    assert not vd.is_processed()  # dir alone isn't enough
    vd.transcript_path("json").write_text("[]", encoding="utf-8")
    assert vd.is_processed()


def test_ensure_creates_subs_dir(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    vd.ensure()
    assert vd.path.is_dir()
    assert vd.subs_dir.is_dir()


def test_write_transcripts_creates_files(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    rendered = {
        "txt": "hello world",
        "srt": "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        "vtt": "WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n",
        "json": '[{"start": 0, "end": 1, "text": "hello"}]',
        "md": "# Title\n\n[00:00] hello",
    }
    written = vd.write_transcripts(rendered)
    assert set(written) == {"txt", "srt", "vtt", "json", "md"}
    for fmt, path in written.items():
        assert path.parent == vd.path
        assert path.name == f"transcript.{fmt}"
        assert path.read_text(encoding="utf-8") == rendered[fmt]
    assert vd.is_processed()


def test_write_transcripts_unknown_format(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    with pytest.raises(ValueError):
        vd.transcript_path("ass")
    with pytest.raises(ValueError):
        vd.write_transcripts({"ass": "x"})


def test_write_source_info_once(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    vd.write_source_info({"id": "7312345678901234567", "title": "v1"})
    vd.write_source_info({"id": "7312345678901234567", "title": "v2"})
    data = json.loads(vd.source_info_path().read_text(encoding="utf-8"))
    assert data["title"] == "v1"  # second write skipped

    vd.write_source_info({"id": "7312345678901234567", "title": "v3"}, refresh=True)
    data = json.loads(vd.source_info_path().read_text(encoding="utf-8"))
    assert data["title"] == "v3"


def test_write_metadata(tmp_path: Path):
    vd = VideoDir(tmp_path, "7312345678901234567")
    compact = compact_metadata(
        {"id": "7312345678901234567", "title": "hi"}, "caption", 3, language="vie"
    )
    vd.write_metadata(compact)
    data = json.loads(vd.metadata_path().read_text(encoding="utf-8"))
    assert data["title"] == "hi"
    assert data["transcript_source"] == "caption"
    assert data["cue_count"] == 3
    assert data["language"] == "vie"
    assert "processed_at" in data


def test_append_index_appends_valid_jsonl(tmp_path: Path):
    append_index(tmp_path, {"video_id": "7312345678901234567", "status": "caption"})
    append_index(tmp_path, {"video_id": "7312345678901234568", "status": "failed"})

    index_path = tmp_path / "index.jsonl"
    lines = index_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["video_id"] == "7312345678901234567"
    assert records[0]["status"] == "caption"
    assert records[0]["processed_at"]  # added automatically
    assert records[1]["status"] == "failed"


def test_append_index_respects_existing_processed_at(tmp_path: Path):
    append_index(
        tmp_path, {"video_id": "7312345678901234567", "processed_at": "2020-01-01T00:00:00+00:00"}
    )
    record = next(read_index(tmp_path))
    assert record["processed_at"] == "2020-01-01T00:00:00+00:00"


def test_read_index_empty_and_missing(tmp_path: Path):
    assert list(read_index(tmp_path)) == []  # no index.jsonl yet
    append_index(tmp_path, {"video_id": "7312345678901234567", "status": "caption"})
    assert len(list(read_index(tmp_path))) == 1


def test_compact_metadata_date_conversion():
    meta = compact_metadata(
        {
            "id": "7312345678901234567",
            "title": "Some video",
            "uploader": "creator",
            "uploader_id": "creator",
            "duration": 12.5,
            "upload_date": "20241124",
            "webpage_url": "https://www.tiktok.com/@creator/video/7312345678901234567",
            "view_count": 1000,
            "like_count": 50,
            "comment_count": 7,
        },
        "whisper",
        42,
        language="eng",
    )
    assert meta["upload_date"] == "2024-11-24"
    assert meta["id"] == "7312345678901234567"
    assert meta["title"] == "Some video"
    assert meta["uploader"] == "creator"
    assert meta["duration"] == 12.5
    assert meta["view_count"] == 1000
    assert meta["transcript_source"] == "whisper"
    assert meta["cue_count"] == 42
    assert meta["language"] == "eng"
    assert meta["processed_at"].endswith("+00:00")


def test_compact_metadata_missing_fields():
    meta = compact_metadata({}, "caption", 0)
    assert meta["upload_date"] is None
    assert meta["language"] is None
    assert meta["transcript_source"] == "caption"
    assert meta["cue_count"] == 0
