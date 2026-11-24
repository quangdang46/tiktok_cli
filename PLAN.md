# tiktok-cli — Kế hoạch chi tiết

> TikTok video → transcript CLI. Không login TikTok, không tích hợp LLM,
> phiên âm chạy local.
> Agent (Claude Code / Codex / Devin) gọi CLI này, rồi tự đọc file output.

---

## 1. Mục tiêu & phạm vi

### MVP (bắt buộc)

| # | Tính năng | Ghi chú |
|---|-----------|---------|
| F1 | `tiktok transcript <url>` | URL → audio/phụ đề → `transcript.txt/.srt/.vtt/.json/.md` |
| F2 | Ưu tiên phụ đề | Dùng track phụ đề có sẵn của TikTok khi có — bỏ qua Whisper hoàn toàn |
| F3 | Whisper dự phòng | Không có phụ đề → faster-whisper (đa nền tảng) / mlx-whisper (Apple Silicon) |
| F4 | `tiktok transcript <url1> <url2> ...` | Nhiều URL, mỗi video một thư mục |
| F5 | `tiktok batch <file>` | Đọc danh sách URL từ file, comment `#`, bỏ qua video đã có transcript |
| F6 | Không login, không cookie mặc định | `--cookies-from-browser` / `--cookies` chỉ là flag tuỳ chọn |

### Phase 2 (sau MVP, tuỳ chọn)

| # | Tính năng | Nguồn |
|---|-----------|--------|
| F7 | `tiktok info <url>` | Metadata: views/likes/comments/uploader/upload_date — yt-dlp `--dump-single-json` + `--list-subs` |
| F8 | `tiktok list <@user>` | Video từ một kênh — yt-dlp flat-playlist hoặc `tt posts` |
| F9 | `tiktok search <keyword>` | Khám phá — gọi binary `tt` (tamnd/tiktok-cli) hoặc fallback yt-dlp |
| F10 | `tiktok discover` | Duyệt đồ thị — `tt discover` |
| F11 | `tiktok tag <hashtag>` | Video theo hashtag — `tt hashtag --videos` |
| F12 | `tiktok trending` | `tt trending` |
| F13 | `tiktok doctor` | Kiểm tra yt-dlp, ffmpeg, model whisper, binary `tt` |

### Ngoài phạm vi (explicitly out of scope)

- Không tích hợp LLM trong CLI (agent nằm ngoài, tự đọc file).
- Không dashboard/web UI.
- Không database — artifact trên filesystem là source of truth.
- Không flow login TikTok hay quản lý session (chỉ passthrough cookie tuỳ chọn).
- Không OCR/frame (Phase 3+, tham khảo `tiktok-extractor`).

---

## 2. Tech stack

| Tầng | Lựa chọn | Vì sao |
|------|----------|--------|
| Ngôn ngữ | **Python 3.11+** | Mọi repo tham khảo đều Python; thân thiện agent; yt-dlp/whisper ưu tiên Python |
| CLI framework | **Typer + Rich** | Được `omni-transcriber`, `gerardnico/transcribe`, `tiktok-extractor` dùng; progress bar đẹp |
| Package manager | **uv** (PEP 723 tuỳ chọn) | Pattern `uv run` zero-install (jadenmaciel/transcript); `uv tool install` cho bản global |
| Download/phụ đề | **yt-dlp** (Python API `yt_dlp.YoutubeDL`, chỉ subprocess khi cần) | Mọi repo tham khảo đều dùng; Python API cho lỗi có cấu trúc thay vì parse text CLI |
| Tách audio | **ffmpeg** subprocess (chỉ khi cần; faster-whisper decode trực tiếp qua PyAV) | PyAV bundled của faster-whisper xử lý mp4/mkv/mp3 — **có thể không cần ffmpeg chút nào** |
| STT engine | **faster-whisper** mặc định; **mlx-whisper** tự detect trên Apple Silicon | pattern dual-backend của douyin-teardown; faster-whisper cài bằng pip, không compile; mlx nhanh ~15x realtime trên M-series |
| Khám phá (Phase 2) | Binary **`tt`** (tamnd/tiktok-cli, Go) qua subprocess, dep tuỳ chọn | Hoạt động không cần login; đã có X-Bogus signing + SSR parsing; không port sang Python |

**Quyết định chính: faster-whisper thay vì whisper.cpp.**
Lý do: (1) `pip install`, không cần cmake/compile; (2) PyAV decode container trực tiếp → không cần bước extract ffmpeg; (3) int8 CPU đủ nhanh cho video TikTok ngắn; (4) whisper.cpp chỉ thắng trên Apple Silicon với CoreML — mlx-whisper cover tốt hơn.

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

