# tiktok-cli — Detailed Plan

> TikTok video → transcript CLI. No TikTok login, no built-in LLM, transcription runs locally.
> An agent (Claude Code / Codex / Devin) calls this CLI, then reads the output files itself.

---

## 1. Goals & scope

### MVP (required)

| # | Feature | Notes |
|---|---------|-------|
| F1 | `tiktok transcript <url>` | URL → audio/captions → `transcript.txt/.srt/.vtt/.json/.md` |
| F2 | Caption-first | Use TikTok's existing caption track when present — skip Whisper entirely |
| F3 | Whisper fallback | No captions → faster-whisper (cross-platform) / mlx-whisper (Apple Silicon) |
| F4 | `tiktok transcript <url1> <url2> ...` | Multi-URL, one folder per video |
| F5 | `tiktok batch <file>` | Read URL list from file, `#` comments, skip already-transcribed |
| F6 | No login, no cookies by default | `--cookies-from-browser` / `--cookies` are optional flags |

### Phase 2 (post-MVP, optional)

| # | Feature | Source |
|---|---------|--------|
| F7 | `tiktok info <url>` | Metadata: views/likes/comments/uploader/upload_date — yt-dlp `--dump-single-json` + `--list-subs` |
| F8 | `tiktok list <@user>` | Videos from a channel — yt-dlp flat-playlist or `tt posts` |
| F9 | `tiktok search <keyword>` | Discovery — call `tt` binary (tamnd/tiktok-cli) or yt-dlp fallback |
| F10 | `tiktok discover` | Graph walk — `tt discover` |
| F11 | `tiktok tag <hashtag>` | Videos by hashtag — `tt hashtag --videos` |
| F12 | `tiktok trending` | `tt trending` |
| F13 | `tiktok doctor` | Check yt-dlp, ffmpeg, whisper model, `tt` binary |

### Explicitly out of scope

- No LLM integration inside the CLI (the agent lives outside and reads files).
- No dashboard/web UI.
- No database — filesystem artifacts are the source of truth.
- No TikTok login flow or session management (optional cookie passthrough only).
- No OCR/frames (Phase 3+, see `tiktok-extractor` reference).

---

## 2. Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.11+** | All reference repos are Python; agent-friendly; yt-dlp/whisper are Python-first |
| CLI framework | **Typer + Rich** | Used by `omni-transcriber`, `gerardnico/transcribe`, `tiktok-extractor`; rich progress bars |
| Package manager | **uv** (optional PEP 723) | `uv run` zero-install pattern (jadenmaciel/transcript); `uv tool install` for global |
| Download/subtitles | **yt-dlp** (Python API `yt_dlp.YoutubeDL`, subprocess only when needed) | Every reference repo uses it; Python API gives structured errors vs parsing CLI text |
| Audio extract | **ffmpeg** subprocess (only if needed; faster-whisper decodes via PyAV directly) | faster-whisper's bundled PyAV handles mp4/mkv/mp3 — **ffmpeg may not be needed at all** |
| STT engine | **faster-whisper** default; **mlx-whisper** auto-detected on Apple Silicon | douyin-teardown dual-backend pattern; faster-whisper is pip-install, no compile; mlx ~15x realtime on M-series |
| Discovery (Phase 2) | **`tt` binary** (tamnd/tiktok-cli, Go) via subprocess, optional dependency | Works without login; X-Bogus signing + SSR parsing already implemented; don't port to Python |

