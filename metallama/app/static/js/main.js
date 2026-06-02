import { setConfigMessage } from "./core/uiMessage.js";
import { setupTranscriptUI } from "./features/audio/index.js";
import { setupModels, refreshModels } from "./features/models/index.js";
import { setupOcrUI } from "./features/ocr/index.js";
import { refreshRam, refreshRamGraph, refreshVram, refreshVramGraph } from "./features/system/index.js";
import { setupThemeSwitcher } from "./features/theme/index.js";

async function init() {
  setupThemeSwitcher(() => {
    refreshVramGraph().catch(() => {});
    refreshRamGraph().catch(() => {});
  });

  setupModels();
  setupTranscriptUI();
  setupOcrUI();

  await refreshModels();
  await refreshVram();
  await refreshRam();
  await refreshVramGraph();
  await refreshRamGraph();

  setInterval(() => {
    refreshModels().catch(() => {});
  }, 2000);

  setInterval(() => {
    refreshVram().catch(() => {});
    refreshRam().catch(() => {});
    refreshVramGraph().catch(() => {});
    refreshRamGraph().catch(() => {});
  }, 1000);
}

init().catch((err) => {
  setConfigMessage(err.message || "Initialization failed", true);
});