### Nguyên tắc thiết kế (từ research)

1. **Ưu tiên phụ đề, Whisper dự phòng** — từ `dedene/skills` + `gerardnico/transcribe`. Đa số TikTok có auto-caption → tiết kiệm ~90% compute.
2. **Các điểm yt-dlp dễ sai đã biết** (quan trọng, giữ làm comment trong code):
   - Thông tin phụ đề **không** xuất hiện trong JSON `extract_info` của TikTok → phải gọi `--list-subs` hoặc tải subs riêng (dedene/skills ghi nhận gotcha này).
   - `--write-subs --write-auto-subs --sub-format vtt --sub-langs "vi.*,en.*,all"`.
   - Format select: `bestaudio/best` cho audio-only; nếu cần video (OCR phase 3) dùng `best[vcodec=h264]` — bytevc1/h265 thường chỉ có video không audio (ghi nhận trong tiktok-extractor, tiktok-transcript).
   - Shortlink `vm./vt.tiktok.com` → yt-dlp tự resolve; lấy video_id từ `info["id"]`, không bao giờ parse URL.
3. **stdout chỉ chứa transcript/plain output; mọi log → stderr** (ràng buộc cứng kiểu omni-transcriber) → agent pipe an toàn.
4. **Idempotent**: `transcript.json` đã tồn tại + không `--refresh` → skip (pattern tiktok-extractor).
5. **Lazy import**: faster-whisper/model chỉ load khi thật sự phiên âm — `tiktok --help` < 100ms (omni-transcriber).
6. **Cấu hình STT chống hallucination** (douyin-teardown): `condition_on_previous_text=False`, `vad_filter=True`, `beam_size=1`, `temperature=0`.

---

## 4. Layout output

```
tiktok-transcripts/                  # --output-dir, mặc định ./tiktok-transcripts
├── VIDEO_ID/                        # yt-dlp info["id"], sanitize [A-Za-z0-9_-]
│   ├── source.info.json             # info yt-dlp thô (ghi một lần)
│   ├── metadata.json                # gọn: title, uploader, duration, counts, url
│   ├── subs/                        # file phụ đề thô từ yt-dlp
│   │   └── VIDEO_ID.vie.vtt ...
│   ├── audio.wav                    # chỉ đường whisper (16k mono nếu ffmpeg; raw nếu PyAV)
│   ├── transcript.vtt               # canonical có timestamp (phụ đề hoặc whisper)
│   ├── transcript.srt
│   ├── transcript.txt               # plain text, không timestamp — thứ agent đọc
│   ├── transcript.json              # [{start,end,text,confidence?}]
│   ├── transcript.md                # # title + metadata + cue [mm:ss]
│   └── whisper.log                  # debug ở đường fallback
├── batch-2026-11-24/                # tuỳ chọn: gom một lần chạy batch vào một thư mục
└── index.jsonl                      # log append-only của mọi video đã xử lý
```

Record `index.jsonl`: `{video_id, url, status: caption|whisper|no-captions|failed, language, cue_count, duration, processed_at, artifact_dir}` — cho phép `tiktok list`/digest sau này mà không cần DB.

---

## 5. Spec lệnh (chi tiết)

### `tiktok transcript <urls...>`

```
tiktok transcript https://www.tiktok.com/@user/video/123

tiktok transcript url1 url2 url3          # tuần tự

Options:
  -o, --output-dir DIR        mặc định ./tiktok-transcripts
  -m, --model NAME            model whisper: tiny|base|small|turbo|large-v3-turbo
                              mặc định: small (faster) / mlx-community/whisper-large-v3-turbo (mlx)
  -l, --language LANG         gợi ý ngôn ngữ whisper; mặc định tự detect
  --whisper auto|always|never auto = whisper chỉ khi không có phụ đề (MẶC ĐỊNH)
                              always = bỏ qua phụ đề, ép whisper
                              never = chỉ phụ đề; video không phụ đề -> status no-captions
  --engine auto|faster|mlx    auto = mlx trên Apple Silicon, faster còn lại
  --format FMT                txt|srt|vtt|json|md|all   mặc định all
  --keep-audio                giữ audio.wav (mặc định: xoá sau khi transcribe)
  --refresh                   bỏ cache, tải lại subs/audio + phiên âm lại
  --cookies-from-browser B    firefox|chrome|safari... (tuỳ chọn)
  --cookies FILE              cookies.txt Netscape (tuỳ chọn)
  -v, --verbose               debug ra stderr
```

