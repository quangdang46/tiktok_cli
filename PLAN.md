# tiktok-cli — Plan chi tiết

> Video → Transcript CLI. Không login TikTok, không LLM bên trong, transcript chạy local.
> Agent (Claude Code / Codex / Devin) gọi CLI này rồi tự đọc file kết quả.

---

## 1. Mục tiêu & phạm vi

### MVP (bắt buộc)

| # | Feature | Ghi chú |
|---|---------|---------|
| F1 | `tiktok transcript <url>` | URL → audio/caption → `transcript.txt/.srt/.vtt/.json/.md` |
| F2 | Caption-first | TikTok caption track có sẵn → dùng luôn, không chạy Whisper |
| F3 | Whisper fallback | Không có caption → faster-whisper (cross-platform) / mlx-whisper (Apple Silicon) |
| F4 | `tiktok transcript <url1> <url2> ...` | Multi-URL, mỗi video 1 thư mục |
| F5 | `tiktok batch <file>` | Đọc list URL từ file, `#` comment, skip đã có transcript |
| F6 | Không login, không cookies mặc định | `--cookies-from-browser` / `--cookies` là optional flag |

### Phase 2 (sau MVP, optional)

| # | Feature | Nguồn |
|---|---------|-------|
| F7 | `tiktok info <url>` | Metadata: views/likes/comments/uploader/upload_date — yt-dlp `--dump-single-json` + `--list-subs` |
| F8 | `tiktok list <@user>` | Videos của 1 kênh — yt-dlp flat-playlist hoặc `tt posts` |
| F9 | `tiktok search <keyword>` | Discovery — gọi `tt` binary (tamnd/tiktok-cli) hoặc yt-dlp search fallback |
| F10 | `tiktok discover` | Graph walk — `tt discover` |
| F11 | `tiktok tag <hashtag>` | Videos theo hashtag — `tt hashtag --videos` |
| F12 | `tiktok trending` | `tt trending` |
| F13 | `tiktok status` / `doctor` | Check yt-dlp, ffmpeg, whisper model, `tt` binary |

### Không làm (explicitly out of scope)

- Không LLM integration trong CLI (agent ở ngoài gọi).
- Không dashboard/web UI.
- Không database — filesystem artifacts là source of truth.
- Không TikTok login flow, không session management (chỉ optional cookie passthrough).
- Không OCR/frames (Phase 3+, tham khảo `tiktok-extractor`).

---

## 2. Tech stack

| Layer | Chọn | Lý do |
|-------|------|-------|
| Language | **Python 3.11+** | Toàn bộ reference repo đều Python; dễ gọi từ agent; yt-dlp/whisper đều là Python-first |
| CLI framework | **Typer + Rich** | `omni-transcriber`, `gerardnico/transcribe`, `tiktok-extractor` đều dùng; rich progress bar |
| Package manager | **uv** (PEP 723 optional) | `transcript.py` (jadenmaciel) pattern `uv run` zero-install; `uv tool install` cho global |
| Download/subtitle | **yt-dlp** (library API `yt_dlp.YoutubeDL`, không subprocess trừ khi cần) | Tất cả repo đều dùng; Python API cho control tốt hơn CLI flags |
| Audio extract | **ffmpeg** subprocess (chỉ khi cần Whisper path; caption path không cần) | `faster-whisper` dùng PyAV decode trực tiếp — **có thể bỏ ffmpeg hoàn toàn** nếu chọn faster-whisper cho mọi audio |
| STT engine | **faster-whisper** mặc định; **mlx-whisper** auto-detect trên Apple Silicon | `douyin-teardown` pattern dual-backend; faster-whisper pip install, không compile; mlx ~15x realtime trên M-series |
| Discovery (Phase 2) | **`tt` binary** (tamnd/tiktok-cli, Go) gọi subprocess, optional dependency | Không login; X-Bogus signing + SSR parse đã implement sẵn; không port sang Python |

**Quyết định then chốt: dùng faster-whisper thay whisper.cpp.**
Lý do: (1) `pip install` không cần cmake/compile; (2) PyAV decode trực tiếp mọi container → bỏ bước ffmpeg extract; (3) int8 CPU đủ nhanh cho TikTok video ngắn; (4) whisper.cpp chỉ thắng ở Apple Silicon nếu dùng CoreML — mlx-whisper cover case đó tốt hơn.

