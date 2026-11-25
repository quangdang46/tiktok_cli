# tiktok-cli

<div align="center">
  <img src="docs/assets/tiktok_cli_illustration.webp" alt="tiktok-cli — TikTok URL to transcript files, no login, no LLM">
</div>

<div align="center">

![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-blue.svg)
![Python](https://img.shields.io/badge/python-%E2%89%A53.11-3776AB.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Release](https://img.shields.io/github/v/release/quangdang46/tiktok_cli)

</div>

**TikTok URL → transcript files. No login, no LLM, transcription runs locally.**
One command turns any public TikTok video or photo post into
`transcript.txt`, `.srt`, `.vtt`, `.json` and `.md` plus metadata —
preferring existing captions, Whisper as fallback, designed so AI agents
read the output directly without any middleman website.

<div align="center">

```bash
curl -fsSL "https://raw.githubusercontent.com/quangdang46/tiktok_cli/main/install.sh?$(date +%s)" | bash
```

</div>

---

## Agent Quickstart

Built for agents (Claude Code, Codex, Devin, scripts). Contract:

- **stdout carries results only** — `transcript` prints one line per video:
  `VIDEO_ID | source | cues=N | dir`; `batch` prints each video's
  `transcript.txt` path plus a final summary line. There is no `--json`
  flag because `transcript.json` is already machine-readable output.
- **stderr carries all diagnostics** — progress bars, warnings, yt-dlp
  logs, batch summary table. Safe to pipe stdout.
- **exit 0 = every URL succeeded**; `transcript` exits 1 if any URL
  failed, `batch` exits 1 only when *nothing* succeeded and at least one
  URL failed.

```bash
# 1. Transcribe — writes to ./tiktok-transcripts/VIDEO_ID/
tiktok transcript "https://www.tiktok.com/@user/video/123"

# 2. Read the transcript — plain text, no timestamps, agent-sized
tiktok-transcripts/VIDEO_ID/transcript.txt

# 3. Timestamped version with metadata for citation
tiktok-transcripts/VIDEO_ID/transcript.md

# 4. Machine-readable cue list
tiktok-transcripts/VIDEO_ID/transcript.json   # [{start, end, text}]

# 5. Batch from a URL file (stdout = transcript.txt paths)
tiktok batch urls.txt

# 6. Health check before a big run
tiktok doctor
```

**Suggested agent prompt:** *"Run `tiktok transcript <url>`, then read
`tiktok-transcripts/<id>/transcript.txt` (or `.md` if you need
timestamps). Don't parse stdout for content — stdout only carries status
lines."*

---

## TL;DR

### The problem

- You see a TikTok worth watching but don't want to sit through 3 minutes.
- Transcript sites require login, make you upload the link to a third
  party, or paywall/lock the results.
- Hand-assembling yt-dlp + ffmpeg + Whisper per video means re-solving
  caption parsing, VTT handling, hallucination guards, and output formats
  every time.

### The solution

`tiktok transcript <url>` runs the whole pipeline in one command:

1. Fetch metadata via yt-dlp.
2. **Prefer captions** — download TikTok's own caption track when present
   (most videos have auto-captions → Whisper never runs).
3. **Whisper fallback** — local faster-whisper (mlx-whisper on Apple
   Silicon), with VAD + anti-hallucination settings.
4. Emit `txt`/`srt`/`vtt`/`json`/`md` + `metadata.json`, append to
   `index.jsonl`.

Photo/slideshow posts (`/photo/`) get their **audio** transcribed **and**
their images downloaded — the CLI solves TikTok's public JS challenge to
read `imagePost` data that yt-dlp can't see.

### Why not just assemble yt-dlp + Whisper yourself?

- TikTok captions come back as raw `.vtt` — you still have to parse
  timestamps, merge cues, pick a language, and produce a clean transcript.
- Whisper hallucinates on music/silence by default — you need VAD filters
  and `condition_on_previous_text=False`, which few remember to set.
- `/photo/` posts are rejected outright by yt-dlp's extractor; you must
  rewrite the URL and solve the client-side challenge yourself.
- Batch + cache + indexing you'd have to build — tiktok-cli ships them,
  idempotent by default.

### Why tiktok-cli?

| Capability | tiktok-cli | yt-dlp + whisper (manual) | gerardnico/transcribe | gallery-dl |
|---|---|---|---|---|
| TikTok URL → transcript | ✅ one command | ⚠️ assemble it | ✅ | ❌ (media only) |
| Prefer captions (skip Whisper) | ✅ | ❌ manual | ✅ | n/a |
| Local STT, no API key | ✅ faster/mlx-whisper | ✅ | ✅ openai-whisper (heavy) | n/a |
| txt/srt/vtt/json/md formats | ✅ all 5 | manual | partial | ❌ |
| Photo post images + audio | ✅ | ❌ | ❌ | ✅ images only |
| Batch + idempotent index | ✅ `index.jsonl` | ❌ | ⚠️ session cache | ⚠️ |
| Agent contract (stdout/stderr) | ✅ | ❌ | ⚠️ | ❌ |
| No login required | ✅ | ✅ | ✅ | ✅ |
| Discovery (search/trending) | ⏸️ suspended | ❌ | ❌ | ⚠️ WAF-blocked |

---

## Quick example

```bash
# Single video — caption path (instant, no Whisper needed)
tiktok transcript "https://www.tiktok.com/@cnn/video/7489575527632833838"
# → tiktok-transcripts/7489575527632833838/transcript.txt  (40 cues, captions)

# Force Whisper even when captions exist
tiktok transcript <url> --whisper always -m turbo

# Captions only — zero Whisper cost
tiktok transcript <url> --whisper never

# Photo post — audio transcript + slideshow images
tiktok transcript "https://www.tiktok.com/@user/photo/7707892619572972813"
# → VIDEO_ID/images/image_01.jpg ... + images.json + transcript.*

# Batch from a file (# comments allowed)
tiktok batch urls.txt
# → transcript.txt path per video + summary table on stderr;
#   one bad URL never kills the run

# Re-runs are free — processed URLs skip instantly
tiktok transcript <url>          # → skipped-cached
tiktok transcript <url> --refresh  # force redo

# Cookies when TikTok is picky (optional, not required)
tiktok transcript <url> --cookies-from-browser chrome
```

---

## Commands

| Command | Description | Key flags |
|---------|-------------|-----------|
| `tiktok transcript <urls...>` | Transcribe one or more videos (captions first, Whisper fallback). | `-o/--output-dir`, `--whisper auto\|always\|never`, `--engine auto\|faster\|mlx`, `-m/--model`, `--format txt\|srt\|vtt\|json\|md\|all`, `--keep-audio`, `--refresh`, `--cookies-from-browser`, `--cookies`, `-v` |
| `tiktok batch <file>` | Process a URL list, one URL per line (`#` comments allowed, auto-deduped); per-video errors don't stop the run. | same pipeline flags as `transcript` |
| `tiktok doctor` | Checks yt-dlp, ffmpeg, faster-whisper, mlx-whisper, cached models, `tt`, network, output dir. Exit 1 on missing core deps. | — |

> Discovery commands (`info`, `search`, `list`, `tag`, `trending`,
> `discover`) are currently **suspended** — see Limitations.

`tiktok transcript` and `batch` share the same options:

| Flag | Default | Meaning |
|------|---------|---------|
| `-o, --output-dir` | `./tiktok-transcripts` | Root directory for results |
| `--whisper` | `auto` | `auto` = Whisper only when no captions; `always` = skip captions; `never` = captions only |
| `--engine` | `auto` | `mlx` on Apple Silicon when installed, else `faster` |
| `-m, --model` | `small` | `tiny` `base` `small` `medium` `large-v3` `turbo` `distil-large-v3`, HF repo, or local path |
| `--format` | `all` | Transcript files to write |
| `--keep-audio` | off | Keep `audio.*` after Whisper (default: delete) |
| `--refresh` | off | Bypass cache, re-download and re-transcribe |
| `-l, --language` | auto | Language hint for Whisper |
| `--cookies-from-browser` | — | `chrome`/`firefox`/`safari`/... passed through to yt-dlp |
| `--cookies` | — | Netscape-format `cookies.txt` file |
| `-v, --verbose` | off | yt-dlp debug logs to stderr |

## Output structure

```
tiktok-transcripts/                  # --output-dir
├── VIDEO_ID/                        # yt-dlp info["id"]
│   ├── source.info.json             # raw yt-dlp info (written once)
│   ├── metadata.json                # compact: title, uploader, duration, counts, url
│   ├── subs/                        # raw caption files from yt-dlp
│   │   └── VIDEO_ID.eng-US.vtt ...
│   ├── audio.*                      # only on the Whisper path with --keep-audio
│   ├── transcript.vtt               # canonical timestamped (captions or whisper)
│   ├── transcript.srt
│   ├── transcript.txt               # plain text, no timestamps — what agents read
│   ├── transcript.json              # [{start, end, text}]
│   ├── transcript.md                # # title + metadata + cue [mm:ss]
│   ├── images/                      # photo posts only: slideshow images
│   │   └── image_01.jpg ...
│   └── images.json                  # photo posts only: image manifest
└── index.jsonl                      # append-only log of every processed video
```

`index.jsonl` records `{video_id, url, status, language, cue_count, duration,
artifact_dir, processed_at}` — enough to build digests or skip processed
videos without a database. Statuses: `caption`, `whisper`, `no-captions`,
`no-audio`, `photo-post`, `skipped-cached`, `failed`.

## Design principles

| Principle | Why |
|-----------|-----|
| Captions first, Whisper fallback | Most TikTok videos have auto-captions — saves ~90% of STT compute |
| Heavy deps lazy-loaded | `tiktok --help` stays fast; faster-whisper/yt-dlp import only when needed |
| stdout = data, stderr = diagnostics | Agents can pipe stdout safely (omni-transcriber-style contract) |
| Idempotent by default | `transcript.json` exists → skip; `--refresh` to redo |
| Per-video error isolation | One bad URL never kills a batch; errors land in `index.jsonl` |
| Honest errors | Private/WAF/rate-limit → clear message + fix hint, never silent empty output |
| No torch, no openai-whisper | faster-whisper's PyAV decodes audio directly — no ffmpeg extract step |

## Installation

Requires Python 3.11+. The one-line installer auto-detects `uv` → `pipx` → `pip`:

```bash
# macOS / Linux
curl -fsSL "https://raw.githubusercontent.com/quangdang46/tiktok_cli/main/install.sh?$(date +%s)" | bash

# Windows PowerShell
irm "https://raw.githubusercontent.com/quangdang46/tiktok_cli/main/install.ps1" | iex
```

Installer flags: `--version vX.Y.Z` (pin a release), `--prefer uv|pipx|pip`,
`--with-mlx` (Apple Silicon Whisper backend), `--verify` (runs
`tiktok --help` after install), `--uninstall`, `--quiet`.

Manual equivalents:

```bash
# Recommended: isolated tool install straight from git
uv tool install git+https://github.com/quangdang46/tiktok_cli

# Alternatives
pipx install git+https://github.com/quangdang46/tiktok_cli
pip install git+https://github.com/quangdang46/tiktok_cli
```

This gives you the `tiktok` command. Check with `tiktok doctor`.

### Optional extra

- **Apple Silicon (macOS arm64):** install the `mlx` extra to use the
  faster mlx-whisper backend (auto-selected when present):

  ```bash
  uv tool install --with mlx-whisper git+https://github.com/quangdang46/tiktok_cli
  # or after pip install:
  pip install "tiktok-cli[mlx]"
  ```

  Without it, Whisper falls back to faster-whisper.

## Photo posts / slideshows

`/photo/` URLs are image carousels with an audio track. The CLI will:

1. Rewrite the URL to the equivalent `/video/` form (yt-dlp's TikTok
   extractor rejects `/photo/` outright, but the same id resolves via
   `/video/`).
2. Transcribe the audio track like a normal video.
3. Fetch the post page, solve TikTok's public JS proof-of-work challenge,
   and download `imagePost.images` into `VIDEO_ID/images/` with
   `images.json` (source URL, dimensions, author, timestamp).

Image download is best-effort: if TikTok changes the challenge format,
the audio transcript still succeeds and a warning goes to stderr.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Download failed: ... certificate verify failed` | Proxy/AV blocking local TLS, or flaky edge CDN | Retry; `curl-cffi` impersonation is already on — persistent failure means network-level blocking |
| `private video` / `members-only` / `sign in` | Content requires login | `--cookies-from-browser chrome` (Safari needs Full Disk Access) or `--cookies cookies.txt` |
| `rate-limit` / `429` | Too many requests | Wait and retry; batch runs sequentially by design |
| Whisper transcript is nonsense on music | No speech — VAD correctly yields 0 cues | Expected; check cue count in `transcript.json` |
| Poor Vietnamese on `small` model | Model too small for Vietnamese | `-m turbo` or `-m large-v3-turbo` (better VN, ~1.5GB download) |
| `no captions - transcribing audio` then slow | Video has no caption track | Normal — first Whisper run downloads the model once |
| `Unsupported URL` on a `/photo/` link | Old behavior — fixed in 0.1.0 | Upgrade; photo posts work now |
| `ffmpeg` WARN in doctor | Not installed | Optional — faster-whisper's PyAV decodes audio directly |
| `mlx-whisper` WARN | Not installed / not arm64 | Optional — falls back to faster-whisper |

## Limitations

- **Private, deleted, age-restricted, or login-required videos fail.**
  The CLI has no login flow; `--cookies-from-browser` / `--cookies` are
  best-effort passthroughs and can't bypass everything.
- **TikTok changes internals often.** Downloading depends on yt-dlp's
  TikTok extractor; when TikTok breaks it, upgrade yt-dlp
  (`uv tool install --force ...`) and re-run `tiktok doctor` to check
  the version.
- **Discovery commands are suspended.** `info`, `search`, `list`, `tag`,
  `trending`, `discover` depend on the external `tt` binary and TikTok web
  endpoints behind aggressive anti-bot/WAF — most IPs get challenged even
  on the more resilient read paths, so the commands were removed from the
  CLI. `transcript`/`batch`/`doctor` are unaffected. Code and tests remain
  in the repo to re-enable when needed.
- **No captions + `--whisper never`** yields `no-captions`: metadata and
  an index entry exist, but no transcript file.
- **Slideshow images are best-effort.** Depends on TikTok's public JS
  challenge format staying stable; the audio transcript is unaffected.
- **No LLM features.** This CLI only extracts transcripts; summarizing,
  chaptering, and analysis are the caller's job.

## FAQ

**Do I need a TikTok login?**
No. Public videos work anonymously. `--cookies-from-browser` exists only
as a fallback for age-restricted content or flaky IPs.

**Does audio leave my machine?**
No. Captions come from TikTok's own subtitle track; Whisper runs locally
(faster-whisper or mlx-whisper). Nothing is uploaded anywhere.

**Why prefer captions over always running Whisper?**
TikTok auto-captions cover most videos and are instant + free. Whisper
only runs when there's no caption track (`--whisper auto`, default).

**Which Whisper model should I use?**
`small` (default, ~466MB) is the speed/quality balance. `turbo` or
`large-v3-turbo` (~1.5GB) is noticeably better for Vietnamese and accented
speech. `tiny`/`base` for quick drafts.

**What does `--whisper never` do?**
Skips Whisper entirely — videos without captions get `no-captions`
status (metadata + index entry only). Use it when you only want free
caption extraction.

**Can it get images from photo posts?**
Yes — `images/` + `images.json` in the artifact directory. The audio
track is also transcribed (usually just music → 0 cues, which is correct).

**Why did my batch exit non-zero?**
`batch` only exits 1 when nothing succeeded *and* at least one URL
failed. Partial success still exits 0 — check the summary table and
`index.jsonl` for per-URL status.

**Will TikTok break this tool?**
Sooner or later, yes — this is scraping. yt-dlp is actively maintained;
run `tiktok doctor` to check the version and upgrade with
`uv tool install --force git+https://github.com/quangdang46/tiktok_cli`.

## Development

```bash
uv sync                     # install deps + dev extras into .venv
uv run pytest               # test suite, no network, no model downloads
uv run ruff check .         # lint
uv run ruff format .        # format
uv run tiktok transcript <url>   # run the CLI from source
```

CI runs ruff + pytest on Ubuntu, macOS, Windows × Python 3.12/3.13.
Integration tests against real TikTok URLs are manual (see PLAN.md §9).

## License

MIT — see [LICENSE](LICENSE).