Flow từng URL:

```
1. chuẩn hoá url → yt_dlp extract_info(download=False) → video_id, metadata
2. kiểm tra cache: transcript.json đã có & !refresh → in path, xong
3. ĐƯỜNG PHỤ ĐỀ:
   yt_dlp chỉ tải subs:
     --skip-download --write-subs --write-auto-subs --sub-format vtt
     --sub-langs "vi.*,en.*,vi,en,all" -o subs/%(id)s.%(ext)s
   → tìm .vtt ưu tiên: vie > vie-* > en > auto-generated > bất kỳ
   → parse VTT → cues[{start,end,text}]
   → render mọi định dạng → transcript_source="tiktok-captions:<lang>"
4. ĐƯỜNG WHISPER (nếu không có phụ đề và --whisper != never):
   yt_dlp tải bestaudio → file temp
   faster-whisper transcribe (hoặc mlx_whisper.transcribe)
   → segments → cues → render định dạng → transcript_source="whisper:<model>:<lang>"
   → xoá audio trừ khi --keep-audio
5. ghi metadata.json + append index.jsonl + in tóm tắt gọn ra stdout
```

Edge case cần xử lý trong code:
- Video không có track audio → `status: no-audio`, vẫn xuất metadata.
- Photo/slideshow post (`imagePost`) → `status: photo-post`, skip sớm.
- Private/đã xoá/giới hạn tuổi → yt-dlp raise → `status: failed`, lý do vào index.
- WAF/rate-limit → retry một lần sau 5s, rồi fail kèm gợi ý `--cookies-from-browser`.
- File phụ đề có cue trùng liên tiếp (auto-caption TikTok lặp) → dedupe khi parse_vtt.
- Shortlink `vm./vt.` → yt-dlp tự resolve; không parse ID thủ công.

### `tiktok batch <file>`

```
tiktok batch urls.txt [-o DIR] [--whisper auto] [cùng flag như transcript]

Định dạng urls.txt:
  # dòng comment
  https://www.tiktok.com/@a/video/111
  https://vm.tiktok.com/XYZ

→ tuần tự (MVP); song song --jobs N ở phase 2+ nếu cần
→ try/except từng video — một URL hỏng không giết cả batch
→ bảng tổng kết cuối batch: đếm ok / caption / whisper / failed
```

### `tiktok info <url>` (phase 2)

Chỉ metadata qua `--dump-single-json` + `--list-subs`; JSON ra stdout. Nhanh, không tải.

### `tiktok search|discover|list|tag|trending` (phase 2)

Wrapper gọi binary `tt` (dep tuỳ chọn, `tiktok doctor` kiểm tra). `tt` xuất JSONL → parse → in bảng. Không có `tt` → lỗi rõ "cài tt"; transcript/batch không ảnh hưởng.

### `tiktok doctor`

Kiểm tra: phiên bản yt-dlp, ffmpeg (chỉ cảnh báo — không bắt buộc), import faster-whisper, mlx-whisper (nếu arm64), model đã cache?, binary `tt` (phase 2), mạng tới tiktok.com, thư mục output ghi được. Bảng PASS/WARN/FAIL + gợi ý fix.

---

## 6. Spec module

### `core/url.py`
- `classify_url(url) -> Video|Photo|Profile|Feed|Short|Other` — regex path `/@user/video/(\d+)`, `/photo/`, host `vm./vt.` (từ `tiktok-transcript/lib/tiktok.js`).
- Không bao giờ parse video_id từ shortlink — để yt-dlp resolve.

### `core/downloader.py`
- `YtdlpClient` bọc `yt_dlp.YoutubeDL`:
  - `extract_info(url, download=False)`
  - `list_subtitles(url) -> {lang: [formats]}` — workaround gotcha phụ đề: chạy tương đương `--list-subs` hoặc tải subs vào temp dir; đừng tin `info["subtitles"]` một mình với TikTok.
  - `download_subtitles(url, out_dir, langs)` → list[Path] .vtt
  - `download_audio(url, tmp_dir)` → Path
  - `download_video_h264(url, out_dir)` (phase 3)
- YDL opts chung: `quiet`, `no_warnings`, `noplaylist`, `socket_timeout=30`, `retries=3`, `js_runtimes` bật deno/node nếu có (omni-transcriber `_enabled_js_runtimes` — cần cho YouTube, vô hại với TikTok).
- Cookies: opt `cookiesfrombrowser`/`cookiefile` chỉ khi truyền flag.

