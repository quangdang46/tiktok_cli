# TikTok Summarizer — Android APK

Overlay bubble nổi trên app TikTok → bấm để ghi âm video → Groq Whisper
phiên âm → Gemini tóm tắt → hiện kết quả ngay trên màn hình.
Không backend, không root — dùng `MediaProjection` + `AudioPlaybackCapture`.

## Quyền cần cấp (1 lần setup)

1. **Hiển thị trên app khác** (`SYSTEM_ALERT_WINDOW`) — bubble nổi.
2. **Usage Access** — detect app TikTok đang foreground.
3. **Microphone** — `AudioPlaybackCapture` yêu cầu `RECORD_AUDIO`.
4. **MediaProjection consent** — hệ thống hỏi "Start now" **mỗi lần reboot**
   (giới hạn Android, không tránh được).

## Build

Yêu cầu: JDK 17+, Android SDK (platform 34, build-tools), Gradle.

```bash
cd apk
gradle wrapper            # tạo wrapper nếu chưa có
./gradlew assembleDebug   # → app/build/outputs/apk/debug/app-debug.apk
```

Sideload APK lên điện thoại (không qua Play Store — app dạng này khó
được duyệt). Android 10+ mới capture được audio app khác.

## Luồng hoạt động

```
MainActivity (nhập API key + cấp quyền)
  → BubbleService: bubble nổi + panel overlay + ForegroundWatcher
  → tap bubble khi TikTok foreground
  → ConsentActivity: xin MediaProjection consent
  → CaptureService (FGS mediaProjection): AudioRecord capture
    audio USAGE_MEDIA → WAV 16kHz mono
  → tap bubble lần nữa → stop → ApiClient:
      WAV → Groq whisper-large-v3-turbo → transcript
      transcript → Gemini → summary
  → panel hiện kết quả
```

## Giới hạn đã biết

- Capture **toàn bộ audio media** trên máy (không tách riêng TikTok) —
  nên tắt nhạc nền khi dùng.
- Consent MediaProjection phải xin lại sau mỗi lần reboot.
- Video dài → WAV lớn → upload lâu + chạm quota Groq free (~8h/ngày).
- TikTok package names detect: musically / ugc.trill / ugc.aweme.
- Chất lượng phụ thuộc audio capture — nếu TikTok đổi audio usage
  policy thì capture ra silence.
