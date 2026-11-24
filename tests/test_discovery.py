"""Unit tests for core/discovery.py — tt binary is fully mocked."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from tiktok_cli.core import discovery
from tiktok_cli.core.errors import UserError


def _proc(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["tt"], returncode=rc, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _tt_on_path():
    with patch.object(discovery.shutil, "which", return_value="/usr/bin/tt"):
        yield


class TestRunTt:
    def test_jsonl_parsing(self):
        out = '{"a": 1}\n{"b": 2}\n\n{"c": 3}\n'
        with patch.object(discovery.subprocess, "run", return_value=_proc(out)) as run:
            records = discovery.run_tt(["search", "cats"])
        assert records == [{"a": 1}, {"b": 2}, {"c": 3}]
        cmd = run.call_args.args[0]
        assert cmd[:2] == ["tt", "search"]
        assert "--output" in cmd and "jsonl" in cmd

    def test_json_array_parsing(self):
        out = json.dumps([{"a": 1}, {"b": 2}])
        with patch.object(discovery.subprocess, "run", return_value=_proc(out)):
            assert discovery.run_tt(["trending"]) == [{"a": 1}, {"b": 2}]

    def test_json_object_wrapped(self):
        with patch.object(discovery.subprocess, "run", return_value=_proc('{"x": 9}')):
            assert discovery.run_tt(["video", "u"]) == [{"x": 9}]

    def test_nonzero_exit_raises_usererror(self):
        with (
            patch.object(discovery.subprocess, "run", return_value=_proc("", "boom\n", rc=1)),
            pytest.raises(UserError, match="boom"),
        ):
            discovery.run_tt(["video", "u"])

    def test_empty_output_raises(self):
        with (
            patch.object(discovery.subprocess, "run", return_value=_proc("")),
            pytest.raises(UserError, match="no records"),
        ):
            discovery.run_tt(["trending"])

    def test_waf_detection_on_failure(self):
        with (
            patch.object(
                discovery.subprocess,
                "run",
                return_value=_proc("", "TikTok served a challenge page", rc=1),
            ),
            pytest.raises(UserError, match="WAF challenge") as ei,
        ):
            discovery.run_tt(["search", "x"])
        assert "SSR plane" in (ei.value.hint or "")

    def test_missing_tt(self):
        with (
            patch.object(discovery.shutil, "which", return_value=None),
            pytest.raises(UserError, match="tt not installed"),
        ):
            discovery.search("x")

    def test_timeout(self):
        with (
            patch.object(
                discovery.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="tt", timeout=120),
            ),
            pytest.raises(UserError, match="timed out"),
        ):
            discovery.run_tt(["video", "u"])


class TestHelpers:
    def _run(self, records=None):
        return patch.object(
            discovery.subprocess,
            "run",
            return_value=_proc("".join(json.dumps(r) + "\n" for r in (records or [{}]))),
        )

    def test_video_info(self):
        with self._run([{"id": "1"}]) as run:
            assert discovery.video_info("https://tiktok.com/@u/video/1") == {"id": "1"}
        assert run.call_args.args[0][:2] == ["tt", "video"]

    def test_search_limit_flag(self):
        with self._run() as run:
            discovery.search("hello world", limit=7)
        cmd = run.call_args.args[0]
        assert cmd == [
            "tt",
            "search",
            "hello world",
            "-n",
            "7",
            "--output",
            "jsonl",
            "--quiet",
        ]

    def test_user_posts_normalizes_handle(self):
        for ref in ["@cool.user", "cool.user", "https://www.tiktok.com/@cool.user"]:
            with self._run() as run:
                discovery.user_posts(ref)
            assert run.call_args.args[0][2] == "cool.user"

    def test_hashtag_strips_hash_and_url(self):
        with self._run() as run:
            discovery.hashtag_videos("#fyp")
        assert run.call_args.args[0][:4] == ["tt", "hashtag", "fyp", "--videos"]
        with self._run() as run:
            discovery.hashtag_videos("https://www.tiktok.com/tag/fyp")
        assert run.call_args.args[0][2] == "fyp"

    def test_trending(self):
        with self._run() as run:
            discovery.trending(limit=5)
        assert run.call_args.args[0] == [
            "tt",
            "trending",
            "-n",
            "5",
            "--output",
            "jsonl",
            "--quiet",
        ]


class TestDiscover:
    def _argv(self, seeds, **kw):
        with patch.object(discovery.subprocess, "run", return_value=_proc("{}\n")) as run:
            discovery.discover(seeds, **kw)
        return run.call_args.args[0]

    def test_seed_mapping(self):
        argv = self._argv(
            [
                ("video", "https://tiktok.com/@u/video/123"),
                ("hashtag", "#fyp"),
                ("user", "@cool.user"),
                ("search", "cats"),
                ("trending", ""),
            ],
            top=10,
            depth=3,
            max_nodes=50,
        )
        assert argv[1] == "discover"
        for frag in (
            ["--seed-video", "https://tiktok.com/@u/video/123"],
            ["--seed-tag", "fyp"],
            ["--seed", "cool.user"],
            ["--seed-search", "cats"],
            "--trending",
            ["--depth", "3"],
            ["--top", "10"],
            ["--max-nodes", "50"],
        ):
            if isinstance(frag, str):
                assert frag in argv
            else:
                i = argv.index(frag[0])
                assert argv[i : i + 2] == frag
        # no bogus flags from the bead's stale spec
        assert "--seed-hashtag" not in argv and "--seed-user" not in argv

    def test_unknown_kind_raises(self):
        with pytest.raises(UserError, match="unknown discover seed kind"):
            self._argv([("bogus", "x")])

    def test_empty_value_raises(self):
        with pytest.raises(UserError, match="needs a value"):
            self._argv([("video", "  ")])
