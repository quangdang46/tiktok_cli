# tiktok-cli

<div align="center">
  <img src="docs/assets/tiktok_cli_illustration.webp" alt="tiktok-cli — từ URL TikTok ra file transcript, không cần login, không cần LLM">
</div>

<div align="center">

![Nền tảng](https://img.shields.io/badge/n%E1%BB%81n%20t%E1%BA%A3ng-macOS%20%7C%20Linux%20%7C%20Windows-blue.svg)
![Python](https://img.shields.io/badge/python-%E2%89%A53.11-3776AB.svg)
![Giấy phép](https://img.shields.io/badge/license-MIT-blue.svg)
![Bản phát hành](https://img.shields.io/github/v/release/quangdang46/tiktok_cli)

</div>

**URL TikTok → file transcript. Không login, không LLM, phiên âm chạy local.**
Một lệnh biến bất kỳ video hoặc bài ảnh công khai nào trên TikTok thành
`transcript.txt`, `.srt`, `.vtt`, `.json` và `.md` kèm metadata — ưu tiên
phụ đề có sẵn, Whisper làm phương án dự phòng, thiết kế để AI agent đọc
kết quả trực tiếp mà không cần qua website trung gian.

<div align="center">

```bash
curl -fsSL "https://raw.githubusercontent.com/quangdang46/tiktok_cli/main/install.sh?$(date +%s)" | bash
```

</div>

---

## Khởi động nhanh cho Agent

Được xây dựng cho agent (Claude Code, Codex, Devin, script). Quy ước:

- **stdout chỉ chứa kết quả** — `transcript` in mỗi video một dòng
  `VIDEO_ID | nguồn | cues=N | thư mục`; `batch` in đường dẫn
  `transcript.txt` từng video + một dòng summary cuối. `--json` không có
  vì artifact `.json` đã là output máy đọc được.
- **stderr chứa toàn bộ chẩn đoán** — progress bar, cảnh báo, log yt-dlp,
  bảng tổng kết batch. An toàn để pipe stdout.
- **exit 0 = mọi URL thành công**; `transcript` exit 1 nếu có URL lỗi,
  `batch` chỉ exit 1 khi *không gì* thành công và có ít nhất một URL lỗi.

```bash
# 1. Phiên âm — ghi vào ./tiktok-transcripts/VIDEO_ID/
tiktok transcript "https://www.tiktok.com/@user/video/123"

# 2. Đọc transcript — plain text, không timestamp, vừa cỡ agent
tiktok-transcripts/VIDEO_ID/transcript.txt

# 3. Bản có timestamp + metadata để trích dẫn
tiktok-transcripts/VIDEO_ID/transcript.md

# 4. Danh sách cue dạng máy đọc được
tiktok-transcripts/VIDEO_ID/transcript.json   # [{start, end, text}]

# 5. Chạy hàng loạt từ file URL (stdout = đường dẫn transcript.txt)
tiktok batch urls.txt

# 6. Kiểm tra sức khỏe trước khi chạy lớn
tiktok doctor
```

**Câu lệnh gợi ý cho agent:** *"Chạy `tiktok transcript <url>`, rồi đọc
`tiktok-transcripts/<id>/transcript.txt` (hoặc `.md` nếu cần timestamp).
Đừng parse stdout để lấy nội dung — stdout chỉ chứa dòng trạng thái."*

---

## TL;DR

### Vấn đề

- Thấy video TikTok đáng xem nhưng ngại xem hết 3 phút.
- Các trang transcript yêu cầu login, phải upload link cho bên thứ ba,
  hoặc khoá paywall/kết quả.
- Tự lắp yt-dlp + ffmpeg + Whisper cho từng video nghĩa là phải xử lý lại
  lỗi phụ đề, parse VTT, cấu hình chống hallucination và định dạng đầu ra
  mỗi lần.

### Giải pháp

`tiktok transcript <url>` làm trọn pipeline trong một lệnh:

1. Lấy metadata qua yt-dlp.
2. **Ưu tiên phụ đề** — tải track phụ đề có sẵn của TikTok khi có
   (đa số video có auto-caption → Whisper không cần chạy).
3. **Whisper dự phòng** — faster-whisper local (mlx-whisper trên Apple
   Silicon), kèm VAD + chống hallucination.
4. Xuất `txt`/`srt`/`vtt`/`json`/`md` + `metadata.json`, append vào
   `index.jsonl`.

Bài ảnh/slideshow (`/photo/`) được phiên âm **audio** **và** tải ảnh —
CLI tự giải JS challenge công khai của TikTok để đọc dữ liệu `imagePost`
mà yt-dlp không thấy.

### Vì sao không tự lắp yt-dlp + Whisper?

- Phụ đề TikTok trả về là file `.vtt` thô — phải tự parse timestamp, gộp
  cue, chọn ngôn ngữ, rồi mới có transcript sạch.
- Whisper mặc định hallucinate trên đoạn nhạc/im lặng — cần VAD filter và
  tham số `condition_on_previous_text=False` mà ít ai nhớ set.
- Photo post `/photo/` bị extractor yt-dlp từ chối hoàn toàn; phải tự
  rewrite URL và giải challenge phía client.
- Batch + cache + index phải tự viết — tiktok-cli cho sẵn và idempotent
  mặc định.

### Vì sao chọn tiktok-cli?

| Khả năng | tiktok-cli | yt-dlp + whisper (thủ công) | gerardnico/transcribe | gallery-dl |
|---|---|---|---|---|
| TikTok URL → transcript | ✅ một lệnh | ⚠️ tự lắp | ✅ | ❌ (chỉ media) |
| Ưu tiên phụ đề (bỏ qua Whisper) | ✅ | ❌ thủ công | ✅ | n/a |
| STT local, không API key | ✅ faster/mlx-whisper | ✅ | ✅ openai-whisper (nặng) | n/a |
| Định dạng txt/srt/vtt/json/md | ✅ đủ 5 | thủ công | một phần | ❌ |
| Ảnh + audio của photo post | ✅ | ❌ | ❌ | ✅ chỉ ảnh |
| Batch + index idempotent | ✅ `index.jsonl` | ❌ | ⚠️ cache session | ⚠️ |
| Contract cho agent (stdout/stderr) | ✅ | ❌ | ⚠️ | ❌ |
| Không cần login | ✅ | ✅ | ✅ | ✅ |
| Khám phá (search/trending) | ⏸️ tạm dừng | ❌ | ❌ | ⚠️ bị WAF chặn |

---

## Ví dụ nhanh

```bash
# Video đơn — đi đường phụ đề (tức thì, không cần Whisper)
tiktok transcript "https://www.tiktok.com/@cnn/video/7489575527632833838"
# → tiktok-transcripts/7489575527632833838/transcript.txt  (40 cues, captions)

# Ép Whisper kể cả khi có phụ đề
tiktok transcript <url> --whisper always -m turbo

# Chỉ lấy phụ đề — không tốn tài nguyên Whisper
tiktok transcript <url> --whisper never

# Photo post — transcript audio + ảnh slideshow
tiktok transcript "https://www.tiktok.com/@user/photo/7707892619572972813"
# → VIDEO_ID/images/image_01.jpg ... + images.json + transcript.*

# Batch từ file (# được phép comment)
tiktok batch urls.txt
# → đường dẫn transcript.txt từng video + bảng tổng kết trên stderr;
#   một URL lỗi không làm chết cả run

# Chạy lại miễn phí — URL đã xử lý sẽ skip ngay
tiktok transcript <url>          # → skipped-cached
tiktok transcript <url> --refresh  # ép làm lại

# Cookies khi TikTok "khó tính" (tuỳ chọn, không bắt buộc)
tiktok transcript <url> --cookies-from-browser chrome
```

---

## Các lệnh

| Lệnh | Mô tả | Flag chính |
|------|-------|-----------|
| `tiktok transcript <urls...>` | Phiên âm một hoặc nhiều video (ưu tiên phụ đề, Whisper dự phòng). | `-o/--output-dir`, `--whisper auto\|always\|never`, `--engine auto\|faster\|mlx`, `-m/--model`, `--format txt\|srt\|vtt\|json\|md\|all`, `--keep-audio`, `--refresh`, `--cookies-from-browser`, `--cookies`, `-v` |
| `tiktok batch <file>` | Xử lý danh sách URL, mỗi dòng một URL (cho phép `#` comment, tự dedupe); lỗi từng video không dừng cả run. | cùng bộ flag pipeline như `transcript` |
| `tiktok doctor` | Kiểm tra yt-dlp, ffmpeg, faster-whisper, mlx-whisper, model đã cache, `tt`, mạng, thư mục output. Exit 1 nếu thiếu dep cốt lõi. | — |

> Các lệnh khám phá (`info`, `search`, `list`, `tag`, `trending`,
> `discover`) hiện **tạm dừng** — xem mục Giới hạn.

`tiktok transcript` và `batch` dùng chung bộ option:

| Flag | Mặc định | Ý nghĩa |
|------|---------|---------|
| `-o, --output-dir` | `./tiktok-transcripts` | Thư mục gốc chứa kết quả |
| `--whisper` | `auto` | `auto` = chỉ Whisper khi không có phụ đề; `always` = bỏ qua phụ đề; `never` = chỉ phụ đề |
| `--engine` | `auto` | `mlx` trên Apple Silicon nếu đã cài, ngược lại `faster` |
| `-m, --model` | `small` | `tiny` `base` `small` `medium` `large-v3` `turbo` `distil-large-v3`, repo HF, hoặc đường dẫn local |
| `--format` | `all` | Các file transcript cần ghi |
| `--keep-audio` | tắt | Giữ `audio.*` sau khi Whisper xong (mặc định: xoá) |
| `--refresh` | tắt | Bỏ cache, tải lại và phiên âm lại |
| `-l, --language` | auto | Gợi ý ngôn ngữ cho Whisper |
| `--cookies-from-browser` | — | `chrome`/`firefox`/`safari`/... chuyển tiếp cho yt-dlp |
| `--cookies` | — | File `cookies.txt` định dạng Netscape |
| `-v, --verbose` | tắt | Log debug của yt-dlp ra stderr |

## Cấu trúc output

```
tiktok-transcripts/                  # --output-dir
├── VIDEO_ID/                        # yt-dlp info["id"]
│   ├── source.info.json             # info yt-dlp thô (ghi một lần)
│   ├── metadata.json                # gọn: title, uploader, duration, counts, url
│   ├── subs/                        # file .vtt phụ đề thô từ yt-dlp
│   │   └── VIDEO_ID.eng-US.vtt ...
│   ├── audio.*                      # chỉ khi --keep-audio (đường Whisper)
│   ├── transcript.vtt               # canonical có timestamp (phụ đề hoặc whisper)
│   ├── transcript.srt
│   ├── transcript.txt               # plain text, không timestamp — thứ agent đọc
│   ├── transcript.json              # [{start, end, text}]
│   ├── transcript.md                # # title + metadata + cue [mm:ss]
│   ├── images/                      # chỉ photo post: ảnh slideshow
│   │   └── image_01.jpg ...
│   └── images.json                  # chỉ photo post: manifest ảnh
└── index.jsonl                      # log append-only của mọi video đã xử lý
```

`index.jsonl` ghi `{video_id, url, status, language, cue_count, duration,
artifact_dir, processed_at}` — đủ để build digest hoặc bỏ qua video đã xử
lý mà không cần database. Status: `caption`, `whisper`, `no-captions`,
`no-audio`, `photo-post`, `skipped-cached`, `failed`.

## Nguyên tắc thiết kế

| Nguyên tắc | Vì sao |
|-----------|--------|
| Ưu tiên phụ đề, Whisper dự phòng | Đa số TikTok có auto-caption — tiết kiệm ~90% tài nguyên STT |
| Dep nặng lazy-load | `tiktok --help` vẫn nhanh; faster-whisper/yt-dlp chỉ import khi cần |
| stdout = dữ liệu, stderr = chẩn đoán | Agent pipe stdout an toàn (ràng buộc kiểu omni-transcriber) |
| Idempotent mặc định | `transcript.json` đã có → skip; `--refresh` để làm lại |
| Cô lập lỗi từng video | Một URL hỏng không giết cả batch; lỗi ghi vào `index.jsonl` |
| Lỗi trung thực | Private/WAF/rate-limit → thông báo rõ + gợi ý fix, không bao giờ trả output rỗng lặng lẽ |
| Không torch, không openai-whisper | PyAV của faster-whisper decode trực tiếp — không cần bước extract ffmpeg |

## Cài đặt

Cần Python 3.11+. Script cài một dòng tự detect `uv` → `pipx` → `pip`:

```bash
# macOS / Linux
curl -fsSL "https://raw.githubusercontent.com/quangdang46/tiktok_cli/main/install.sh?$(date +%s)" | bash

# Windows PowerShell
irm "https://raw.githubusercontent.com/quangdang46/tiktok_cli/main/install.ps1" | iex
```

Flag của installer: `--version vX.Y.Z` (ghim bản), `--prefer uv|pipx|pip`,
`--with-mlx` (backend Whisper Apple Silicon), `--verify` (chạy
`tiktok --help` sau cài), `--uninstall`, `--quiet`.

Cách thủ công tương đương:

```bash
# Khuyến nghị: cài tool cô lập thẳng từ git
uv tool install git+https://github.com/quangdang46/tiktok_cli

# Cách khác
pipx install git+https://github.com/quangdang46/tiktok_cli
pip install git+https://github.com/quangdang46/tiktok_cli
```

Lệnh này cho bạn `tiktok`. Kiểm tra bằng `tiktok doctor`.

### Extra tuỳ chọn

- **Apple Silicon (macOS arm64):** cài extra `mlx` để dùng backend
  mlx-whisper nhanh hơn (tự chọn khi có):

  ```bash
  uv tool install --with mlx-whisper git+https://github.com/quangdang46/tiktok_cli
  # hoặc sau khi pip install:
  pip install "tiktok-cli[mlx]"
  ```

  Không có nó, Whisper tự rơi về faster-whisper.

## Photo post / bài slideshow

URL `/photo/` là carousel ảnh kèm track audio. CLI sẽ:

1. Viết lại URL sang dạng `/video/` tương đương (extractor TikTok của
   yt-dlp từ chối `/photo/` thẳng, nhưng cùng id resolve được qua
   `/video/`).
2. Phiên âm track audio như video thường.
3. Tải trang bài viết, giải JS proof-of-work challenge công khai của
   TikTok, và tải `imagePost.images` vào `VIDEO_ID/images/` kèm
   `images.json` (source URL, kích thước, tác giả, timestamp).

Tải ảnh là best-effort: nếu TikTok đổi format challenge, transcript
audio vẫn thành công và cảnh báo đi ra stderr.

## Xử lý sự cố

| Triệu chứng | Nguyên nhân | Cách sửa |
|-------------|-------------|----------|
| `Download failed: ... certificate verify failed` | Proxy/AV chặn TLS local, hoặc edge CDN chập chờn | Thử lại; `curl-cffi` impersonation đã bật — lỗi dai dẳng nghĩa là chặn ở tầng mạng |
| `private video` / `members-only` / `sign in` | Nội dung cần login | `--cookies-from-browser chrome` (Safari cần Full Disk Access) hoặc `--cookies cookies.txt` |
| `rate-limit` / `429` | Quá nhiều request | Chờ rồi thử lại; batch chạy tuần tự theo thiết kế |
| Transcript Whisper vô nghĩa trên nhạc | Không có lời nói — VAD phải cho 0 cue | Đúng vậy; kiểm tra số cue trong `transcript.json` |
| Tiếng Việt kém trên model `small` | Model quá nhỏ cho tiếng Việt | `-m turbo` hoặc `-m large-v3-turbo` (VN tốt hơn, ~1.5GB tải về) |
| `no captions - transcribing audio` rồi chậm | Video không có track phụ đề | Bình thường — lần chạy Whisper đầu tải model một lần |
| `Unsupported URL` với link `/photo/` | Hành vi cũ — đã fix ở 0.1.0 | Nâng cấp; photo post giờ hoạt động |
| `ffmpeg` WARN trong doctor | Chưa cài | Tuỳ chọn — PyAV của faster-whisper decode audio trực tiếp |
| `mlx-whisper` WARN | Chưa cài / không phải arm64 | Tuỳ chọn — tự rơi về faster-whisper |

## Giới hạn

- **Video private, đã xoá, giới hạn độ tuổi hoặc yêu cầu login sẽ lỗi.**
  CLI không có flow login; `--cookies-from-browser` / `--cookies` chỉ là
  passthrough best-effort, không vượt qua được mọi thứ.
- **TikTok hay đổi nội bộ.** Việc tải phụ thuộc extractor TikTok của
  yt-dlp; khi TikTok làm gãy nó, nâng cấp yt-dlp
  (`uv tool install --force ...`) rồi chạy `tiktok doctor` kiểm tra
  phiên bản.
- **Lệnh khám phá đang tạm dừng.** `info`, `search`, `list`, `tag`,
  `trending`, `discover` phụ thuộc binary ngoài `tt` và endpoint web
  của TikTok nằm sau anti-bot/WAF rất gắt — thực tế đa số IP bị
  challenge kể cả trên đường đọc bền hơn, nên các lệnh đã gỡ khỏi CLI.
  `transcript`/`batch`/`doctor` không ảnh hưởng. Code và test vẫn nằm
  trong repo để bật lại khi cần.
- **Không có phụ đề + `--whisper never`** cho kết quả `no-captions`:
  có metadata và entry index nhưng không có file transcript.
- **Ảnh slideshow là best-effort.** Phụ thuộc format JS challenge công
  khai của TikTok giữ ổn định; transcript audio không bị ảnh hưởng.
- **Không có tính năng LLM.** CLI này chỉ trích transcript; tóm tắt,
  chia chương, phân tích là việc của bên gọi.

## FAQ

**Có cần login TikTok không?**
Không. Video công khai hoạt động ẩn danh. `--cookies-from-browser` chỉ
tồn tại như phương án dự phòng cho trường hợp giới hạn độ tuổi hoặc IP
chập chờn.

**Audio có rời khỏi máy không?**
Không. Phụ đề lấy từ track subtitle của chính TikTok; Whisper chạy
local (faster-whisper hoặc mlx-whisper). Không gì được upload đi đâu.

**Vì sao ưu tiên phụ đề thay vì luôn Whisper?**
Auto-caption của TikTok phủ đa số video và tức thì + miễn phí. Whisper
chỉ chạy khi không có track phụ đề (`--whisper auto`, mặc định).

**Nên dùng model Whisper nào?**
`small` (mặc định, ~466MB) là cân bằng tốc độ/chất lượng. `turbo` hoặc
`large-v3-turbo` (~1.5GB) tốt hơn rõ cho tiếng Việt và giọng có dấu.
`tiny`/`base` cho bản nháp nhanh.

**`--whisper never` làm gì?**
Bỏ qua Whisper hoàn toàn — video không có phụ đề nhận status
`no-captions` (chỉ metadata + entry index). Dùng khi bạn chỉ muốn trích
phụ đề miễn phí.

**Lấy được ảnh từ photo post không?**
Có — `images/` + `images.json` trong thư mục artifact. Track audio cũng
được phiên âm (thường chỉ là nhạc → 0 cue, đúng vậy).

**Vì sao batch của tôi exit khác 0?**
`batch` chỉ exit 1 khi không gì thành công *và* có ít nhất một URL lỗi.
Thành công một phần vẫn exit 0 — xem bảng tổng kết và `index.jsonl` để
biết status từng URL.

**TikTok có làm hỏng tool này không?**
Sớm muộn cũng có — đây là scraping. yt-dlp được maintain tích cực; chạy
`tiktok doctor` kiểm tra phiên bản và nâng cấp bằng
`uv tool install --force git+https://github.com/quangdang46/tiktok_cli`.

## Phát triển

```bash
uv sync                     # cài deps + dev extras vào .venv
uv run pytest               # test suite, không mạng, không tải model
uv run ruff check .         # lint
uv run ruff format .        # format
uv run tiktok transcript <url>   # chạy CLI từ source
```

CI chạy ruff + pytest trên Ubuntu, macOS, Windows × Python 3.12/3.13.
Test tích hợp với URL TikTok thật làm thủ công (xem PLAN.md §9).

## Giấy phép

MIT — xem [LICENSE](LICENSE).
