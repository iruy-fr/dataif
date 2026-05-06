import { createContext, useContext, useEffect, useState } from "react";

const ThemeContext = createContext(undefined);

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "ui-theme",
  darkModeClass = "dark-mode",
}) {
  const [theme, setTheme] = useState(() => {
    if (typeof window !== "undefined") {
      const savedTheme = window.localStorage.getItem(storageKey);
      return savedTheme || defaultTheme;
    }

    return defaultTheme;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    function applyTheme() {
      const root = window.document.documentElement;

      if (theme === "system") {
        const systemTheme = mediaQuery.matches ? "dark" : "light";
        root.classList.toggle(darkModeClass, systemTheme === "dark");
        window.localStorage.removeItem(storageKey);
        return;
      }

      root.classList.toggle(darkModeClass, theme === "dark");
      window.localStorage.setItem(storageKey, theme);
    }

    function handleSystemThemeChange() {
      if (theme === "system") {
        applyTheme();
      }
    }

    applyTheme();
    mediaQuery.addEventListener("change", handleSystemThemeChange);

    return () => {
      mediaQuery.removeEventListener("change", handleSystemThemeChange);
    };
  }, [darkModeClass, storageKey, theme]);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);

  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }

  return context;
}
