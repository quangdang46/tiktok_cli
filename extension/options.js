const KEYS = ["groqApiKey", "geminiApiKey", "geminiModel", "groqModel", "summaryLanguage"];

const inputs = Object.fromEntries(KEYS.map((k) => [k, document.getElementById(k)]));

chrome.storage.local.get(KEYS, (stored) => {
  for (const k of KEYS) {
    if (inputs[k] && stored[k] != null) inputs[k].value = stored[k];
  }
});

document.getElementById("save").addEventListener("click", () => {
  const data = {};
  for (const k of KEYS) data[k] = inputs[k].value.trim();
  chrome.storage.local.set(data, () => {
    document.getElementById("status").textContent = "Đã lưu ✓";
    setTimeout(() => (document.getElementById("status").textContent = ""), 2000);
  });
});
