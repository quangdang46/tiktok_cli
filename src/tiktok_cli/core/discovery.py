"""Wrapper around the external `tt` binary (github.com/tamnd/tiktok-cli).

`tt` is a Go binary that reimplements TikTok's web signing and SSR parsing.
We never reimplement that in Python — every discovery read shells out to `tt`
and parses its JSONL record stream. All tt CLI knowledge lives in this module;
commands consume plain dicts/lists.

Verified against tt's source (any-cli kit v0.3.3 + tiktok/ops.go,
tiktok/discover_op.go):

- Output format flag is ``--output jsonl`` (global, ``-o`` short) — there is
  no ``--format`` flag.
- Record limit is the global ``-n`` / ``--limit`` flag.
- discover seeds: ``--seed`` (user, repeatable), ``--seed-tag``,
  ``--seed-sound``, ``--seed-video``, ``--seed-search``, ``--trending``;
  ``--depth``, ``--max-nodes``, ``--top``. (Bead spec said
  ``--seed-hashtag``/``--seed-user`` — the real flags are ``--seed-tag`` and
  ``--seed``.)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from tiktok_cli.core.errors import UserError

TT_INSTALL_HINT = "install: go install github.com/tamnd/tiktok-cli/cmd/tt@latest"

# TikTok WAF/challenge markers. Only consulted on failure paths — a successful
# JSONL stream can legitimately contain "403" inside numeric ids.
_WAF_MARKERS = ("walled", "challenge", "403")

_HANDLE_URL_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.IGNORECASE)
_TAG_URL_RE = re.compile(r"tiktok\.com/tag/([^/?#]+)", re.IGNORECASE)

_DISCOVER_FLAGS = {
    "video": "--seed-video",
    "hashtag": "--seed-tag",
    "user": "--seed",
    "search": "--seed-search",
}


def tt_available() -> bool:
    """True when the `tt` binary is on PATH."""
    return shutil.which("tt") is not None


def _require_tt() -> None:
    if not tt_available():
        raise UserError(f"tt not installed — {TT_INSTALL_HINT}")


def run_tt(args: list[str], *, timeout: int = 120) -> list[dict]:
    """Run `tt <args> --output jsonl` and parse stdout as JSONL or a JSON array.

    Raises UserError on missing binary, non-zero exit, WAF challenge, empty
    output, or unparseable output.
    """
    _require_tt()
    cmd = ["tt", *args, "--output", "jsonl", "--quiet"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise UserError(
            f"tt timed out after {timeout}s",
            hint="the request may be rate-limited; retry with a smaller limit",
        ) from exc
    except OSError as exc:
        raise UserError(f"failed to run tt: {exc}") from exc

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        if _looks_walled(stdout + "\n" + stderr):
            raise UserError(_WAF_MSG, hint=_WAF_HINT)
        tail = stderr.strip().splitlines()
        detail = tail[-1] if tail else f"exit code {proc.returncode}"
        raise UserError(f"tt failed: {detail}")

    records = _parse_records(stdout)
    if not records:
        if _looks_walled(stdout + "\n" + stderr):
            raise UserError(_WAF_MSG, hint=_WAF_HINT)
        raise UserError("tt returned no records")
    return records


_WAF_MSG = "TikTok served a WAF challenge — wait and retry or reduce rate"
_WAF_HINT = "tt video/user use the sturdier SSR plane; search/discover hit the signed API plane"


def _looks_walled(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _WAF_MARKERS)


def _parse_records(stdout: str) -> list[dict]:
    """Parse tt output as a JSON array or JSONL (one object per line)."""
    text = stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _normalize_handle(ref: str) -> str:
    """'@user', 'user', or a tiktok.com/@user URL -> bare handle."""
    ref = ref.strip()
    m = _HANDLE_URL_RE.search(ref)
    if m:
        return m.group(1)
    return ref.lstrip("@")


def _normalize_tag(tag: str) -> str:
    """'#tag', 'tag', or a tiktok.com/tag/tag URL -> bare tag name."""
    tag = tag.strip()
    m = _TAG_URL_RE.search(tag)
    if m:
        return m.group(1)
    return tag.lstrip("#")


def video_info(url: str) -> dict:
    """One video record for a URL or bare id (`tt video`)."""
    records = run_tt(["video", url])
    return records[0]


def search(keyword: str, limit: int = 20) -> list[dict]:
    """Mixed search hits — videos and users (`tt search`)."""
    return run_tt(["search", keyword, "-n", str(limit)])


def user_posts(handle: str, limit: int = 30) -> list[dict]:
    """A user's public videos (`tt posts`)."""
    return run_tt(["posts", _normalize_handle(handle), "-n", str(limit)])


def hashtag_videos(tag: str, limit: int = 30) -> list[dict]:
    """Videos under a hashtag (`tt hashtag --videos`)."""
    return run_tt(["hashtag", _normalize_tag(tag), "--videos", "-n", str(limit)])


def trending(limit: int = 30) -> list[dict]:
    """Logged-out recommend feed (`tt trending`)."""
    return run_tt(["trending", "-n", str(limit)])


def discover(
    seeds: list[tuple[str, str]],
    top: int = 20,
    depth: int = 2,
    max_nodes: int | None = None,
) -> list[dict]:
    """Graph walk from seeds (`tt discover`).

    seeds is a list of (kind, value) pairs; kind is one of 'video',
    'hashtag', 'user', 'search', 'trending'. 'trending' takes an empty value.
    """
    args = ["discover"]
    for kind, value in seeds:
        kind = kind.strip().lower()
        if kind == "trending":
            args.append("--trending")
            continue
        flag = _DISCOVER_FLAGS.get(kind)
        if flag is None:
            raise UserError(
                f"unknown discover seed kind {kind!r}",
                hint="use one of: video, hashtag, user, search, trending",
            )
        value = value.strip()
        if not value:
            raise UserError(f"discover seed of kind {kind!r} needs a value")
        if kind == "user":
            value = _normalize_handle(value)
        elif kind == "hashtag":
            value = _normalize_tag(value)
        args += [flag, value]
    args += ["--depth", str(depth), "--top", str(top)]
    if max_nodes:
        args += ["--max-nodes", str(max_nodes)]
    # A graph walk makes many requests; give it more headroom than the default.
    return run_tt(args, timeout=600)