---

## 3. Kiến trúc

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

### Nguyên tắc thiết kế (rút từ research)

1. **Caption-first, Whisper-fallback** — học từ `dedene/skills` + `gerardnico/transcribe`. TikTok auto-caption cover phần lớn video → tiết kiệm 90% compute.
2. **yt-dlp subtleties đã biết** (quan trọng, ghi vào code comment):
   - Caption info **không** có trong `extract_info` JSON → phải gọi `--list-subs` hoặc download subs riêng (dedene/skills ghi rõ gotcha này).
   - `--write-subs --write-auto-subs --sub-format vtt --sub-langs "vi.*,en.*,all"`.
   - Format select: `bestaudio/best` cho audio-only; nếu cần video (phase 3 OCR) dùng `best[vcodec=h264]` — bytevc1/h265 hay video-only (tiktok-extractor, tiktok-transcript đều ghi).
   - Shortlink `vm./vt.tiktok.com` → yt-dlp tự resolve; nhưng video_id lấy từ `info["id"]`, không parse từ URL.
3. **stdout chỉ transcript/plain output; mọi log → stderr** (omni-transcriber hard constraint) → agent pipe được.
4. **Idempotent**: `transcript.json` đã tồn tại + `--no-refresh` → skip (tiktok-extractor pattern).
5. **Lazy import**: faster-whisper/model chỉ load khi thật sự cần transcribe — `tiktok --help` < 100ms (omni-transcriber).
6. **Anti-hallucination STT settings** (douyin-teardown): `condition_on_previous_text=False`, `vad_filter=True`, `beam_size=1`, `temperature=0`.

---

## 4. Output layout

```
tiktok-transcripts/                  # --output-dir, default ./tiktok-transcripts
├── VIDEO_ID/                        # yt-dlp info["id"], sanitize [A-Za-z0-9_-]
│   ├── source.info.json             # raw yt-dlp info (chỉ ghi lần đầu)
│   ├── metadata.json                # compact: title, uploader, duration, counts, url
│   ├── subs/                        # raw caption files yt-dlp tải về
│   │   └── VIDEO_ID.vie.vtt ...
│   ├── audio.wav                    # chỉ khi whisper path (16k mono nếu ffmpeg; raw nếu PyAV)
│   ├── transcript.vtt               # canonical timestamped (caption hoặc whisper)
│   ├── transcript.srt
│   ├── transcript.txt               # plain text, no timestamp — cho agent đọc
│   ├── transcript.json              # [{start,end,text,confidence?}]
│   ├── transcript.md                # # title + metadata + [mm:ss] cues
│   └── whisper.log                  # debug khi fallback
├── batch-2026-11-24/                # optional: batch run gom vào 1 dir
└── index.jsonl                      # append-only log mọi video đã xử lý
```

`index.jsonl` record: `{video_id, url, status: caption|whisper|no-captions|failed, language, cue_count, duration, processed_at, artifact_dir}` — cho `tiktok list`/digest sau này mà không cần DB.

---

## 5. Command spec chi tiết

### `tiktok transcript <urls...>`

```
tiktok transcript https://www.tiktok.com/@user/video/123

tiktok transcript url1 url2 url3          # sequential

Options:
  -o, --output-dir DIR        default ./tiktok-transcripts
  -m, --model NAME            whisper model: tiny|base|small|turbo|large-v3-turbo
                              default: small (faster) / mlx-community/whisper-large-v3-turbo (mlx)
  -l, --language LANG         whisper language hint; auto-detect mặc định
  --whisper auto|always|never auto = chỉ whisper khi không caption (DEFAULT)
                              always = bỏ caption, ép whisper
                              never = chỉ caption, video không caption → status no-captions
  --engine auto|faster|mlx    auto = mlx trên Apple Silicon, faster còn lại
  --format FMT                txt|srt|vtt|json|md|all   default all
  --keep-audio                giữ audio.wav (default xóa sau transcribe)
  --refresh                   bỏ cache, fetch lại subs/audio + transcribe lại
  --cookies-from-browser B    firefox|chrome|safari... (optional)
  --cookies FILE              Netscape cookies.txt (optional)
  -v, --verbose               stderr debug
```

