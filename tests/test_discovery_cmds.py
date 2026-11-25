"""Unit tests for the phase-2 discovery commands — discovery layer fully mocked."""

from __future__ import annotations

import json
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from tiktok_cli.commands import (
    discover as discover_cmd,
)
from tiktok_cli.commands import (
    info as info_cmd,
)
from tiktok_cli.commands import (
    list_cmd,
)
from tiktok_cli.commands import (
    search as search_cmd,
)
from tiktok_cli.commands import (
    tag as tag_cmd,
)
from tiktok_cli.commands import (
    trending as trending_cmd,
)
from tiktok_cli.commands._table import render_info, render_video_table
from tiktok_cli.core.errors import UserError

# Discovery commands are suspended in cli.py (TikTok WAF) — test them via a
# dedicated app so coverage survives the suspension.
DISCOVERY_APP = typer.Typer()
DISCOVERY_APP.command(name="info")(info_cmd.info)
DISCOVERY_APP.command(name="search")(search_cmd.search)
DISCOVERY_APP.command(name="list")(list_cmd.list_videos)
DISCOVERY_APP.command(name="tag")(tag_cmd.tag)
DISCOVERY_APP.command(name="trending")(trending_cmd.trending)
DISCOVERY_APP.command(name="discover")(discover_cmd.discover)

runner = CliRunner()

VIDEO = {
    "id": "7350000000000000001",
    "desc": "hello world",
    "author": "dev.daily",
    "author_id": "dev.daily",
    "play_count": 128400,
    "digg_count": 9800,
    "comment_count": 312,
    "create_time": 1732100000,
    "url": "https://www.tiktok.com/@dev.daily/video/7350000000000000001",
}

SEARCH_HIT = {
    "type": "video",
    "id": "111",
    "title": "a search hit",
    "author": "searcher",
    "url": "https://www.tiktok.com/@searcher/video/111",
}

DISCOVER_NODE = {
    "kind": "video",
    "id": "222",
    "name": "discovered vid",
    "author": "walker",
    "metric": 5000,
    "score": 0.875,
    "depth": 1,
    "via": "seed",
    "url": "https://www.tiktok.com/@walker/video/222",
}


def _stderr(result) -> str:
    try:
        return result.stderr or ""
    except (AttributeError, ValueError):
        return ""


class TestRenderHelpers:
    def test_video_table_renders_fields(self):
        out = render_video_table([VIDEO])
        assert "dev.daily" in out
        assert "7350000000000000001" in out
        assert "128,400" in out
        assert "hello world" in out
        assert "tiktok.com/@dev.daily/video/" in out

    def test_video_table_tolerates_missing_fields(self):
        out = render_video_table([{"id": "9"}])
        assert "9" in out

    def test_score_column_only_when_present(self):
        assert "Score" not in render_video_table([VIDEO])
        assert "Score" in render_video_table([DISCOVER_NODE])
        assert "0.875" in render_video_table([DISCOVER_NODE])

    def test_empty_records(self):
        assert render_video_table([]) == "no results"

    def test_nested_fallbacks(self):
        nested = {
            "id": "1",
            "author": {"nickname": "Nested", "unique_id": "nested"},
            "stats": {"play_count": 42},
            "desc": "d",
        }
        out = render_video_table([nested])
        assert "Nested" in out and "42" in out

    def test_info_table(self):
        out = render_info(VIDEO)
        assert "hello world" in out
        assert "dev.daily" in out
        assert "128,400" in out