### `core/captions.py`
- `parse_vtt(path) -> list[Cue{start,end,start_time,end_time,text}]` — port từ `parse_vtt` + `strip_vtt_markup` của dedene/skills (xử lý `<c>`, `<00:00:00.000>`, `\h`, HTML entity).
- `pick_caption(candidates, preference=["vie","vi","en","en-US"])` — sub thủ công > auto sub; vie > en > đầu tiên.
- `dedupe_cues(cues)` — bỏ text trùng liên tiếp (auto-caption lặp).
- `cues_to_paragraphs(cues, gap_threshold=2.0)` — gộp cue → đoạn cho txt/md.

### `core/stt.py`
- Protocol `TranscribeEngine`: `transcribe(audio_path, language) -> list[Cue]`.
- `FasterWhisperEngine`: `WhisperModel(model, device="auto", compute_type="auto")`, cache theo (model,device). Settings: `vad_filter=True`, `condition_on_previous_text=False`, `beam_size=1`, `temperature=0`.
- `MlxEngine` (chỉ darwin/arm64): `mlx_whisper.transcribe(path_or_hf_repo=..., language=...)`.
- `resolve_engine(auto)` → mlx nếu `platform.machine()=="arm64"` và import được, ngược lại faster.
- Bảng model: `small` → faster `small`; mlx `small` → `mlx-community/whisper-small-mlx` (bảng từ `_MLX_MODEL_MAP` của douyin-teardown).

### `core/artifacts.py`
- `VideoDir(video_id)` path builder, `is_processed()`, `write_outputs(cues, meta, source)`, `append_index(record)`.
- Sanitize tên file: `[^\nA-Za-z0-9_-]` → strip; vẫn validate `^[\w-]{6,}$`.

### `core/errors.py`
- `UserError(msg, hint, exit_code)` → in `error: msg\nhint: ...` ra stderr, exit code.
- `_translate_yt_dlp_error(exc)` — port `_ERROR_RULES` từ omni-transcriber downloader.py: map "private video", "members-only", "sign in", "rate-limit", "geo-blocked", "unsupported url" → message + hint (tiếng Anh theo convention tooling), hint gợi ý `--cookies-from-browser`.

### `commands/`
- `transcript.py`: loop URL, `Progress` bar rich cho từng video (download / transcribe %), bảng tổng kết cuối.
- `batch.py`: đọc file, lọc comment/dòng trống, tái dùng pipeline transcript.
- `info.py`, `doctor.py` ở phase 2+.

---

## 7. Layout repo

```
tiktok_cli/
├── PLAN.md                  # file này
├── README.md
├── pyproject.toml           # uv/pip, entry point `tiktok`
├── src/tiktok_cli/
│   ├── __init__.py          # __version__
│   ├── cli.py               # Typer app root, đăng ký subcommand
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
│   ├── test_captions.py     # parse_vtt, dedupe, pick_caption — thuần, không mạng
│   ├── test_url.py          # classify_url
│   ├── test_artifacts.py    # layout, idempotency
│   ├── test_stt.py          # logic chọn engine (mock)
│   └── fixtures/
│       ├── sample.vtt
│       ├── tiktok_info.json
│       └── urls.txt
└── .github/workflows/ci.yml # lint (ruff) + pytest (chỉ test không mạng)
```

Deps trong `pyproject.toml`:
```toml
dependencies = [
  "typer>=0.12", "rich>=13.7",
  "yt-dlp>=2025.1",           # floor pin, không floating latest
  "faster-whisper>=1.1",      # ctranslate2>=4.6.3 floor cho GPU mới (bài học omni-transcriber)
]
[project.optional-dependencies]
mlx = ["mlx-whisper>=0.4"]    # chỉ Apple Silicon
```

Không torch, không openai-whisper, không pydub — gọn như omni-transcriber.

---

## 8. Lộ trình triển khai (các phase)

### Phase 0 — scaffold (nhỏ)
- pyproject, cli.py với `transcript` stub, `doctor` kiểm tra yt-dlp/ffmpeg.
- `uv sync` chạy được, `tiktok --help` < 100ms.

### Phase 1 — đường phụ đề (không Whisper)
- downloader.list_subtitles + download_subs
- captions.parse_vtt/pick/dedupe/render
- artifacts layout + index.jsonl
- `tiktok transcript <url>` end-to-end với video có phụ đề → verify trên 1 video tiếng Việt + 1 tiếng Anh thật.
- Test: fixture parse_vtt, classify url, artifacts.

