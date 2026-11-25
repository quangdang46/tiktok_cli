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


class TestNormalizers:
    """SSR itemStruct and yt-dlp info/entry -> flat record."""

    def test_record_from_item_struct(self):
        item = {
            "id": "7106594312292453675",
            "desc": "frog video",
            "createTime": 1654632929,
            "author": {"id": "107955", "uniqueId": "tiktok"},
            "statsV2": {
                "diggCount": "98900",
                "shareCount": "362",
                "commentCount": "1279",
                "playCount": "597300",
                "collectCount": "59224",
                "repostCount": "0",
            },
            "music": {"title": "original sound", "author": "TikTok"},
            "challenges": [{"title": "Minecraft"}, {"noTitle": True}, "junk"],
            "video": {"duration": 24},
        }
        rec = discovery._record_from_item_struct(item)
        assert rec["id"] == "7106594312292453675"
        assert rec["desc"] == "frog video"
        assert rec["author"] == "tiktok"
        assert rec["play_count"] == 597300
        assert rec["digg_count"] == 98900
        assert rec["comment_count"] == 1279
        assert rec["share_count"] == 362
        assert rec["favorite_count"] == 59224
        assert rec["create_time"] == 1654632929
        assert rec["duration"] == 24
        assert rec["music_title"] == "original sound"
        assert rec["music_author"] == "TikTok"
        assert rec["challenges"] == ["Minecraft"]
        assert rec["url"] == "https://www.tiktok.com/@tiktok/video/7106594312292453675"
        assert rec["source"] == "tiktok-page"

    def test_record_from_ytdlp_full_info(self):
        info = {
            "id": "123",
            "title": "a title",
            "description": "a description",
            "uploader": "dev.daily",
            "uploader_id": "107955",
            "view_count": 1000,
            "like_count": 50,
            "comment_count": 7,
            "repost_count": 3,
            "save_count": 9,
            "timestamp": 1700000000,
            "duration": 15,
            "track": "original sound",
            "artists": ["TikTok"],
            "tags": ["fyp"],
            "webpage_url": "https://www.tiktok.com/@dev.daily/video/123",
        }
        rec = discovery._record_from_ytdlp(info)
        assert rec["id"] == "123"
        assert rec["desc"] == "a description"
        assert rec["author"] == "dev.daily"
        assert rec["play_count"] == 1000
        assert rec["digg_count"] == 50
        assert rec["comment_count"] == 7
        assert rec["share_count"] == 3
        assert rec["favorite_count"] == 9
        assert rec["music_title"] == "original sound"
        assert rec["music_author"] == "TikTok"
        assert rec["challenges"] == ["fyp"]
        assert rec["url"] == "https://www.tiktok.com/@dev.daily/video/123"
        assert rec["source"] == "yt-dlp"

    def test_record_from_ytdlp_flat_entry_builds_url(self):
        entry = {
            "id": "555",
            "title": "flat entry",
            "uploader": "dev.daily",
            "view_count": 10,
            "url": None,
            "webpage_url": None,
        }
        rec = discovery._record_from_ytdlp(entry)
        assert rec["url"] == "https://www.tiktok.com/@dev.daily/video/555"
        assert rec["desc"] == "flat entry"


class TestVideoInfo:
    _URL = "https://www.tiktok.com/@u/video/1"

    def test_ssr_item_struct_wins(self):
        item = {"id": "1", "desc": "d", "author": {"uniqueId": "u"}}
        with (
            patch.object(discovery.post_page, "fetch_item_struct", return_value=item),
            patch.object(discovery.YtdlpClient, "extract_info") as ytdlp,
        ):
            rec = discovery.video_info(self._URL)
        assert rec["source"] == "tiktok-page"
        assert rec["id"] == "1"
        ytdlp.assert_not_called()

    def test_ytdlp_fallback_when_ssr_empty(self):
        info = {"id": "1", "title": "t", "uploader": "u"}
        with (
            patch.object(discovery.post_page, "fetch_item_struct", return_value=None),
            patch.object(discovery.YtdlpClient, "extract_info", return_value=info) as ytdlp,
        ):
            rec = discovery.video_info(self._URL)
        assert rec["source"] == "yt-dlp"
        assert rec["id"] == "1"
        ytdlp.assert_called_once_with(self._URL)

    def test_non_post_url_skips_ssr(self):
        info = {"id": "1", "title": "t"}
        with (
            patch.object(discovery.post_page, "fetch_item_struct") as ssr,
            patch.object(discovery.YtdlpClient, "extract_info", return_value=info),
        ):
            discovery.video_info("not a url at all")
        ssr.assert_not_called()

    def test_bare_id_resolves_via_placeholder_author(self):
        item = {"id": "7106594312292453675", "desc": "d"}
        with (
            patch.object(discovery.post_page, "fetch_item_struct", return_value=item) as ssr,
            patch.object(discovery.YtdlpClient, "extract_info") as ytdlp,
        ):
            rec = discovery.video_info("7106594312292453675")
        ssr.assert_called_once_with("https://www.tiktok.com/@_/video/7106594312292453675")
        assert rec["id"] == "7106594312292453675"
        ytdlp.assert_not_called()

    def test_photo_url_rewritten_for_ssr(self):
        item = {"id": "9", "desc": "p"}
        with (
            patch.object(discovery.post_page, "fetch_item_struct", return_value=item) as ssr,
            patch.object(discovery.YtdlpClient, "extract_info") as ytdlp,
        ):
            discovery.video_info("https://www.tiktok.com/@u/photo/9")
        ssr.assert_called_once_with("https://www.tiktok.com/@u/video/9")
        ytdlp.assert_not_called()

    def test_empty_ytdlp_raises(self):
        with (
            patch.object(discovery.post_page, "fetch_item_struct", return_value=None),
            patch.object(discovery.YtdlpClient, "extract_info", return_value={}),
            pytest.raises(UserError, match="no video metadata"),
        ):
            discovery.video_info(self._URL)


class TestUserPosts:
    def test_flattens_entries(self):
        entries = [
            {"id": "1", "title": "a", "uploader": "u", "view_count": 5},
            {"id": "2", "title": "b", "uploader": "u", "view_count": 6},
            "junk",
        ]
        client = patch.object(
            discovery.YtdlpClient,
            "extract_flat",
            return_value={"entries": entries},
        )
        with client as flat:
            records = discovery.user_posts("@cool.user", limit=7)
        flat.assert_called_once_with("https://www.tiktok.com/@cool.user", limit=7)
        assert [r["id"] for r in records] == ["1", "2"]
        assert records[0]["author"] == "u"
        assert records[0]["play_count"] == 5

    def test_normalizes_handle_forms(self):
        for ref in ["@cool.user", "cool.user", "https://www.tiktok.com/@cool.user"]:
            with patch.object(
                discovery.YtdlpClient, "extract_flat", return_value={"entries": []}
            ) as flat:
                discovery.user_posts(ref)
            assert flat.call_args.args[0] == "https://www.tiktok.com/@cool.user"

    def test_invalid_handle_raises(self):
        with (
            patch.object(discovery.YtdlpClient, "extract_flat") as flat,
            pytest.raises(UserError, match="invalid TikTok handle"),
        ):
            discovery.user_posts("not a handle!!")
        flat.assert_not_called()


class TestTtBackedHelpers:
    """search/hashtag/trending/discover still shell out to `tt` (suspended cmds)."""

    def _run(self, records=None):
        return patch.object(
            discovery.subprocess,
            "run",
            return_value=_proc("".join(json.dumps(r) + "\n" for r in (records or [{}]))),
        )

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