**Key decision: faster-whisper instead of whisper.cpp.**
Reasons: (1) `pip install`, no cmake/compile; (2) PyAV decodes containers directly → no ffmpeg extract step; (3) int8 CPU is fast enough for short TikTok videos; (4) whisper.cpp only wins on Apple Silicon with CoreML — mlx-whisper covers that better.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  tiktok CLI (Typer app)                                     │
│                                                             │
│  commands/                                                  │
│   transcript.py   batch.py   info.py   (phase2: search.py)  │
│                                                             │
│  core/                                                      │
│   url.py          resolve URL → canonical, video_id, kind   │
│   downloader.py   yt-dlp wrapper: info, subs, audio         │
│   captions.py     VTT parse → cues, txt/md render           │
│   stt.py          faster/mlx-whisper wrapper, model cache   │
│   artifacts.py    output dir layout, idempotency, metadata  │
│   errors.py       UserError/DownloadError + translation     │
│   discovery.py    tt binary wrapper (phase 2)               │
│                                                             │
│  external: yt-dlp · ffmpeg(optional) · faster-whisper · tt  │
└─────────────────────────────────────────────────────────────┘
```

### Design principles (from research)

1. **Caption-first, Whisper-fallback** — from `dedene/skills` + `gerardnico/transcribe`. Most TikToks have auto-captions → saves ~90% compute.
2. **Known yt-dlp subtleties** (important, keep as code comments):
   - Caption info does **not** appear in `extract_info` JSON for TikTok → must call `--list-subs` or download subs separately (dedene/skills documents this gotcha).
   - `--write-subs --write-auto-subs --sub-format vtt --sub-langs "vi.*,en.*,all"`.
   - Format select: `bestaudio/best` for audio-only; if video needed (phase 3 OCR) use `best[vcodec=h264]` — bytevc1/h265 often video-only (noted in tiktok-extractor, tiktok-transcript).
   - Shortlinks `vm./vt.tiktok.com` → yt-dlp resolves them; get video_id from `info["id"]`, never parse the URL.
3. **stdout carries only transcript/plain output; all logs → stderr** (omni-transcriber hard constraint) → agent can pipe safely.
4. **Idempotent**: `transcript.json` exists + no `--refresh` → skip (tiktok-extractor pattern).
5. **Lazy imports**: faster-whisper/model only loads when actually transcribing — `tiktok --help` < 100ms (omni-transcriber).
6. **Anti-hallucination STT settings** (douyin-teardown): `condition_on_previous_text=False`, `vad_filter=True`, `beam_size=1`, `temperature=0`.

---

## 4. Output layout

```
tiktok-transcripts/                  # --output-dir, default ./tiktok-transcripts
├── VIDEO_ID/                        # yt-dlp info["id"], sanitize [A-Za-z0-9_-]
│   ├── source.info.json             # raw yt-dlp info (written once)
│   ├── metadata.json                # compact: title, uploader, duration, counts, url
│   ├── subs/                        # raw caption files from yt-dlp
│   │   └── VIDEO_ID.vie.vtt ...
│   ├── audio.wav                    # whisper path only (16k mono if ffmpeg; raw if PyAV)
│   ├── transcript.vtt               # canonical timestamped (caption or whisper)
│   ├── transcript.srt
│   ├── transcript.txt               # plain text, no timestamps — what agents read
│   ├── transcript.json              # [{start,end,text,confidence?}]
│   ├── transcript.md                # # title + metadata + [mm:ss] cues
│   └── whisper.log                  # debug on fallback path
├── batch-2026-11-24/                # optional: group a batch run in one dir
└── index.jsonl                      # append-only log of every processed video
```

`index.jsonl` record: `{video_id, url, status: caption|whisper|no-captions|failed, language, cue_count, duration, processed_at, artifact_dir}` — enables `tiktok list`/digest later without a DB.

---

## 5. Command spec (detailed)

### `tiktok transcript <urls...>`

```
tiktok transcript https://www.tiktok.com/@user/video/123

tiktok transcript url1 url2 url3          # sequential

Options:
  -o, --output-dir DIR        default ./tiktok-transcripts
  -m, --model NAME            whisper model: tiny|base|small|turbo|large-v3-turbo
                              default: small (faster) / mlx-community/whisper-large-v3-turbo (mlx)
  -l, --language LANG         whisper language hint; auto-detect by default
  --whisper auto|always|never auto = whisper only when no captions (DEFAULT)
                              always = skip captions, force whisper
                              never = captions only; no-caption videos -> status no-captions
  --engine auto|faster|mlx    auto = mlx on Apple Silicon, faster otherwise
  --format FMT                txt|srt|vtt|json|md|all   default all
  --keep-audio                keep audio.wav (default: delete after transcribe)
  --refresh                   bypass cache, re-fetch subs/audio + re-transcribe
  --cookies-from-browser B    firefox|chrome|safari... (optional)
  --cookies FILE              Netscape cookies.txt (optional)
  -v, --verbose               stderr debug