Flow mỗi URL:

```
1. normalize url → yt_dlp extract_info(download=False) → video_id, metadata
2. check cache: transcript.json tồn tại & !refresh → print path, done
3. CAPTION PATH:
   yt_dlp download subs only:
     --skip-download --write-subs --write-auto-subs --sub-format vtt
     --sub-langs "vi.*,en.*,vi,en,all" -o subs/%(id)s.%(ext)s
   → tìm file .vtt ưu tiên: vie > vie-* > en > auto-generated > bất kỳ
   → parse VTT → cues[{start,end,text}]
   → render tất cả formats → transcript_source="tiktok-captions:<lang>"
4. WHISPER PATH (nếu không caption và --whisper != never):
   yt_dlp download bestaudio → temp file
   faster-whisper transcribe (hoặc mlx_whisper.transcribe)
   → segments → cues → render formats → transcript_source="whisper:<model>:<lang>"
   → xóa audio trừ --keep-audio
5. ghi metadata.json + append index.jsonl + print compact summary ra stdout
```

Edge cases đã biết (xử lý trong code):
- Video không có audio track → `status: no-audio`, vẫn xuất metadata.
- Photo/slideshow post (`imagePost`) → `status: photo-post`, skip sớm.
- Private/deleted/age-gated → yt-dlp raise → `status: failed`, ghi reason vào index.
- WAF/rate-limit → retry 1 lần sau 5s, rồi failed với hint `--cookies-from-browser`.
- Caption file có cue trùng lặp liên tiếp (TikTok auto-caption hay lặp) → dedupe trong parse_vtt.
- `vm./vt.` shortlink → resolve qua yt-dlp, không tự parse.

### `tiktok batch <file>`

```
tiktok batch urls.txt [-o DIR] [--whisper auto] [same flags as transcript]

urls.txt format:
  # comment line
  https://www.tiktok.com/@a/video/111
  https://vm.tiktok.com/XYZ
  
→ sequential (MVP), parallel --jobs N ở phase 2 nếu cần
→ per-video try/except, không chết cả batch vì 1 URL fail
→ cuối batch in summary table: ok / caption / whisper / failed counts
```

### `tiktok info <url>` (phase 2)

Metadata only, `--dump-single-json` + `--list-subs`, output JSON ra stdout. Nhanh, không download.

### `tiktok search|discover|list|tag|trending` (phase 2)

Wrapper gọi `tt` binary (optional dep, `tiktok doctor` check). Output của `tt` là JSONL → parse → in table. Nếu `tt` không có → fallback yt-dlp hashtag search nếu có, không thì báo rõ "install tt".

### `tiktok doctor`

Check: yt-dlp version, ffmpeg (warn nếu thiếu — chỉ cần cho 1 số edge), faster-whisper import, mlx-whisper (nếu arm64), model đã cache chưa, `tt` binary (phase 2), network tới tiktok.com. Output bảng pass/fail + fix hint.

---

## 6. Module spec

### `core/url.py`
- `classify_url(url) -> Video|Photo|Profile|Feed|Short|Other` — regex path `/@user/video/(\d+)`, `/photo/`, host `vm./vt.` (học `tiktok-transcript/lib/tiktok.js`).
- Không parse video_id từ shortlink — để yt-dlp resolve.

### `core/downloader.py`
- `YtdlpClient` wrap `yt_dlp.YoutubeDL`:
  - `extract_info(url, download=False)`
  - `list_subtitles(url) -> {lang: [formats]}` — workaround gotcha caption không có trong info JSON: gọi với `--list-subs`-equivalent qua `writesubtitles`... **thực tế**: caption TikTok lấy được qua `info["subtitles"]`/`automatic_captions` chỉ khi `extract_info` có `writesubtitles=True`; verify bằng test thực tế, fallback subprocess `yt-dlp --list-subs`.
  - `download_subs(url, out_dir, langs)` → list Path .vtt
  - `download_audio(url, tmp_dir)` → Path
  - `download_video_h264(url, out_dir)` (phase 3)
