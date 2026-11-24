// TikTok Summarizer — content script.
// Injects a draggable floating bubble + panel on tiktok.com.
// Tap bubble → records the currently-playing video's audio via
// video.captureStream() + MediaRecorder → background sends it to
// Groq Whisper → Gemini summary → panel shows the result.
// Tap again while recording → stop & process.

(() => {
  if (window.__tiktokSummarizerLoaded) return;
  window.__tiktokSummarizerLoaded = true;

  const STAGE_LABELS = {
    transcribe: "Đang phiên âm (Whisper)…",
    summarize: "Đang tóm tắt (LLM)…",
  };

  // ---------- UI ----------
  const style = document.createElement("style");
  style.textContent = `
    #tts-bubble {
      position: fixed; right: 20px; bottom: 90px; z-index: 2147483646;
      width: 52px; height: 52px; border-radius: 50%;
      background: #fe2c55; color: #fff; border: 3px solid #fff;
      box-shadow: 0 4px 16px rgba(0,0,0,.4); cursor: grab;
      display: flex; align-items: center; justify-content: center;
      font-size: 22px; user-select: none; touch-action: none;
    }
    #tts-bubble.tts-rec { animation: tts-rec 1s infinite alternate; }
    #tts-bubble.tts-dragging { cursor: grabbing; }
    @keyframes tts-rec { from { transform: scale(1); } to { transform: scale(1.15); box-shadow: 0 0 0 8px rgba(254,44,85,.25); } }
    #tts-panel {
      position: fixed; right: 16px; bottom: 16px; z-index: 2147483647;
      width: 380px; max-width: calc(100vw - 32px); max-height: 70vh;
      background: #121212; color: #eee; border-radius: 14px;
      border: 1px solid #333; box-shadow: 0 12px 40px rgba(0,0,0,.6);
      display: none; flex-direction: column; overflow: hidden;
      font-family: -apple-system, "Segoe UI", Roboto, sans-serif; font-size: 14px;
    }
    #tts-panel.tts-open { display: flex; }
    #tts-panel .tts-head {
      display: flex; align-items: center; justify-content: space-between;
      padding: 10px 14px; background: #1e1e1e; border-bottom: 1px solid #333;
    }
    #tts-panel .tts-head b { font-size: 14px; }
    #tts-panel .tts-close { background: none; border: none; color: #aaa; font-size: 18px; cursor: pointer; }
    #tts-panel .tts-body { padding: 14px; overflow-y: auto; white-space: pre-wrap; line-height: 1.5; }
    #tts-panel .tts-status { color: #aaa; font-style: italic; }
    #tts-panel .tts-error { color: #ff6b6b; }
    #tts-panel .tts-recbtn {
      display: inline-block; margin-top: 10px; padding: 8px 14px;
      background: #fe2c55; color: #fff; border: none; border-radius: 8px;
      font-size: 13px; cursor: pointer;
    }
    #tts-panel details { margin-top: 10px; color: #999; font-size: 12px; }
    #tts-panel summary { cursor: pointer; }
  `;
  document.documentElement.appendChild(style);

  const bubble = document.createElement("div");
  bubble.id = "tts-bubble";
  bubble.textContent = "⏺";
  document.body.appendChild(bubble);

  const panel = document.createElement("div");
  panel.id = "tts-panel";
  panel.innerHTML = `
    <div class="tts-head">
      <b>Tóm tắt TikTok</b>
      <button class="tts-close" title="Đóng">✕</button>
    </div>
    <div class="tts-body"></div>
  `;
  document.body.appendChild(panel);

  const bodyEl = panel.querySelector(".tts-body");
  panel.querySelector(".tts-close").addEventListener("click", () => {
    panel.classList.remove("tts-open");
  });

  // ---------- Drag ----------
  let dragging = false, moved = false, startX, startY, origX, origY;
  bubble.addEventListener("pointerdown", (e) => {
    dragging = true; moved = false;
    startX = e.clientX; startY = e.clientY;
    const r = bubble.getBoundingClientRect();
    origX = r.left; origY = r.top;
    bubble.classList.add("tts-dragging");
    bubble.setPointerCapture(e.pointerId);
  });
  bubble.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX, dy = e.clientY - startY;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    bubble.style.left = `${Math.max(0, origX + dx)}px`;
    bubble.style.top = `${Math.max(0, origY + dy)}px`;
    bubble.style.right = "auto"; bubble.style.bottom = "auto";
  });
  bubble.addEventListener("pointerup", () => {
    dragging = false;
    bubble.classList.remove("tts-dragging");
    if (!moved) onBubbleClick();
  });

  // ---------- Video detection ----------
  function activeVideo() {
    const videos = [...document.querySelectorAll("video")];
    if (!videos.length) return null;
    // prefer playing + largest visible
    let best = null, bestScore = -1;
    for (const v of videos) {
      const r = v.getBoundingClientRect();
      const visible = r.bottom > 0 && r.top < innerHeight && r.width > 0;
      if (!visible) continue;
      const score = r.width * r.height + (v.paused ? 0 : 1e9);
      if (score > bestScore) { bestScore = score; best = v; }
    }
    return best || videos[0];
  }

  function videoMeta(v) {
    // best-effort title/author from DOM
    const wrap = v.closest("div");
    let node = v;
    for (let i = 0; i < 12 && node; i++, node = node.parentElement) {
      const h = node.querySelector?.('h1, [data-e2e="browse-video-desc"], [data-e2e="video-desc"]');
      if (h?.textContent?.trim()) {
        return { desc: h.textContent.trim().slice(0, 300), author: "" };
      }
    }
    return { desc: "", author: "" };
  }

  // ---------- Recording ----------
  let recorder = null;
  let chunks = [];
  let state = "idle"; // idle | recording | processing

  function setBody(html) { bodyEl.innerHTML = html; }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function startRecording() {
    const v = activeVideo();
    if (!v) {
      setBody(`<div class="tts-error">Không tìm thấy thẻ &lt;video&gt; nào trên trang.</div>`);
      return;
    }
    const stream = v.captureStream ? v.captureStream() : v.mozCaptureStream?.();
    if (!stream) {
      setBody(`<div class="tts-error">Trình duyệt không hỗ trợ ghi âm từ video.</div>`);
      return;
    }
    const audioTracks = stream.getAudioTracks();
    if (!audioTracks.length) {
      setBody(`<div class="tts-error">Video không có track audio (hoặc đang bị chặn).</div>`);
      return;
    }
    const audioStream = new MediaStream(audioTracks);
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
      .find((t) => MediaRecorder.isTypeSupported(t)) || "";
    try {
      recorder = mime
        ? new MediaRecorder(audioStream, { mimeType: mime, audioBitsPerSecond: 32000 })
        : new MediaRecorder(audioStream);
    } catch (e) {
      setBody(`<div class="tts-error">Không tạo được bộ ghi âm: ${escapeHtml(e.message)}</div>`);
      return;
    }
    chunks = [];
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = onRecordingDone;
    recorder.start(1000);
    state = "recording";
    bubble.classList.add("tts-rec");
    const meta = videoMeta(v);
    setBody(
      `<div class="tts-status">🔴 Đang ghi audio video${meta.desc ? " — " + escapeHtml(meta.desc.slice(0, 80)) : ""}<br>` +
      `Bấm bubble lần nữa để dừng &amp; tóm tắt. (video cần đang phát tiếng)</div>`
    );
  }

  async function onRecordingDone() {
    const blob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
    const meta = videoMeta(activeVideo() || document.createElement("video"));
    state = "processing";
    bubble.classList.remove("tts-rec");
    setBody(`<div class="tts-status">Đang gửi audio lên Whisper…</div>`);

    const port = chrome.runtime.connect({ name: "sum" });
    port.onMessage.addListener((msg) => {
      if (msg.stage) {
        setBody(`<div class="tts-status">${STAGE_LABELS[msg.stage] || msg.stage}…</div>`);
      } else if (msg.ok) {
        const transcriptBlock = msg.transcript
          ? `<details><summary>Xem bản ghi lời (transcript)</summary>${escapeHtml(msg.transcript)}</details>`
          : "";
        setBody(
          `<div>${escapeHtml(msg.summary)}</div>${transcriptBlock}` +
          (meta.desc ? `<div style="margin-top:8px;color:#666;font-size:12px">${escapeHtml(meta.desc)}</div>` : "")
        );
        state = "idle";
      } else {
        setBody(`<div class="tts-error">${escapeHtml(msg.error || "Lỗi không xác định")}</div>`);
        state = "idle";
      }
    });
    port.onDisconnect.addListener(() => {
      if (state === "processing") {
        setBody(`<div class="tts-error">Kết nối bị ngắt. Thử lại nhé.</div>`);
        state = "idle";
      }
    });
    // send blob as arrayBuffer (ports don't support Blob directly in all versions)
    const buf = await blob.arrayBuffer();
    port.postMessage({ type: "SUMMON", audio: buf, mimeType: blob.type, meta });
  }

  function onBubbleClick() {
    panel.classList.add("tts-open");
    if (state === "recording") {
      try { recorder?.stop(); } catch {}
      state = "processing";
    } else if (state === "idle") {
      setBody(`<div class="tts-status">Nhấn để bắt đầu ghi audio video đang phát…</div>`);
      startRecording();
    }
    // processing: ignore
  }
})();