```

Per-URL flow:

```
1. normalize url → yt_dlp extract_info(download=False) → video_id, metadata
2. cache check: transcript.json exists & !refresh → print path, done
3. CAPTION PATH:
   yt_dlp download subs only:
     --skip-download --write-subs --write-auto-subs --sub-format vtt
     --sub-langs "vi.*,en.*,vi,en,all" -o subs/%(id)s.%(ext)s
   → find .vtt preferring: vie > vie-* > en > auto-generated > any
   → parse VTT → cues[{start,end,text}]
   → render all formats → transcript_source="tiktok-captions:<lang>"
4. WHISPER PATH (if no caption and --whisper != never):
   yt_dlp download bestaudio → temp file
   faster-whisper transcribe (or mlx_whisper.transcribe)
   → segments → cues → render formats → transcript_source="whisper:<model>:<lang>"
   → delete audio unless --keep-audio
5. write metadata.json + append index.jsonl + print compact summary to stdout
```

Known edge cases (handle in code):
- Video with no audio track → `status: no-audio`, still emit metadata.
- Photo/slideshow post (`imagePost`) → `status: photo-post`, skip early.
- Private/deleted/age-gated → yt-dlp raises → `status: failed`, reason into index.
- WAF/rate-limit → retry once after 5s, then fail with `--cookies-from-browser` hint.
- Caption files with consecutive duplicate cues (TikTok auto-caption repeats) → dedupe in parse_vtt.
- `vm./vt.` shortlinks → resolved by yt-dlp; don't parse IDs manually.

### `tiktok batch <file>`

```
tiktok batch urls.txt [-o DIR] [--whisper auto] [same flags as transcript]

urls.txt format:
  # comment line
  https://www.tiktok.com/@a/video/111
  https://vm.tiktok.com/XYZ

