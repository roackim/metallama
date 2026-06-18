import { copyToClipboard } from "./clipboard.js";

const uiMessageEl = document.getElementById("ui-message");

let _lastError = "";
let _errorTimeout = null;

export function setConfigMessage(msg, isError = false) {
  if (!uiMessageEl) return;

  uiMessageEl.textContent = msg;
  uiMessageEl.classList.toggle("error", isError);

  if (isError) {
    _lastError = String(msg || "");
    uiMessageEl.title = "Click to copy error details";
    uiMessageEl.style.cursor = "pointer";
    uiMessageEl.onclick = () => {
      if (_lastError) {
        copyToClipboard(_lastError);
        showTooltip("Copied!");
      }
    };
  } else {
    uiMessageEl.title = "";
    uiMessageEl.style.cursor = "";
    uiMessageEl.onclick = null;
  }

  // Auto-clear after a delay
  clearTimeout(_errorTimeout);
  _errorTimeout = setTimeout(() => {
    if (uiMessageEl.textContent === msg) {
      uiMessageEl.textContent = "";
      uiMessageEl.classList.remove("error");
      uiMessageEl.title = "";
      uiMessageEl.style.cursor = "";
      uiMessageEl.onclick = null;
    }
  }, isError ? 10000 : 4000);
}

function showTooltip(text) {
  if (!uiMessageEl) return;
  const original = uiMessageEl.textContent;
  uiMessageEl.textContent = text;
  uiMessageEl.classList.remove("error");
  setTimeout(() => {
    if (uiMessageEl.textContent === text) {
      uiMessageEl.textContent = original;
    }
  }, 1500);
}
