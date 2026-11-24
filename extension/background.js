// TikTok Summarizer — background service worker.
// Receives recorded audio (webm/opus) from the content script,
// transcribes via Groq Whisper, summarizes via Gemini.

const DEFAULTS = {
  groqApiKey: "",
  geminiApiKey: "",
  geminiModel: "gemini-2.5-flash-lite",
  groqModel: "whisper-large-v3-turbo",
  summaryLanguage: "Tiếng Việt",
};

async function getSettings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...stored };
}

const EXT_FOR_MIME = {
  "audio/webm": "audio.webm",
  "audio/mp4": "audio.mp4",
  "audio/ogg": "audio.ogg",
  "audio/wav": "audio.wav",
};

async function transcribe(buf, mimeType, settings) {
  const blob = new Blob([buf], { type: mimeType || "audio/webm" });
  const form = new FormData();
  form.append("file", blob, EXT_FOR_MIME[mimeType] || "audio.webm");
  form.append("model", settings.groqModel);
  form.append("response_format", "verbose_json");
  const res = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
    method: "POST",
    headers: { Authorization: `Bearer ${settings.groqApiKey}` },
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Groq STT failed: HTTP ${res.status} ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return data.text || (data.segments || []).map((s) => s.text).join(" ");
}

async function summarize(transcript, meta, settings) {
  const prompt = [
    `You are summarizing a TikTok video for a viewer who wants the key points fast.`,
    meta?.desc ? `Video caption: "${meta.desc}"` : "",
    ``,
    `Transcript:`,
    transcript.slice(0, 24000),
    ``,
    `Respond IN ${settings.summaryLanguage}. Format:`,
    `- One-line gist (1 sentence)`,
    `- Key points (3-6 bullets)`,
    `- Tone/topic tags (3-5 words)`,
  ].filter(Boolean).join("\n");

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${settings.geminiModel}:generateContent?key=${settings.geminiApiKey}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.3 },
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Gemini failed: HTTP ${res.status} ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return data?.candidates?.[0]?.content?.parts?.map((p) => p.text).join("") || "";
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "sum") return;
  port.onMessage.addListener((msg) => {
    if (msg?.type !== "SUMMON" || !msg.audio) return;
    (async () => {
      const send = (payload) => {
        try { port.postMessage(payload); } catch {}
      };
      try {
        const settings = await getSettings();
        if (!settings.groqApiKey) throw new Error("Missing Groq API key — open extension options.");
        if (!settings.geminiApiKey) throw new Error("Missing Gemini API key — open extension options.");

        send({ stage: "transcribe" });
        const transcript = await transcribe(msg.audio, msg.mimeType, settings);
        if (!transcript.trim()) throw new Error("Transcription empty — video likely has no speech.");

        send({ stage: "summarize" });
        const summary = await summarize(transcript, msg.meta, settings);

        send({ ok: true, summary, transcript });
      } catch (err) {
        send({ ok: false, error: String(err?.message || err) });
      }
    })();
  });
});
