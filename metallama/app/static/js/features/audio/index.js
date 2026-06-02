import { copyToClipboard } from "../../core/clipboard.js";
import { downloadMarkdownFile } from "../../core/download.js";
import { setConfigMessage } from "../../core/uiMessage.js";

const transcriptFormEl = document.getElementById("transcript-form");
const audioFileEl = document.getElementById("audio-file");
const fileLabelEl = document.querySelector(".service-audio .file-drop-label");
const languageEl = document.getElementById("transcript-language");
const timecodesEl = document.getElementById("timecodes");
const transcribeBtnEl = document.getElementById("transcribe-btn");
const transcriptOverlayEl = document.getElementById("transcript-overlay");
const transcriptStatusEl = document.getElementById("transcript-status");
const cancelTranscriptBtnEl = document.getElementById("cancel-transcript-btn");
const transcriptErrorEl = document.getElementById("transcript-error");
const transcriptLiveEl = document.getElementById("transcript-live");
const transcriptOutputSectionEl = document.getElementById("transcript-output-section");
const copyTranscriptBtnEl = document.getElementById("copy-transcript-btn");
const downloadTranscriptBtnEl = document.getElementById("download-transcript-btn");

let transcriptionInFlight = false;
let transcriptAbortController = null;

const FILE_ICON_SVG =
  '<svg class="file-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

function updateTranscriptStatus(statusText) {
  transcriptStatusEl.textContent = statusText || "Working...";
}

function setTranscriptionRunning(running) {
  transcriptionInFlight = running;
  transcribeBtnEl.disabled = running;
  audioFileEl.disabled = running;
  languageEl.disabled = running;
  timecodesEl.disabled = running;
  cancelTranscriptBtnEl.disabled = !running;
  transcriptOverlayEl.classList.toggle("is-hidden", !running);
}

function updateFileLabel() {
  const file = audioFileEl.files?.[0];
  if (file) {
    fileLabelEl.innerHTML = `${FILE_ICON_SVG} ${file.name}`;
    fileLabelEl.classList.add("file-selected");
  } else {
    fileLabelEl.textContent = "Drop audio file here or click to select";
    fileLabelEl.classList.remove("file-selected");
  }
}

function setTranscriptError(message = "") {
  if (!message) {
    transcriptErrorEl.textContent = "";
    transcriptErrorEl.classList.remove("visible");
    return;
  }

  transcriptErrorEl.textContent = message;
  transcriptErrorEl.classList.add("visible");
}

function updateTranscriptVisibility() {
  const hasText = Boolean((transcriptLiveEl.textContent || "").trim());
  transcriptOutputSectionEl.classList.toggle("is-hidden", !hasText);
}

export function setupTranscriptUI() {
  if (!transcriptFormEl) {
    return;
  }

  updateTranscriptVisibility();

  audioFileEl.addEventListener("change", updateFileLabel);

  const dropZone = transcriptFormEl.querySelector(".file-drop");
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (eventName === "drop") {
        const dt = event.dataTransfer;
        if (dt?.files?.length) {
          audioFileEl.files = dt.files;
          updateFileLabel();
        }
      }
      dropZone.classList.remove("drag-over");
    });
  });

  transcriptFormEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (transcriptionInFlight) {
      return;
    }

    const file = audioFileEl.files?.[0];
    if (!file) {
      setTranscriptError("Choose an audio file first");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("language", languageEl.value);
    formData.append("include_timecodes", String(Boolean(timecodesEl.checked)));

    transcriptLiveEl.textContent = "";
    setTranscriptError("");
    setTranscriptionRunning(true);
    updateTranscriptVisibility();
    updateTranscriptStatus("Uploading and preparing...");
    transcriptAbortController = new AbortController();

    try {
      const response = await fetch("/api/transcript/stream", {
        method: "POST",
        body: formData,
        signal: transcriptAbortController.signal,
      });

      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(text || `Request failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            continue;
          }

          let payload;
          try {
            payload = JSON.parse(trimmed);
          } catch {
            continue;
          }

          if (payload.event === "queued") {
            updateTranscriptStatus(payload.message || "Queued...");
          }

          if (payload.event === "status") {
            updateTranscriptStatus(payload.message || "Working...");
          }

          if (payload.event === "partial") {
            transcriptLiveEl.textContent = payload.text || "";
            updateTranscriptVisibility();
            updateTranscriptStatus(`Transcribing ${payload.chunk_index || ""}/${payload.chunk_total || ""}`);
          }

          if (payload.event === "done") {
            transcriptLiveEl.textContent = payload.text || "";
            updateTranscriptVisibility();
          }

          if (payload.event === "error") {
            throw new Error(payload.message || "Transcription failed");
          }
        }
      }
    } catch (err) {
      const message = err.name === "AbortError" ? "Transcription canceled" : err.message || "Transcription failed";
      setConfigMessage(message, true);
      setTranscriptError(message);
    } finally {
      transcriptAbortController = null;
      setTranscriptionRunning(false);
      updateTranscriptVisibility();
    }
  });

  cancelTranscriptBtnEl.addEventListener("click", () => {
    if (transcriptionInFlight && transcriptAbortController) {
      transcriptAbortController.abort();
    }
  });

  copyTranscriptBtnEl.addEventListener("click", async () => {
    const text = transcriptLiveEl.textContent || "";
    if (!text.trim()) {
      setConfigMessage("No transcript text to copy", true);
      return;
    }

    try {
      await copyToClipboard(text);
      setConfigMessage("Transcript copied");
    } catch (err) {
      setConfigMessage(err.message || "Copy failed", true);
    }
  });

  downloadTranscriptBtnEl.addEventListener("click", () => {
    const text = transcriptLiveEl.textContent || "";
    if (!text.trim()) {
      setConfigMessage("No transcript text to download", true);
      return;
    }

    downloadMarkdownFile(`transcript-${new Date().toISOString().slice(0, 10)}`, text);
    setConfigMessage("Transcript markdown downloaded");
  });
}
