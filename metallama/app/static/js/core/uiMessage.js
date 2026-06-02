const uiMessageEl = document.getElementById("ui-message");

export function setConfigMessage(msg, isError = false) {
  if (!uiMessageEl) {
    return;
  }
  uiMessageEl.textContent = msg;
  uiMessageEl.classList.toggle("error", isError);
}
