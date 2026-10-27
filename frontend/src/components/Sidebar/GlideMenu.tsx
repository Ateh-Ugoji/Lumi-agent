import { useEffect, useRef, useState, type ReactNode } from "react";

type GlideMenuProps = {
  rowSelector?: string;
  highlightClassName?: string;
  className?: string;
  children: ReactNode;
};

export default function GlideMenu({
  rowSelector = "[data-row]",
  highlightClassName = "",
  className = "",
  children,
}: GlideMenuProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ top: number; height: number } | null>(
    null,
  );
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onOver = (event: Event) => {
      const target = (event.target as Element | null)?.closest?.(rowSelector);
      if (!target || !el.contains(target)) return;
      const row = target as HTMLElement;
      setBox({ top: row.offsetTop, height: row.offsetHeight });
      setVisible(true);
    };
    const onLeave = () => setVisible(false);
    el.addEventListener("mouseover", onOver);
    el.addEventListener("focusin", onOver);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      el.removeEventListener("mouseover", onOver);
      el.removeEventListener("focusin", onOver);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [rowSelector]);

  return (
    <div ref={containerRef} className={className} style={{ position: "relative" }}>
      <span
        aria-hidden
        className={highlightClassName}
        style={{
          position: "absolute",
          top: box?.top ?? 0,
          height: box?.height ?? 0,
          opacity: box && visible ? 1 : 0,
          pointerEvents: "none",
          transition:
            "top 220ms cubic-bezier(0.16,1,0.3,1), height 220ms cubic-bezier(0.16,1,0.3,1), opacity 150ms ease",
        }}
      />
      {children}
    </div>
  );
}