class TestInfo:
    @patch("tiktok_cli.core.discovery.video_info")
    def test_table_output(self, mock_info):
        mock_info.return_value = VIDEO
        result = runner.invoke(DISCOVERY_APP, ["info", "https://tiktok.com/@u/video/1"])
        assert result.exit_code == 0, result.output
        assert "dev.daily" in result.output
        mock_info.assert_called_once_with("https://tiktok.com/@u/video/1", client=None)

    @patch("tiktok_cli.core.discovery.video_info")
    def test_json_output(self, mock_info):
        mock_info.return_value = VIDEO
        result = runner.invoke(DISCOVERY_APP, ["info", "https://tiktok.com/@u/video/1", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == VIDEO

    @patch("tiktok_cli.core.discovery.video_info")
    def test_user_error_propagates(self, mock_info):
        mock_info.side_effect = UserError("tt not installed — install it")
        result = runner.invoke(DISCOVERY_APP, ["info", "u"])
        assert result.exit_code == 1
        assert "tt not installed" in result.output + _stderr(result)


class TestSearch:
    @patch("tiktok_cli.core.discovery.search")
    def test_table_and_limit(self, mock_search):
        mock_search.return_value = [SEARCH_HIT]
        result = runner.invoke(DISCOVERY_APP, ["search", "cute cats", "-n", "5"])
        assert result.exit_code == 0, result.output
        assert "a search hit" in result.output
        assert "searcher" in result.output
        mock_search.assert_called_once_with("cute cats", limit=5)

    @patch("tiktok_cli.core.discovery.search")
    def test_default_limit(self, mock_search):
        mock_search.return_value = [SEARCH_HIT]
        result = runner.invoke(DISCOVERY_APP, ["search", "cats"])
        assert result.exit_code == 0
        mock_search.assert_called_once_with("cats", limit=20)

    @patch("tiktok_cli.core.discovery.search")
    def test_json(self, mock_search):
        mock_search.return_value = [SEARCH_HIT]
        result = runner.invoke(DISCOVERY_APP, ["search", "cats", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == [SEARCH_HIT]

    @patch("tiktok_cli.core.discovery.search")
    def test_user_error(self, mock_search):
        mock_search.side_effect = UserError("TikTok served a WAF challenge")
        result = runner.invoke(DISCOVERY_APP, ["search", "cats"])
        assert result.exit_code == 1
        assert "WAF challenge" in result.output + _stderr(result)


class TestList:
    @patch("tiktok_cli.core.discovery.user_posts")
    def test_table_and_limit(self, mock_posts):
        mock_posts.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["list", "@dev.daily", "-n", "7"])
        assert result.exit_code == 0, result.output
        assert "hello world" in result.output
        mock_posts.assert_called_once_with("@dev.daily", limit=7, client=None)

    @patch("tiktok_cli.core.discovery.user_posts")
    def test_default_limit_and_url_passthrough(self, mock_posts):
        mock_posts.return_value = [VIDEO]
        url = "https://www.tiktok.com/@dev.daily"
        result = runner.invoke(DISCOVERY_APP, ["list", url])
        assert result.exit_code == 0
        mock_posts.assert_called_once_with(url, limit=30, client=None)

    @patch("tiktok_cli.core.discovery.user_posts")
    def test_json(self, mock_posts):
        mock_posts.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["list", "dev.daily", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == [VIDEO]


class TestTag:
    @patch("tiktok_cli.core.discovery.hashtag_videos")
    def test_table_and_limit(self, mock_tag):
        mock_tag.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["tag", "#fyp", "-n", "9"])
        assert result.exit_code == 0, result.output
        assert "hello world" in result.output
        mock_tag.assert_called_once_with("#fyp", limit=9)

    @patch("tiktok_cli.core.discovery.hashtag_videos")
    def test_tag_url_passthrough_and_default_limit(self, mock_tag):
        mock_tag.return_value = [VIDEO]
        url = "https://www.tiktok.com/tag/fyp"
        result = runner.invoke(DISCOVERY_APP, ["tag", url])
        assert result.exit_code == 0
        mock_tag.assert_called_once_with(url, limit=30)

    @patch("tiktok_cli.core.discovery.hashtag_videos")
    def test_json(self, mock_tag):
        mock_tag.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["tag", "fyp", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == [VIDEO]


class TestTrending:
    @patch("tiktok_cli.core.discovery.trending")
    def test_table_and_default_limit(self, mock_trending):
        mock_trending.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["trending"])
        assert result.exit_code == 0, result.output
        assert "dev.daily" in result.output
        mock_trending.assert_called_once_with(limit=20)

    @patch("tiktok_cli.core.discovery.trending")
    def test_limit_flag(self, mock_trending):
        mock_trending.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["trending", "-n", "3"])
        assert result.exit_code == 0
        mock_trending.assert_called_once_with(limit=3)

    @patch("tiktok_cli.core.discovery.trending")
    def test_json(self, mock_trending):
        mock_trending.return_value = [VIDEO]
        result = runner.invoke(DISCOVERY_APP, ["trending", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == [VIDEO]

    @patch("tiktok_cli.core.discovery.trending")
    def test_user_error(self, mock_trending):
        mock_trending.side_effect = UserError("tt not installed — install it")
        result = runner.invoke(DISCOVERY_APP, ["trending"])
        assert result.exit_code == 1
        assert "tt not installed" in result.output + _stderr(result)


class TestDiscover:
    @patch("tiktok_cli.core.discovery.discover")
    def test_seeds_and_flags(self, mock_discover):
        mock_discover.return_value = [DISCOVER_NODE]
        result = runner.invoke(
            DISCOVERY_APP,
            [
                "discover",
                "--seed-video",
                "https://tiktok.com/@u/video/1",
                "--seed-tag",
                "#fyp",
                "--seed-user",
                "@walker",
                "--seed-search",
                "cats",
                "--trending",
                "--depth",
                "3",
                "--top",
                "7",
                "--max-nodes",
                "50",
            ],
        )
        assert result.exit_code == 0, result.output
        seeds = mock_discover.call_args.args[0]
        assert seeds == [
            ("video", "https://tiktok.com/@u/video/1"),
            ("hashtag", "#fyp"),
            ("user", "@walker"),
            ("search", "cats"),
            ("trending", ""),
        ]
        assert mock_discover.call_args.kwargs == {"top": 7, "depth": 3, "max_nodes": 50}
        assert "walker" in result.output
        assert "Score" in result.output

    @patch("tiktok_cli.core.discovery.discover")
    def test_defaults(self, mock_discover):
        mock_discover.return_value = [DISCOVER_NODE]
        result = runner.invoke(DISCOVERY_APP, ["discover", "--trending"])
        assert result.exit_code == 0
        assert mock_discover.call_args.kwargs == {"top": 20, "depth": 2, "max_nodes": None}

    @patch("tiktok_cli.core.discovery.discover")
    def test_no_seed_errors(self, mock_discover):
        result = runner.invoke(DISCOVERY_APP, ["discover"])
        assert result.exit_code == 1
        assert "at least one seed" in result.output + _stderr(result)
        mock_discover.assert_not_called()

    @patch("tiktok_cli.core.discovery.discover")
    def test_json(self, mock_discover):
        mock_discover.return_value = [DISCOVER_NODE]
        result = runner.invoke(DISCOVERY_APP, ["discover", "--seed-search", "cats", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == [DISCOVER_NODE]

    @patch("tiktok_cli.core.discovery.discover")
    def test_user_error(self, mock_discover):
        mock_discover.side_effect = UserError("tt timed out after 600s")
        result = runner.invoke(DISCOVERY_APP, ["discover", "--trending"])
        assert result.exit_code == 1
        assert "timed out" in result.output + _stderr(result)
