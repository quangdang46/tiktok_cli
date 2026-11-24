# TikTok Summarizer — Chrome Extension

Bubble nổi trên tiktok.com: bấm ⏺ → ghi audio video đang phát →
bấm lần nữa → Groq Whisper phiên âm → Gemini tóm tắt → panel hiện kết quả.
Không backend — extension gọi thẳng API free-tier.

## Tại sao dùng captureStream thay vì tải file video

TikTok web **không còn SSR video data** — trang watch trả về shell
HTML rỗng (`webapp.video-detail` chỉ có `statusCode`), video load qua
XHR phía client. Không có cách đáng tin để lấy URL mp4 từ content
script → thay vào đó ghi audio trực tiếp từ thẻ `<video>` bằng
`captureStream()` + `MediaRecorder` (webm/opus). Cách này cũng hoạt
động giống hệt trên app Android (MediaProjection) — một pipeline chung.

## Cài đặt

1. Lấy API key (đều free):
   - **Groq**: https://console.groq.com → API Keys.
   - **Gemini**: https://aistudio.google.com → "Get API key".
2. `chrome://extensions` → **Developer mode** → **Load unpacked** →
   chọn thư mục `extension/` này.
3. Options → dán 2 API key → Save.

## Cách dùng

- Mở video TikTok, đảm bảo **video đang phát tiếng** → bấm bubble ⏺
  → bubble nhấp nháy đỏ = đang ghi → bấm lần nữa để dừng → chờ
  transcript + summary.
- Chỉ ghi audio — video phải đang chạy; nếu pause thì transcript rỗng.

## Giới hạn

- `captureStream()` cần Chrome/Edge/Brave mới; nếu video dùng DRM
  (hiếm trên TikTok web) audio track có thể câm.
- Quota free: Groq ~8h audio/ngày; Gemini Flash-Lite ~500 req/ngày.
- Photo post (không tiếng) → transcript rỗng.
