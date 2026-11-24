# TikTok Summarizer — Extension Chrome

Bubble nổi trên tiktok.com: bấm ⏺ → ghi âm video đang phát →
bấm lần nữa → Groq Whisper phiên âm → Gemini tóm tắt → panel hiện kết quả.
Không backend — extension gọi thẳng API miễn phí, không tốn server.

## Tại sao ghi âm thay vì tải file video

TikTok web **không còn nhúng sẵn dữ liệu video** — trang xem trả về
template HTML rỗng (`webapp.video-detail` chỉ có `statusCode`), dữ
liệu video load qua XHR phía trình duyệt. Không có cách đáng tin để
lấy URL mp4 từ content script → nên ghi âm trực tiếp từ thẻ `<video>`
bằng `captureStream()` + `MediaRecorder` (webm/opus). Đã verify trên
TikTok thật: audio track live, có tín hiệu.

## Cài đặt

1. Lấy 2 API key (đều miễn phí):
   - **Groq** (phiên âm): https://console.groq.com → API Keys.
   - **Gemini** (tóm tắt): https://aistudio.google.com → "Get API key".
2. Vào `chrome://extensions` → bật **Developer mode** (chế độ nhà
   phát triển) → **Load unpacked** (Tải tiện ích đã giải nén) →
   chọn thư mục `extension/` này.
3. Mở trang **Options** của extension → dán 2 API key → **Save**.

## Cách dùng

- Mở video TikTok bất kỳ, đảm bảo **video đang phát tiếng** → bấm
  bubble ⏺ → bubble nhấp nháy đỏ = đang ghi → bấm lần nữa để dừng →
  chờ bản tóm tắt + transcript hiện trong panel.
- Chỉ ghi âm — video phải đang chạy; nếu tạm dừng thì transcript rỗng.

## Giới hạn

- `captureStream()` cần Chrome/Edge/Brave bản mới.
- Video dùng DRM (hiếm gặp trên TikTok web) có thể cho audio câm.
- Hạn mức free: Groq ~8 giờ audio/ngày; Gemini Flash-Lite ~500
  request/ngày — vượt thì phải chờ reset hoặc nâng cấp trả phí.
- Photo post / video không lời nói → transcript rỗng.