→ sequential (MVP); parallel --jobs N in phase 2+ if needed
→ per-video try/except — one bad URL never kills the batch
→ end-of-batch summary table: ok / caption / whisper / failed counts
```

### `tiktok info <url>` (phase 2)

Metadata only via `--dump-single-json` + `--list-subs`; JSON to stdout. Fast, no download.

### `tiktok search|discover|list|tag|trending` (phase 2)

Wrappers calling the `tt` binary (optional dep, `tiktok doctor` checks it). `tt` emits JSONL → parse → print table. Without `tt` → clear "install tt" error; transcript/batch unaffected.

### `tiktok doctor`

Checks: yt-dlp version, ffmpeg (warn only — not strictly required), faster-whisper import, mlx-whisper (if arm64), model cached?, `tt` binary (phase 2), network to tiktok.com, output dir writable. PASS/WARN/FAIL table + fix hints.

---

## 6. Module spec

### `core/url.py`
- `classify_url(url) -> Video|Photo|Profile|Feed|Short|Other` — regex path `/@user/video/(\d+)`, `/photo/`, hosts `vm./vt.` (from `tiktok-transcript/lib/tiktok.js`).
- Never parse video_id from shortlinks — let yt-dlp resolve.

### `core/downloader.py`
- `YtdlpClient` wrapping `yt_dlp.YoutubeDL`:
  - `extract_info(url, download=False)`
  - `list_subtitles(url) -> {lang: [formats]}` — workaround for the caption gotcha: run with `--list-subs`-equivalent or download subs into temp dir; don't trust `info["subtitles"]` alone for TikTok.
  - `download_subtitles(url, out_dir, langs)` → list[Path] .vtt
  - `download_audio(url, tmp_dir)` → Path
  - `download_video_h264(url, out_dir)` (phase 3)
- Shared YDL opts: `quiet`, `no_warnings`, `noplaylist`, `socket_timeout=30`, `retries=3`, `js_runtimes` enabling deno/node if present (omni-transcriber `_enabled_js_runtimes` — needed for YouTube, harmless for TikTok).
- Cookies: `cookiesfrombrowser`/`cookiefile` opts only when flags passed.

### `core/captions.py`
- `parse_vtt(path) -> list[Cue{start,end,start_time,end_time,text}]` — port from dedene/skills `parse_vtt` + `strip_vtt_markup` (handles `<c>`, `<00:00:00.000>`, `\h`, HTML entities).
- `pick_caption(candidates, preference=["vie","vi","en","en-US"])` — manual sub > auto sub; vie > en > first.
- `dedupe_cues(cues)` — drop consecutive duplicate texts (auto-caption repeats).
- `cues_to_paragraphs(cues, gap_threshold=2.0)` — merge cues → paragraphs for txt/md.

### `core/stt.py`
- `TranscribeEngine` protocol: `transcribe(audio_path, language) -> list[Cue]`.
- `FasterWhisperEngine`: `WhisperModel(model, device="auto", compute_type="auto")`, cache per (model,device). Settings: `vad_filter=True`, `condition_on_previous_text=False`, `beam_size=1`, `temperature=0`.
- `MlxEngine` (darwin/arm64 only): `mlx_whisper.transcribe(path_or_hf_repo=..., language=...)`.
- `resolve_engine(auto)` → mlx if `platform.machine()=="arm64"` and import works, else faster.
- Model map: `small` → faster `small`; mlx `small` → `mlx-community/whisper-small-mlx` (table from douyin-teardown `_MLX_MODEL_MAP`).

### `core/artifacts.py`
- `VideoDir(video_id)` path builder, `is_processed()`, `write_outputs(cues, meta, source)`, `append_index(record)`.
- Filename sanitize: `[^
A-Za-z0-9_-]` → strip; validate `^[\w-]{6,}$` anyway.

### `core/errors.py`
- `UserError(msg, hint, exit_code)` → print `error: msg\nhint: ...` to stderr, exit code.
- `_translate_yt_dlp_error(exc)` — port `_ERROR_RULES` from omni-transcriber downloader.py: map "private video", "members-only", "sign in", "rate-limit", "geo-blocked", "unsupported url" → message + hint (English, tooling convention), hint suggests `--cookies-from-browser`.

### `commands/`
- `transcript.py`: loop URLs, `Progress` rich bar per video (download / transcribe %), end summary.
- `batch.py`: read file, filter comments/blanks, reuse transcript pipeline.
- `info.py`, `doctor.py` in phase 2+.

---

## 7. Repo layout

```
tiktok_cli/
├── PLAN.md                  # this file
├── README.md
├── pyproject.toml           # uv/pip, entry point `tiktok`
├── src/tiktok_cli/
│   ├── __init__.py          # __version__
│   ├── cli.py               # Typer app root, subcommand registration
│   ├── core/
│   │   ├── url.py
│   │   ├── downloader.py
│   │   ├── captions.py
│   │   ├── stt.py
│   │   ├── artifacts.py
│   │   ├── errors.py
│   │   └── discovery.py     # phase 2
│   └── commands/
│       ├── transcript.py
│       ├── batch.py
│       ├── info.py          # phase 2
│       ├── search.py        # phase 2
│       └── doctor.py
├── tests/
│   ├── conftest.py          # fixtures: sample .vtt, fake yt-dlp info json
│   ├── test_captions.py     # parse_vtt, dedupe, pick_caption — pure, no network
│   ├── test_url.py          # classify_url
│   ├── test_artifacts.py    # layout, idempotency
│   ├── test_stt.py          # engine selection logic (mocked)
│   └── fixtures/
│       ├── sample.vtt
│       ├── tiktok_info.json
│       └── urls.txt
└── .github/workflows/ci.yml # lint (ruff) + pytest (no-network tests only)
```

`pyproject.toml` deps:
```toml
dependencies = [
  "typer>=0.12", "rich>=13.7",
  "yt-dlp>=2025.1",           # floor pin, no floating latest
  "faster-whisper>=1.1",      # ctranslate2>=4.6.3 floor for new GPUs (omni-transcriber lesson)
]
[project.optional-dependencies]
mlx = ["mlx-whisper>=0.4"]    # Apple Silicon only
```

No torch, no openai-whisper, no pydub — lean like omni-transcriber.

---

## 8. Implementation roadmap (phases)

### Phase 0 — scaffold (small)
- pyproject, cli.py with `transcript` stub, `doctor` checking yt-dlp/ffmpeg.
- `uv sync` works, `tiktok --help` < 100ms.

### Phase 1 — caption path (no Whisper)
- downloader.list_subtitles + download_subs
- captions.parse_vtt/pick/dedupe/render
- artifacts layout + index.jsonl
- `tiktok transcript <url>` end-to-end with a captioned video → verify on 1 real Vietnamese + 1 English video.
- Tests: parse_vtt fixtures, url classify, artifacts.

### Phase 2 — Whisper fallback
- stt.py faster + mlx engines
- audio download path
- `--whisper/--engine/--model` flags
- Test on a no-caption video; benchmark `small` vs `turbo`.

### Phase 3 — batch + hardening
- `tiktok batch`, multi-URL, summary table
- full error translation, retry/WAF hints
- `--cookies-from-browser` path
- README: install (uv tool install), usage, limitations (private/WAF/no-caption coverage), model benchmark table.

### Phase 4 — discovery (optional, `tt`-dependent)
- `tiktok info`, `list`, `search`, `tag`, `trending`, `discover`
- `core/discovery.py` wraps `tt` subprocess → JSONL parse
- doctor checks `tt`
- **Gate**: only after MVP is stable; search depends on WAF — document "best effort".

### Phase 5 — nice-to-have (consider, not committed)
- `--screen` OCR keyframes (tiktok-extractor approach: ffmpeg scene detect + tesseract).
- `--llm` markdown output (omni-transcriber `_llm_body`: timestamped ~150-word paragraphs).
- `--jobs N` parallel (omni-transcriber pipeline: fetch queue + transcribe queue, memory-aware).
- `tiktok digest` — read index.jsonl → summary of processed videos.

---

## 9. Test plan

**Unit (no network, CI-safe):**
- `parse_vtt`: cue parsing, `<c>` tags, duplicate removal, timestamp format.
- `classify_url`: all TikTok URL kinds.
- `pick_caption`: preference order vie > en > auto.
- `render_*`: golden files txt/srt/vtt/json/md.
- `is_processed` / index append.
- `_translate_yt_dlp_error`: mock exceptions → messages.

**Integration (manual, needs network + TikTok):**
- 1 Vietnamese captioned video → caption path.
- 1 English captioned video.
- 1 no-caption video → whisper path, check `small` vs `turbo` quality.
- 1 vm.tiktok.com shortlink.
- 1 private video → graceful failure.
- Batch of 10 URLs → correct summary.

**MVP acceptance:** `tiktok transcript <any public TikTok URL>` → artifact folder with all 5 formats + metadata.json + index.jsonl entry, ≤2 min for a <3-min video on Apple Silicon.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| yt-dlp TikTok extractor breaks (TikTok changes API often) | Pin `yt-dlp` floor, `tiktok doctor` reports version, docs for `uv tool install --force` upgrade; caption path dies with it — accepted, that's scraping reality |
| Whisper hallucination on music/noise | `condition_on_previous_text=False` + VAD + no_speech_prob filter (douyin-teardown recipe); document `--whisper never` for captions-only users |
| Vietnamese quality of `small` insufficient | Benchmark on real videos; default may move to `turbo` (1.6GB, ~large-v3 quality, fast) — decide after testing |
| faster-whisper vs mlx-whisper wrong choice | `--engine` flag override; auto is only the default |
| `tt` binary search hit by WAF | Phase 4 gate; document "best effort"; SSR plane sturdier than API plane — `tt video` less risky than `tt search` |
| ffmpeg missing on user machine | faster-whisper/PyAV decodes directly → ffmpeg **not required**; doctor only warns |

---

## 11. Locked decisions

1. **Default model**: `small` (~466MB) for faster-whisper; mlx → `mlx-community/whisper-small-mlx`. README documents upgrading to `turbo`/`large-v3-turbo`.
2. **Audio**: deleted after transcribe; `--keep-audio` opt-in.
3. **Output dir**: `./tiktok-transcripts` cwd-relative; `-o` override.
4. **Discovery**: build **all** — `info`, `list`, `search`, `tag`, `trending`, `discover` via `tt` binary in v1 (still optional dep, degrades gracefully without `tt`).
