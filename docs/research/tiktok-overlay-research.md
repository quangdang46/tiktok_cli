# Research: công cụ tóm tắt video TikTok (extension + overlay Android)

Ngày: 2026-11-24. Trạng thái: findings đã đối chiếu nguồn chính ở những
chỗ ghi chú.

## Mục tiêu

Chrome extension: bubble nổi trên tiktok.com → bấm → ghi âm video đang
xem → phiên âm → LLM tóm tắt → hiện panel.

(APK overlay Android đã research và prototype, sau đó user quyết định bỏ
— chỉ làm extension.)

Ràng buộc đã chốt với user: không backend riêng, API key lưu trong app,
chỉ dùng API free-tier, Chrome trước, extension MVP trước APK.

## RQ-001 — Content script có xác định được video TikTok đang xem không?
TRẢ LỜI: MỘT PHẦN — đã đổi hướng tiếp cận

Giả định ban đầu: `__UNIVERSAL_DATA_FOR_REHYDRATION__` nhúng sẵn toàn
bộ dữ liệu video (playAddr, desc). **Verify SAI với fetch ẩn danh
(2026-11-24):** HTML trang watch có thẻ script đó nhưng
`webapp.video-detail` chỉ chứa `{statusCode, statusMsg}` — TikTok giờ
load dữ liệu item qua XHR phía client sau hydration. Không có cách đáng
tin để lấy URL mp4 từ content script (API call có ký, src dạng MSE/blob).

**Thiết kế đã pivot:** không resolve file video nữa. Ghi âm thẻ
`<video>` đang phát ngay trong page bằng `video.captureStream()` →
`MediaRecorder` (webm/opus) → gửi blob cho Groq. Không cần video ID,
không cần URL CDN, hoạt động giống nhau trên trang watch lẫn feed, và
giống hệt hướng MediaProjection của Android — một pipeline chung:
`audio → Groq STT → Gemini summary`.

Metadata best-effort còn lại: text caption cạo từ DOM (`h1`, phần tử
`data-e2e` desc) đưa vào prompt tóm tắt.

**ĐÃ VERIFY 2026-11-24** trên tiktok.com/foryou thật bằng headless
Chrome: `video.captureStream()` trả về track `audio` + `video` live và
audio capture có tín hiệu thật (RMS peak ≈ 0.17) dù `src` của `<video>`
là URL `blob:` MSE. MediaRecorder → webm/opus → Groq
`/audio/transcriptions` hỗ trợ webm/opus native.

## RQ-002 — Phiên âm không backend? TRẢ LỜI: CÓ (Groq Whisper free tier)

Groq `whisper-large-v3-turbo` / `whisper-large-v3`: đa ngôn ngữ (gồm
tiếng Việt), endpoint tương thích OpenAI
`https://api.groq.com/openai/v1/audio/transcriptions`.
Free tier (theo docs, bên thứ ba verify 2026-11): ~20 RPM,
~2000 RPD, ~8h audio/ngày, file tối đa 25 MB. Nhận webm/opus, wav,
mp4 v.v. — output `audio/webm;codecs=opus` của MediaRecorder upload
trực tiếp, không cần transcode.

Phương án dự phòng nếu file >25 MB hoặc hết quota: capture audio qua
`AudioContext` + `MediaElementSource` trong page (phụ thuộc CORS của
CDN — không đáng tin), hoặc upload từng phần (Groq không hỗ trợ chunk;
phải ffmpeg.wasm — nặng, loại khỏi MVP).

## RQ-003 — LLM tóm tắt $0? TRẢ LỜI: CÓ (Gemini free tier)

Gemini API free tier: `gemini-*-flash-lite` ~500 RPD / 5 RPM,
`gemini-*-flash` ~20 RPD. Flash-Lite đủ cho transcript→summary. Hỗ trợ
tiếng Việt.
Phương án một call duy nhất: Gemini multimodal có thể phiên âm audio
trực tiếp, gộp STT+tóm tắt thành một API — để làm option sau; MVP dùng
Groq(STT) + Gemini(summary) vì STT của Groq nhanh/rẻ hơn theo giờ audio
và cô lập lỗi tốt hơn.

## RQ-004 — Overlay Android khả thi không? TRẢ LỜI: CÓ, kèm lưu ý

- Bubble: quyền `SYSTEM_ALERT_WINDOW` ("hiển thị trên app khác"), kỹ
  thuật chuẩn của các app chat-head.
- Detect TikTok foreground: poll `UsageStatsManager` hoặc
  `AccessibilityService` đọc `packageName` cửa sổ active.
- Lấy nội dung video: không API nào expose video đang phát. Đường thực
  tế = `MediaProjection` + `AudioPlaybackCapture` (Android 10+): user
  cấp consent một lần mỗi lần boot, app capture audio app (TikTok dùng
  USAGE_MEDIA → capture được; app DRM opt-out, TikTok dường như không)
  → WAV → cùng pipeline Groq/Gemini. Tuỳ chọn capture thêm frame cho
  OCR/vision summary sau này.
- Lưu ý: dialog consent quay lại sau mỗi lần reboot; service
  `mediaProjection` foreground type bắt buộc (Android 14+); Play Store
  review nhiều khả năng reject → sideload APK cho personal use.

## Ngoài phạm vi (MVP)

- Không backend/server riêng; key nằm trong storage của extension.
- Không auto-tóm-tắt trên feed (chỉ tóm tắt khi bấm nút).
- Không iOS (không có API overlay tương đương nếu không jailbreak).
- Không APK Android — user quyết định bỏ; findings RQ-004 giữ lại dưới
  đây để tham khảo nếu quay lại.

## Câu hỏi còn mở

- Shape JSON `webapp.video-detail` hiện tại chính xác ra sao (cần
  verify runtime trên TikTok live; parser phải chịu lỗi tốt).
- Fetch `playAddr` của CDN TikTok có cần Referer/headers không — cần
  test; fallback là fetch HTML trang watch rồi parse lại.
- Quota ngày hiệu dụng của Gemini Flash-Lite tuỳ project; giữ model
  cấu hình được trong options.
