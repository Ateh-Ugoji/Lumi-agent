import { useEffect, useState } from "react";

const STORAGE_KEY = "lumi:light";

/**
 * Light (white) is the default theme. Call once at startup, before React
 * renders, so the page never flashes dark first.
 */
export function applyStoredLightMode() {
  const stored = localStorage.getItem(STORAGE_KEY);
  const light = stored === null ? true : stored === "true";
  document.body.classList.toggle("light", light);
}

export function useLightMode() {
  const [light, setLight] = useState(() =>
    document.body.classList.contains("light"),
  );
  useEffect(() => {
    const update = () => setLight(document.body.classList.contains("light"));
    const observer = new MutationObserver(update);
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);
  const set = (next: boolean) => {
    document.body.classList.toggle("light", next);
    localStorage.setItem(STORAGE_KEY, String(next));
  };
  const toggle = () => set(!document.body.classList.contains("light"));
  return { light, toggle, set };
}
