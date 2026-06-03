import { setConfigMessage } from "./core/uiMessage.js";
import { setupModels, refreshModels } from "./features/models/index.js";
import { refreshRam, refreshRamGraph, refreshVram, refreshVramGraph } from "./features/system/index.js";
import { setupThemeSwitcher } from "./features/theme/index.js";

async function init() {
  setupThemeSwitcher(() => {
    refreshVramGraph().catch(() => {});
    refreshRamGraph().catch(() => {});
  });

  setupModels();

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
