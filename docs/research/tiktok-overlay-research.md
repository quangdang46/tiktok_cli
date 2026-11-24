# Research: TikTok video summarizer (extension + Android overlay)

Date: 2026-11-24. Status: findings verified against primary sources where noted.

## Goal

Chrome extension: floating bubble on tiktok.com → tap → record current
video's audio → transcribe → LLM summary → show panel.

(Android overlay APK was researched and prototyped, then dropped by user
decision — extension only.)

Constraints decided with user: no own backend, API keys stored in-app,
free-tier APIs only, Chrome first, extension MVP before APK.

## RQ-001 — Can a content script identify the current TikTok video? ANSWERED: PARTIALLY — approach changed

Initial assumption: `__UNIVERSAL_DATA_FOR_REHYDRATION__` inlines full
video data (playAddr, desc). **Verified FALSE for anonymous fetch
(2026-11-24):** the watch-page HTML contains the script tag but
`webapp.video-detail` holds only `{statusCode, statusMsg}` — TikTok now
loads item data via client-side XHR after hydration. There is no
reliable way to extract the mp4 URL from a content script (signed API
calls, MSE/blob src).

**Pivoted design:** don't resolve the video file at all. Record the
playing `<video>` element's audio in-page with
`video.captureStream()` → `MediaRecorder` (webm/opus) → send blob to
Groq. This needs no video ID, no CDN URL, works identically on watch
pages and the feed, and mirrors the Android MediaProjection approach —
one shared pipeline: `audio → Groq STT → Gemini summary`.

**VERIFIED 2026-11-24** on live tiktok.com/foryou in headless Chrome:
`video.captureStream()` returns live `audio` + `video` tracks and the
captured audio has real signal (RMS peak ≈ 0.17) even though the
`<video>` src is a `blob:` MSE URL. MediaRecorder → webm/opus → Groq
`/audio/transcriptions` accepts webm/opus natively.

Remaining best-effort metadata: caption text scraped from DOM
(`h1`, `data-e2e` desc elements) for the summary prompt.

## RQ-002 — Transcription without a backend? ANSWERED: YES (Groq Whisper free tier)

Groq `whisper-large-v3-turbo` / `whisper-large-v3`: multilingual
(incl. Vietnamese), OpenAI-compatible endpoint
`https://api.groq.com/openai/v1/audio/transcriptions`.
Free tier (per docs, third-party verified 2026-11): ~20 RPM,
~2000 RPD, ~8h audio/day, max file 25 MB. Accepts webm/opus, wav,
mp4 etc — the MediaRecorder `audio/webm;codecs=opus` output uploads
directly, no transcoding needed.

Fallback if file >25 MB or quota hit: capture audio via
`AudioContext` + `MediaElementSource` in the page (subject to CORS on
the CDN — unreliable), or chunked upload (Groq doesn't support chunks;
would need ffmpeg.wasm — heavy, rejected for MVP).

## RQ-003 — Summarization LLM with $0? ANSWERED: YES (Gemini free tier)

Gemini API free tier: `gemini-*-flash-lite` ~500 RPD / 5 RPM,
`gemini-*-flash` ~20 RPD. Flash-Lite is sufficient for
transcript→summary. Vietnamese supported.
Alternative single-call option: Gemini multimodal can transcribe audio
directly, collapsing STT+summary into one API — kept as a later option;
MVP uses Groq(STT) + Gemini(summary) because Groq's STT is faster/cheaper
per audio-hour and isolates failures.

## RQ-004 — Android overlay feasibility? ANSWERED: YES, with caveats

- Bubble: `SYSTEM_ALERT_WINDOW` permission ("display over other apps"),
  standard technique used by chat-head apps.
- Detect TikTok foreground: `UsageStatsManager` polling or an
  `AccessibilityService` reading `packageName` of the active window.
- Get the video content: no API exposes the playing video. Practical
  path = `MediaProjection` + `AudioPlaybackCapture` (Android 10+):
  user grants a one-time-per-boot consent dialog, app captures app
  audio (TikTok uses USAGE_MEDIA → capturable; DRM apps opt out,
  TikTok does not appear to) → WAV → same Groq/Gemini pipeline.
  Optionally also capture frames for OCR/vision summary later.
- Caveats: consent dialog returns after each reboot; foreground
  `mediaProjection` service type required (Android 14+); Play Store
  review likely rejects → sideload APK for personal use.

## Non-goals (MVP)

- No backend/server of our own; keys live in extension storage.
- No feed-mode auto-summarize (only on-demand button press).
- No iOS (no overlay API equivalent without jailbreak).
- No Android APK — cut by user decision; RQ-004 findings kept below
  for reference if revisited.

## Open questions

- Exact current shape of `webapp.video-detail` JSON (verify at runtime
  against live TikTok; parser must be tolerant).
- Whether TikTok CDN `playAddr` fetch needs Referer/headers — test;
  fallback is fetching the watch page HTML and re-parsing.
- Gemini Flash-LE effective daily quota varies per project; keep model
  configurable in options.
