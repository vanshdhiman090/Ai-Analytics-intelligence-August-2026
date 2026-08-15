"use client";

import { useLayoutEffect, useState } from "react";

const STORAGE_KEY = "ai-analytics-theme";

function storedTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState("dark");

  useLayoutEffect(() => {
    const selected = storedTheme();
    document.documentElement.dataset.theme = selected;
    setTheme(selected);
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The visual theme still works when storage is unavailable.
    }
    setTheme(next);
  }

  const nextLabel = theme === "dark" ? "light" : "dark";
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${nextLabel} theme`}
      aria-pressed={theme === "light"}
      data-testid="theme-toggle"
    >
      <span className="theme-toggle-icon" aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
      <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
    </button>
  );
}
