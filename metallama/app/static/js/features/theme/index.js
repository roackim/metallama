const themeButtons = document.querySelectorAll(".theme-btn");
const THEME_KEY = "metallama.theme";

function getThemePreference() {
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark" || saved === "system") {
    return saved;
  }
  return "system";
}

function resolveSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function setupThemeSwitcher(onThemeApplied) {
  const applyTheme = (themePreference) => {
    const theme = themePreference === "system" ? resolveSystemTheme() : themePreference;
    document.documentElement.dataset.theme = theme;

    const titleLogo = document.getElementById("hero-logo");
    if (titleLogo) {
      titleLogo.src =
        theme === "dark" ? "/static/assets/logo-carre-blanc.svg" : "/static/assets/logo-carre-noir.svg";
    }

    themeButtons.forEach((button) => {
      const isActive = button.dataset.theme === themePreference;
      button.classList.toggle("active", isActive);
    });

    if (typeof onThemeApplied === "function") {
      onThemeApplied();
    }
  };

  const pref = getThemePreference();
  applyTheme(pref);

  themeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const nextTheme = button.dataset.theme;
      window.localStorage.setItem(THEME_KEY, nextTheme);
      applyTheme(nextTheme);
    });
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (getThemePreference() === "system") {
      applyTheme("system");
    }
  });
}
