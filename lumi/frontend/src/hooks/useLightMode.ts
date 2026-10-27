import { useEffect, useState } from "react";

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
  };
  const toggle = () => set(!document.body.classList.contains("light"));
  return { light, toggle, set };
}
