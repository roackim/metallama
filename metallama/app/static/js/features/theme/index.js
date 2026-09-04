export function setupThemeSwitcher(onThemeApplied) {
  document.documentElement.dataset.theme = "dark";
  if (typeof onThemeApplied === "function") {
    onThemeApplied();
  }
}