### Phase 2 — Whisper dự phòng
- stt.py engine faster + mlx
- đường tải audio
- flag `--whisper/--engine/--model`
- Test trên video không phụ đề; benchmark `small` vs `turbo`.

### Phase 3 — batch + hardening
- `tiktok batch`, multi-URL, bảng tổng kết
- dịch lỗi đầy đủ, retry/WAF hints
- đường `--cookies-from-browser`
- README: install (uv tool install), usage, limitations (private/WAF/coverage không phụ đề), bảng benchmark model.

### Phase 4 — khám phá (tuỳ chọn, phụ thuộc `tt`)
- `tiktok info`, `list`, `search`, `tag`, `trending`, `discover`
- `core/discovery.py` bọc subprocess `tt` → parse JSONL
- doctor kiểm tra `tt`
- **Cổng**: chỉ làm sau khi MVP ổn định; search phụ thuộc WAF — ghi "best effort".

### Phase 5 — nice-to-have (cân nhắc, chưa cam kết)
- OCR keyframe `--screen` (hướng tiktok-extractor: ffmpeg scene detect + tesseract).
- Output markdown `--llm` (omni-transcriber `_llm_body`: đoạn ~150 từ có timestamp).
- Song song `--jobs N` (pipeline omni-transcriber: queue fetch + queue transcribe, nhận biết memory).
- `tiktok digest` — đọc index.jsonl → tóm tắt video đã xử lý.

---

## 9. Kế hoạch test

**Unit (không mạng, an toàn cho CI):**
- `parse_vtt`: parse cue, tag `<c>`, xoá trùng, format timestamp.
- `classify_url`: mọi loại URL TikTok.
- `pick_caption`: thứ tự ưu tiên vie > en > auto.
- `render_*`: file golden txt/srt/vtt/json/md.
- `is_processed` / append index.
- `_translate_yt_dlp_error`: mock exception → message.

**Tích hợp (thủ công, cần mạng + TikTok):**
- 1 video tiếng Việt có phụ đề → đường caption.
- 1 video tiếng Anh có phụ đề.
- 1 video không phụ đề → đường whisper, so chất lượng `small` vs `turbo`.
- 1 shortlink vm.tiktok.com.
- 1 video private → fail êm.
- Batch 10 URL → tổng kết đúng.

**Tiêu chí nghiệm thu MVP:** `tiktok transcript <bất kỳ URL TikTok công khai>` → thư mục artifact đủ 5 định dạng + metadata.json + entry index.jsonl, ≤2 phút cho video <3 phút trên Apple Silicon.

---

## 10. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|--------|-----------|
| Extractor TikTok của yt-dlp hỏng (TikTok hay đổi API) | Pin floor `yt-dlp`, `tiktok doctor` báo phiên bản, docs `uv tool install --force`; đường caption chết theo — chấp nhận, đó là thực tế scraping |
| Whisper hallucination trên nhạc/nhiễu | `condition_on_previous_text=False` + VAD + lọc no_speech_prob (công thức douyin-teardown); ghi `--whisper never` cho user chỉ muốn phụ đề |
| Chất lượng tiếng Việt của `small` không đủ | Benchmark trên video thật; default có thể chuyển `turbo` (1.6GB, ~chất lượng large-v3, nhanh) — quyết sau khi test |
| faster-whisper vs mlx-whisper chọn sai | Flag override `--engine`; auto chỉ là mặc định |
| Binary `tt` bị WAF chặn khi search | Cổng phase 4; ghi "best effort"; mặt phẳng SSR bền hơn API — `tt video` ít rủi ro hơn `tt search` |
| Máy user thiếu ffmpeg | faster-whisper/PyAV decode trực tiếp → ffmpeg **không bắt buộc**; doctor chỉ cảnh báo |

---

## 11. Quyết định đã chốt

1. **Model mặc định**: `small` (~466MB) cho faster-whisper; mlx → `mlx-community/whisper-small-mlx`. README ghi cách nâng `turbo`/`large-v3-turbo`.
2. **Audio**: xoá sau khi transcribe; `--keep-audio` opt-in.
3. **Thư mục output**: `./tiktok-transcripts` tương đối cwd; override bằng `-o`.
4. **Khám phá**: build **tất cả** — `info`, `list`, `search`, `tag`, `trending`, `discover` qua binary `tt` trong v1 (vẫn là dep tuỳ chọn, degrade nhẹ nhàng khi thiếu `tt`).
