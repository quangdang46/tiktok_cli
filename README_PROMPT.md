# Prompt: viết lại README.md cho tiktok-cli

Copy toàn bộ block trong ```` ``` ```` bên dưới, paste vào agent/bất kỳ AI nào để tái tạo README.

````markdown
Rewrite README.md in banner-first premium CLI style for this repo.

Repo facts (verified — do not invent beyond these):
- Project: tiktok-cli, Python 3.11+, Typer + Rich. Binary name: `tiktok`.
- What it does: TikTok URL -> local transcript files. No login, no LLM, caption-first with local Whisper fallback.
- Commands (only these are live): `tiktok transcript <urls...>`, `tiktok batch <file>`, `tiktok doctor`.
  Discovery commands (info/search/list/tag/trending/discover) are SUSPENDED — code kept in repo but unregistered. Document as a known limitation, do not document them as usable.
- Pipeline: yt-dlp metadata -> prefer TikTok's own captions -> faster-whisper fallback (mlx-whisper auto-preferred on Apple Silicon) -> writes txt/srt/vtt/json/md + metadata.json + images/ for /photo/ posts -> appends index.jsonl.
- Photo posts (/photo/ URLs): rewrites to /video/, transcribes audio, downloads slideshow images best-effort via public JS challenge solver.
- Output contract: stdout = data only (per-video `VIDEO_ID | source | cues=N | dir` lines for transcript; transcript.txt paths + summary for batch); stderr = all diagnostics; exit 0 = success (batch exits 1 only when nothing succeeded and at least one URL failed).
- Idempotent: skips when transcript.json exists; `--refresh` forces reprocess.
- Install: install.sh (curl|bash) auto-detects uv -> pipx -> pip --user. Flags: --version, --prefer uv|pipx|pip, --with-mlx, --verify, --uninstall, --quiet. Windows: install.ps1 via irm|iex. Manual: uv tool install / pipx install / pip install git+https://github.com/quangdang46/tiktok_cli. Extra `[mlx]` for Apple Silicon.
- Hero art: docs/assets/tiktok_cli_illustration.webp already exists — use it.
- License: MIT.
- Language: Vietnamese (repo docs are Vietnamese; keep Vietnamese).
- There is NO --easy-mode flag on install.sh — the curl line must be plain `| bash` (optionally document --verify). Do not claim easy-mode.
- Repo owner: quangdang46, repo: tiktok_cli.

Constraints:
1. HERO FIRST: H1, centered .webp in its own <div align="center">, badges in a SECOND separate <div align="center"> (platform, Python, License, Release), bold one-liner + expansion, centered curl install with ?$(date +%s) cache-bust above the fold.
2. Do NOT merge illustration + badges into one div.
3. Agent Quickstart goes AFTER hero but BEFORE TL;DR. Include stdout/stderr/exit contract, a suggested agent prompt blurb, and warn that `tiktok doctor`/`--help` are safe but there is no bare TUI.
4. TL;DR: Problem (concrete pains in operator language), Solution (what it does + key differentiator), "Why tiktok-cli?" feature table (5-10 rows), then a mandatory comparison table vs at least 2 alternatives (e.g. manual yt-dlp+whisper pipeline, gerardnico/transcribe, gallery-dl).
5. Quick Example: 8-15 annotated commands covering transcript, --whisper modes, photo post, batch, cache skip/--refresh, cookies fallback.
6. Commands section: table of the 3 live commands + shared option table; explicitly note suspended discovery commands under Limitations, not as commands.
7. Output structure: show the tiktok-transcripts/ artifact tree and index.jsonl fields + status values.
8. Design principles as a table (3-7 rows), not a numbered list.
9. Installation multi-path (curl, PowerShell, uv/pipx/pip, [mlx] extra). Honest about what install.sh flags exist.
10. Photo post section explaining /photo/ -> /video/ rewrite + image download being best-effort.
11. Troubleshooting as a table (Symptom -> Cause -> Fix), honest Limitations, FAQ with 5+ questions.
12. License: MIT badge only; short License section at the end is fine.
13. Voice: concrete, operator-dense, tables over essays, Vietnamese. No hype without commands. No "About Contributions" section.
14. 1-2 sentence origin/context line allowed only if it explains why the tool exists.
15. Length tier: Compact (~400-800 lines). Do not pad.

Show, don't tell. Every feature claim needs a command or table cell.
````