- YDL opts chung: `quiet`, `no_warnings`, `noplaylist`, `socket_timeout=30`, `retries=3`, `js_runtimes` enable deno/node nếu có (học omni-transcriber `_enabled_js_runtimes` — YouTube cần, TikTok ít nhưng harmless).
- Cookies: `cookiesfrombrowser`/`cookiefile` chỉ khi flag truyền.

### `core/captions.py`
- `parse_vtt(path) -> list[Cue{start,end,start_time,end_time,text}]` — port gần nguyên từ dedene/skills `parse_vtt` + `strip_vtt_markup` (xử lý `<c>`, `<00:00:00.000>`, `\h`, html entities).
- `pick_caption(candidates, preference=["vie","vi","en","en-US"])` — ưu tiên: manual sub > auto sub; vie > en > first.
- `dedupe_cues(cues)` — bỏ cue text trùng liên tiếp (auto-caption hay lặp).
- `cues_to_paragraphs(cues, gap_threshold=2.0)` — gộp cue → đoạn văn cho txt/md.

### `core/stt.py`
- `TranscribeEngine` protocol: `transcribe(audio_path, language) -> list[Cue]`.
- `FasterWhisperEngine`: `WhisperModel(model, device="auto", compute_type="auto")`, cache per (model,device). Settings: `vad_filter=True`, `condition_on_previous_text=False`, `beam_size=1`, `temperature=0`.
- `MlxEngine` (darwin/arm64 only): `mlx_whisper.transcribe(path_or_hf_repo=..., language=...)`.
- `resolve_engine(auto)` → mlx nếu `platform.machine()=="arm64"` và import được, else faster.
- Model map: `small` → faster `small`; mlx `small` → `mlx-community/whisper-small-mlx` (map table từ douyin-teardown `_MLX_MODEL_MAP`).

### `core/artifacts.py`
- `VideoDir(video_id)` path builder, `is_processed()`, `write_outputs(cues, meta, source)`, `append_index(record)`.
- Filename sanitize: `[^
A-Za-z0-9_-]` → strip; video_id từ yt-dlp đã safe nhưng vẫn validate `^[\w-]{6,}$`.

### `core/errors.py`
- `UserError(msg, hint, exit_code)` → print `error: msg\nhint: ...` stderr, exit code.
- `_translate_yt_dlp_error(exc)` — port `_ERROR_RULES` từ omni-transcriber downloader.py: map "private video", "members-only", "sign in", "rate-limit", "geo-blocked", "unsupported url" → message + hint tiếng Anh/Việt? **→ English** (tooling convention), hint gợi ý `--cookies-from-browser`.

### `commands/`
- `transcript.py`: loop URLs, `Progress` rich bar per video (download / transcribe %), summary cuối.
- `batch.py`: đọc file, filter comment/blank, reuse transcript pipeline.
- `info.py`, `doctor.py` phase 2.

---

## 7. Cấu trúc repo

```
tiktok_cli/
├── PLAN.md                  # file này
├── README.md
├── pyproject.toml           # uv/pip, entry point `tiktok`
├── src/tiktok_cli/
│   ├── __init__.py          # __version__
│   ├── cli.py               # Typer app root, subcommand register
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
│   ├── test_stt.py          # engine selection logic (mock)
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
  "yt-dlp>=2025.1",           # pin floor, không floating latest
  "faster-whisper>=1.1",      # ctranslate2 floor >=4.6.3 cho GPU mới (bài học omni-transcriber)
]
[project.optional-dependencies]
mlx = ["mlx-whisper>=0.4"]    # chỉ cài trên Apple Silicon
```

Không torch, không openai-whisper, không pydub — lean như omni-transcriber.

---

## 8. Lộ trình implement (phases)

### Phase 0 — scaffold (nhỏ)
- pyproject, cli.py với `transcript` stub, `doctor` check yt-dlp/ffmpeg.
- `uv sync` chạy được, `tiktok --help` < 100ms.

### Phase 1 — caption path (không Whisper)
- downloader.list_subtitles + download_subs
- captions.parse_vtt/pick/dedupe/render
- artifacts layout + index.jsonl
- `tiktok transcript <url>` end-to-end với video CÓ caption → verify trên 1 video tiếng Việt + 1 tiếng Anh thật.
- Tests: parse_vtt fixtures, url classify, artifacts.

