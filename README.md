# tiktok-cli

TikTok URL → transcript files. No login, no LLM, runs locally. Built for AI agents.

Point the CLI at a TikTok video URL and it writes caption or Whisper transcripts
to disk. An agent (Claude Code, Codex, Devin, a script) reads the files itself;
the CLI does no summarization or LLM calls.

## Install

Requires Python 3.11+.

```bash
# Recommended: isolated tool install straight from git
uv tool install git+https://github.com/quangdang46/tiktok_cli

# Alternatives
pipx install git+https://github.com/quangdang46/tiktok_cli
pip install git+https://github.com/quangdang46/tiktok_cli
```

This gives you the `tiktok` command. Verify with `tiktok doctor`.

### Optional extras

- **Apple Silicon (macOS arm64):** install the `mlx` extra for the faster
  mlx-whisper backend (auto-selected when available):

  ```bash
  uv tool install --with mlx-whisper git+https://github.com/quangdang46/tiktok_cli
  # or after pip install:
  pip install "tiktok-cli[mlx]"
  ```

  Without it, Whisper falls back to faster-whisper automatically.

- **Discovery commands are suspended.** `info`, `search`, `list`, `tag`,
  `trending`, and `discover` were built on the optional `tt` binary
  ([tamnd/tiktok-cli](https://github.com/tamnd/tiktok-cli)) but TikTok's WAF
  blocks those endpoints for most IPs, making them unreliable in practice.
  They are disabled in the CLI for now; the code and tests remain in the repo
  and can be re-enabled if TikTok's anti-bot posture changes.

## Quickstart

```bash
tiktok transcript https://www.tiktok.com/@user/video/1234567890
```

Shortlinks (`vm.tiktok.com`, `vt.tiktok.com`) and multiple URLs work:

```bash
tiktok transcript url1 url2 url3
```

Output lands in `./tiktok-transcripts/VIDEO_ID/`:

```
tiktok-transcripts/VIDEO_ID/
├── source.info.json      # raw yt-dlp metadata (written once)
├── metadata.json         # compact: title, uploader, duration, counts, url
├── subs/                 # raw caption files downloaded from TikTok
│   └── VIDEO_ID.vie.vtt
├── transcript.txt        # plain text, no timestamps — point your agent here
├── transcript.srt        # SubRip with timestamps
├── transcript.vtt        # WebVTT with timestamps
├── transcript.json       # [{start, end, text}] cue list
└── transcript.md         # markdown: title + metadata + [mm:ss] cues
```

Every run also appends one line per video to `tiktok-transcripts/index.jsonl`
(`{video_id, url, status, language, cue_count, duration, artifact_dir, ...}`),
which is enough to build digests or skip already-processed videos later.

**For agents:** after `tiktok transcript <url>` succeeds, read
`transcript.txt` for the plain text or `transcript.md` for the timestamped,
metadata-rich version. `transcript` prints one summary line per video to
stdout (`VIDEO_ID | source | cues=N | dir`); progress and errors go to stderr,
so stdout stays pipe-safe.

## Commands

| Command | Description | Key flags |
|---------|-------------|-----------|
| `tiktok transcript <urls...>` | Transcribe one or more videos (caption-first, Whisper fallback). | `-o/--output-dir`, `--whisper`, `--engine`, `--model`, `--format`, `--keep-audio`, `--refresh`, `--cookies-from-browser`, `-v` |
| `tiktok batch <file>` | Process a list of URLs, one per line (`#` comments allowed); per-video failures don't stop the run. | same pipeline flags as `transcript` |
| `tiktok doctor` | Check yt-dlp, ffmpeg, faster-whisper, mlx-whisper, cached models, `tt`, network, output dir. Exit 1 if a core dep is missing. | — |

> Discovery commands (`info`, `search`, `list`, `tag`, `trending`,
> `discover`) are currently suspended — see Limitations.

`transcript` and `batch` share the same option set:

```
tiktok transcript <urls...>
  -o, --output-dir DIR         artifact root            [default: tiktok-transcripts]
  -m, --model NAME             Whisper model            [default: small]
  -l, --language LANG          Whisper language hint    [default: auto-detect]
      --whisper MODE           auto | always | never    [default: auto]
      --engine NAME            auto | faster | mlx       [default: auto]
      --format FMT             txt|srt|vtt|json|md|all   [default: all]
      --keep-audio             keep the downloaded audio after transcribing
      --refresh                bypass the transcript.json cache and reprocess
      --cookies-from-browser B pass browser cookies to yt-dlp (firefox, chrome...)
      --cookies FILE           Netscape cookies.txt for authenticated requests
  -v, --verbose                 yt-dlp/whisper debug output on stderr
```

## How it works

1. **Caption-first.** Most TikToks ship TikTok's own caption track. The CLI
   asks yt-dlp for subtitle files, picks the best one (manual > auto,
   Vietnamese > English > anything), parses the VTT, dedupes repeated
   auto-caption cues, and renders all formats. No Whisper model loads, no
   audio downloads.
2. **Whisper fallback.** If a video has no usable captions, audio is
   downloaded and transcribed locally:
   - `faster-whisper` (CTranslate2) is the default backend — pip-installable,
     runs on CPU, int8 by default.
   - `mlx-whisper` is preferred automatically on Apple Silicon when the
     `[mlx]` extra is installed. `--engine faster|mlx` overrides `auto`.
3. **Local-only.** Transcription never leaves your machine. Only yt-dlp
   fetches metadata/audio from TikTok; no transcript websites, no API keys,
   no login.

STT settings are tuned against Whisper hallucination on music/noise:
`condition_on_previous_text=False`, VAD filter on, greedy decoding
(`beam_size=1`, `temperature=0`), and low-confidence/no-speech segments are
dropped.

Statuses per video (in `index.jsonl` and the stdout summary): `caption`,
`whisper`, `no-captions` (`--whisper never` and no captions), `no-audio`,
`photo-post`, `skipped-cached`, `failed`.

## Options reference

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--whisper` | `auto`, `always`, `never` | `auto` | `auto` = Whisper only when captions are missing; `always` = skip captions entirely; `never` = captions only, no-caption videos end as `no-captions`. |
| `--engine` | `auto`, `faster`, `mlx` | `auto` | `auto` = mlx-whisper on Apple Silicon, faster-whisper elsewhere. |
| `--model` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`, `distil-large-v3`, HF repo id, or local path | `small` | faster-whisper names pass through; mlx maps short names to `mlx-community/whisper-*-mlx` repos. `turbo` (~1.6 GB) is a good quality/speed upgrade over `small`. |
| `--format` | `txt`, `srt`, `vtt`, `json`, `md`, `all` | `all` | Render only the formats you need. |
| `--keep-audio` | flag | off | Audio is deleted after transcribing by default. |
| `--refresh` | flag | off | Re-fetch captions/audio and re-transcribe even if `transcript.json` exists. |
| `--cookies-from-browser` | browser name | — | Read cookies from a local browser for age/login-gated videos. |
| `--cookies` | path | — | Netscape `cookies.txt` file. |
| `-o, --output-dir` | path | `./tiktok-transcripts` | Artifact root; one `VIDEO_ID/` folder per video plus `index.jsonl`. |
| `-l, --language` | code | auto | Whisper language hint (e.g. `vi`, `en`). |
| `-v, --verbose` | flag | off | yt-dlp/whisper debug on stderr. |

## Output layout

```
tiktok-transcripts/                  # --output-dir
├── VIDEO_ID/                        # yt-dlp info["id"]
│   ├── source.info.json             # raw yt-dlp info (written once)
│   ├── metadata.json                # compact: title, uploader, duration, counts, url
│   ├── subs/                        # raw caption .vtt files from yt-dlp
│   │   └── VIDEO_ID.vie.vtt ...
│   ├── audio.*                      # only with --keep-audio (Whisper path)
│   ├── transcript.vtt               # canonical timestamped (caption or whisper)
│   ├── transcript.srt
│   ├── transcript.txt               # plain text, no timestamps — what agents read
│   ├── transcript.json              # [{start, end, text}]
│   ├── transcript.md                # # title + metadata + [mm:ss] cues
│   ├── images/                      # photo posts only: slideshow images
│   │   └── image_01.jpg ...
│   └── images.json                  # photo posts only: image manifest
└── index.jsonl                      # append-only log of every processed video
```

## Limitations

- **Private, deleted, age-gated, or login-required videos fail.** The CLI
  makes no login flow; `--cookies-from-browser` / `--cookies` are a
  best-effort passthrough and will not bypass everything.
- **TikTok changes its internals often.** Downloading relies on yt-dlp's
  TikTok extractor; when TikTok breaks it, upgrade yt-dlp
  (`uv tool install --force ...`) and run `tiktok doctor` to check versions.
- **Discovery commands are suspended.** `info`, `search`, `list`, `tag`,
  `trending`, and `discover` depend on the external `tt` binary and TikTok's
  web endpoints, which sit behind aggressive anti-bot/WAF protection — in
  practice most IPs get challenged even on the sturdier read path, so the
  commands were removed from the CLI. `transcript`/`batch`/`doctor` are
  unaffected.
- **No captions + `--whisper never`** produces `no-captions`: metadata and
  an index entry, but no transcript files.
- **Photo/slideshow posts** (`/photo/` URLs): yt-dlp cannot read `/photo/`
  URLs, so the CLI rewrites them to the equivalent `/video/` form — the
  post's audio track is transcribed as usual — and additionally downloads
  the slideshow images into `VIDEO_ID/images/` plus an `images.json`
  manifest, by solving TikTok's public JS challenge on the post page.
- **No LLM features.** This CLI extracts transcripts only; summarization,
  chaptering, and analysis are the caller's job.

## Development

```bash
uv sync                     # install deps + dev extras into .venv
uv run pytest               # fast unit tests — no network, no models
uv run pytest -m slow       # real tiny-model smoke test (downloads ~75 MB once)
uv run ruff check .
uv run ruff format .
```

The unit test suite is fully offline: it uses fixture VTT/JSON files and
mocks yt-dlp, Whisper, and the `tt` binary. Live TikTok runs are manual
integration checks.

## License

MIT
