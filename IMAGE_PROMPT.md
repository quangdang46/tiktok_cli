# Prompt tạo ảnh hero cho README

Copy block trong ```` ``` ```` bên dưới paste vào image generator (image_gen / Midjourney / DALL-E / v.v.).

````
[SYSTEM / STYLE LOCK]
Stylized 3D cartoon GitHub README hero illustration for a developer CLI tool. Cute blue-and-white robot mascot with large glowing lime-green eyes, dark visor, soft smile, orange baseball cap, compact chibi proportions — placed in the right third of the frame, actively presenting the system. Landscape ~16:9 composition, clear focal metaphor center/left, depth with foreground desk/tools + mid machine + environmental background. Product name on a large readable sign; 5-8 short English ALL-CAPS labels on machines/screens; 1-2 small metric callouts. Soft studio lighting, gentle bloom on screens, warm spark particles, premium materials (metal, glass, plastic). Approach­able operator energy — helpful robot building software infrastructure. No watermark, no border, no photoreal humans, no flat icon collage, every visible word correctly spelled English.

[USER]
Tool: "tiktok-cli" — TikTok URL to local transcript files. No login, no LLM, caption-first with local Whisper fallback.

Metaphor: a friendly robot at a workbench feeding a TikTok video URL into a machine that prints out clean transcript pages — a conveyor of caption subtitles flows in, Whisper audio-waveform transcriber waits as backup, output stacks of .txt/.srt/.vtt/.json/.md documents and a photo-post carousel of images.

Labels to show clearly on signs/machines (use exactly): tiktok-cli, TRANSCRIPT, CAPTIONS FIRST, WHISPER LOCAL, NO LOGIN, NO LLM, .txt .srt .vtt .json .md, PHOTO POST.

Metric callouts: "0 API keys", "100% local STT".

Environment kit: warm workshop — bright pastel background with soft pink blossom accents, mint and white surfaces, wooden workbench.

Mascot action: holding a small printed transcript sheet, other hand pointing at the subtitle conveyor feeding the machine; orange cap, green eyes.

Include product title sign: "tiktok-cli". Tagline under title (optional, ≤6 words): "URL IN, TRANSCRIPT OUT".

Follow the STYLE LOCK. Landscape hero for GitHub README. No watermark.
````

## Ghi chú

- Lưu kết quả thành `docs/assets/tiktok_cli_illustration.webp` (hoặc tên mới rồi sửa `<img src>` trong README).
- Ảnh cũ đã tồn tại ở `docs/assets/tiktok_cli_illustration.webp` — chỉ cần chạy prompt này nếu muốn ảnh mới.
- Nếu model làm rối chữ: giảm labels xuống icon + 4-5 từ ALL-CAPS.
- QA sau khi gen: mascot đúng DNA (xanh/trắng, mắt xanh lá phát sáng, mũ cam), tên sản phẩm đọc được, metaphor khớp "URL → transcript", không watermark.