### Phase 2 — Whisper fallback
- stt.py faster + mlx engines
- audio download path
- `--whisper/--engine/--model` flags
- Test trên video KHÔNG caption (tìm video cũ/không bật auto-caption).

### Phase 3 — batch + hardening
- `tiktok batch`, multi-URL, summary table
- error translation đầy đủ, retry/WAF hint
- `--cookies-from-browser` path
- README: install (uv tool install), usage, limitations (private/WAF/no-caption coverage), benchmark table model.

### Phase 4 — discovery (optional, `tt`-dependent)
- `tiktok info`, `list`, `search`, `tag`, `trending`, `discover`
- `core/discovery.py` wrap `tt` subprocess → JSONL parse
- doctor check `tt`
- **Gate**: chỉ làm sau khi MVP stable; search phụ thuộc WAF — document rõ "best effort".

### Phase 5 — nice-to-have (cân nhắc, chưa commit)
- `--screen` OCR keyframes (tiktok-extractor approach: ffmpeg scene detect + tesseract).
- `--llm` markdown output (omni-transcriber `_llm_body`: timestamped paragraphs ~150 words).
- `--jobs N` parallel (omni-transcriber pipeline pattern: fetch queue + transcribe queue, memory-aware).
- `tiktok digest` — đọc index.jsonl → summary các video đã xử lý.

---

## 9. Test plan

**Unit (no network, CI chạy được):**
- `parse_vtt`: cue parsing, `<c>` tags, duplicate removal, timestamp format.
- `classify_url`: mọi loại URL TikTok.
- `pick_caption`: preference order vie > en > auto.
- `render_*`: golden files txt/srt/vtt/json/md.
- `is_processed` / index append.
- `_translate_yt_dlp_error`: mock exceptions → messages.

**Integration (manual, cần network + TikTok):**
- 1 video tiếng Việt có caption → caption path.
- 1 video tiếng Anh có caption.
- 1 video không caption → whisper path, check chất lượng `small` vs `turbo`.
- 1 shortlink vm.tiktok.com.
- 1 private video → failed gracefully.
- Batch 10 URL → summary đúng.

**Acceptance MVP:** `tiktok transcript <bất kỳ public TikTok URL nào>` → folder artifacts đủ 5 format + metadata.json + index.jsonl entry, trong ≤2 phút cho video <3 phút trên M-series.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| yt-dlp TikTok extractor gãy (TikTok đổi API thường xuyên) | Pin `yt-dlp` floor, `tiktok doctor` báo version, docs hướng dẫn `uv tool install --force` upgrade; caption path vẫn có thể chết cùng nhau — chấp nhận, đây là bản chất scraping |
| Whisper hallucination trên audio nhạc/noise | `condition_on_previous_text=False` + VAD + no_speech_prob filter (douyin-teardown recipe); document `--whisper never` cho ai chỉ muốn caption |
| Vietnamese quality của `small` không đủ | Benchmark trên video thật; default có thể nâng `turbo` (1.6GB, chất lượng ~large-v3, nhanh) — quyết sau test |
| faster-whisper vs mlx-whisper chọn sai | `--engine` flag override; auto chỉ là default |
| `tt` binary search bị WAF | Phase 4 gate; document "best effort"; SSR plane bền hơn API plane — `tt video` ít risk hơn `tt search` |
| ffmpeg thiếu trên máy user | faster-whisper/PyAV decode trực tiếp → ffmpeg **không bắt buộc**; chỉ warn trong doctor |

---

## 11. Quyết định đã chốt

1. **Model default**: `small` (~466MB) cho faster-whisper; mlx → `mlx-community/whisper-small-mlx`. README ghi cách nâng `turbo`/`large-v3-turbo`.
2. **Audio**: xóa sau transcribe; `--keep-audio` opt-in.
3. **Output dir**: `./tiktok-transcripts` cwd-relative; `-o` override.
4. **Discovery**: làm **tất cả** — `info`, `list`, `search`, `tag`, `trending`, `discover` qua `tt` binary trong v1 (vẫn optional dependency, degrade gracefully khi thiếu `tt`).
