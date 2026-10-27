import { useEffect, useMemo, useRef, useState } from "react";
import usePrefersReducedMotion from "./usePrefersReducedMotion";
import styles from "./AgentThinking.module.css";

/**
 * WorkingMark — a sprite-strip flipbook, ported from the logic of Claude's
 * `data-cds="WorkingMark"` (their markup: a 20px window with a tall vertical
 * strip behind it; frames advance by stepping `translateY` on the strip).
 *
 * Two rules follow their structure exactly:
 *   1. EVERY sheet is mounted up front and painted at `opacity: 0.001`
 *      (decoded, invisible); only the active sheet gets `z-index: 1` +
 *      `will-change: transform`. Swapping which animation plays is instant —
 *      nothing has to load or decode at swap time.
 *   2. Frame advance is a transform on the inner strip inside an
 *      `overflow: clip` window — no layout, no repaint of the sheet itself.
 *
 * The artwork is OURS, drawn on a canvas into a PNG strip (the original's
 * base64 frames are Anthropic's assets and are not copied). Reduced motion
 * freezes on frame 0.
 */

export type WorkingMarkVariant = "busy" | "calm";

const FRAME_PX = 20; // logical frame size (matches their size-icon box)
const SHEET_FRAMES: Record<WorkingMarkVariant, number> = { busy: 24, calm: 16 };
const SHEET_FPS: Record<WorkingMarkVariant, number> = { busy: 12, calm: 8 };

type DrawFn = (
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  t: number,
) => void;

/** Renders a vertical strip: one canvas, `frames` cells stacked top to bottom. */
function makeStrip(draw: DrawFn, frames: number): string {
  if (typeof document === "undefined") return "";
  const scale = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
  const px = Math.round(FRAME_PX * scale);
  const canvas = document.createElement("canvas");
  canvas.width = px;
  canvas.height = px * frames;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (let f = 0; f < frames; f++) {
    ctx.save();
    ctx.translate(0, f * px);
    ctx.scale(scale, scale);
    draw(ctx, FRAME_PX, FRAME_PX, f / frames);
    ctx.restore();
  }
  return canvas.toDataURL("image/png");
}

/**
 * Breathing clay orb — our own artwork in the spirit of the reference's
 * `--cds-clay` mark: a CRISP two-tone disc (no glow halo — at 20px a halo
 * reads as a fuzzy blob), radius pulsing over the loop, with an orbiting
 * satellite dot on the "busy" sheet.
 */
function makeOrbDraw(opts: { orbit: boolean; deep: boolean }): DrawFn {
  return (ctx, w, h, t) => {
    const cx = w / 2;
    const cy = h / 2;
    const wave = Math.sin(t * Math.PI * 2); // -1..1 across one loop
    const amplitude = opts.deep ? 0.14 : 0.22;
    const breathe = (opts.deep ? 0.9 : 0.94) + amplitude * wave;
    const r = w * 0.3 * breathe;
    const hue = 14 + (opts.deep ? -4 : 6) * wave; // clay family (~#d97757)

    // Crisp shaded disc — hard edge, two stops, nothing translucent outside it.
    const grad = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    grad.addColorStop(0, `hsl(${hue}, 78%, 66%)`);
    grad.addColorStop(1, `hsl(${hue}, 74%, 50%)`);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();

    // Lit highlight — keeps it reading as a sphere without a glow.
    ctx.fillStyle = `hsla(${hue + 10}, 92%, 86%, ${opts.deep ? 0.55 : 0.8})`;
    ctx.beginPath();
    ctx.arc(cx - r * 0.26, cy - r * 0.3, r * 0.3, 0, Math.PI * 2);
    ctx.fill();

    // Orbiting satellite dot — the "life" in the loop (busy sheet only)
    if (opts.orbit) {
      const a = t * Math.PI * 2;
      const dx = cx + Math.cos(a) * w * 0.38;
      const dy = cy + Math.sin(a) * w * 0.38 * 0.72;
      const alpha = 0.55 + 0.35 * Math.abs(Math.sin(a));
      ctx.fillStyle = `hsla(${hue + 8}, 88%, 76%, ${alpha})`;
      ctx.beginPath();
      ctx.arc(dx, dy, w * 0.06, 0, Math.PI * 2);
      ctx.fill();
    }
  };
}

let stripCache: Record<WorkingMarkVariant, string> | null = null;

function getStrips(): Record<WorkingMarkVariant, string> {
  if (!stripCache) {
    stripCache = {
      busy: makeStrip(makeOrbDraw({ orbit: true, deep: false }), SHEET_FRAMES.busy),
      calm: makeStrip(makeOrbDraw({ orbit: false, deep: true }), SHEET_FRAMES.calm),
    };
  }
  return stripCache;
}

export type WorkingMarkProps = {
  /** Window size in CSS px (header 17, row 12). */
  size?: number;
  variant?: WorkingMarkVariant;
  /** False = hold on frame 0 (settled rows, reduced motion). */
  running?: boolean;
  className?: string;
};

export default function WorkingMark({
  size = 20,
  variant = "busy",
  running = true,
  className,
}: WorkingMarkProps) {
  const reduced = usePrefersReducedMotion();
  const [frame, setFrame] = useState(0);
  const strips = useMemo(getStrips, []);

  const active = running && !reduced;
  const frames = SHEET_FRAMES[variant];

  // rAF with time accumulation → frame stepping at the sheet's own fps.
  useEffect(() => {
    if (!active) {
      setFrame(0);
      return;
    }
    const period = 1000 / SHEET_FPS[variant];
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const tick = (now: number) => {
      acc += now - last;
      last = now;
      while (acc >= period) {
        acc -= period;
        setFrame((f) => (f + 1) % SHEET_FRAMES[variant]);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, variant]);

  const variants: WorkingMarkVariant[] = ["busy", "calm"];

  return (
    <span
      className={`${styles.markWindow} ${className ?? ""}`}
      style={{ width: size, height: size }}
      data-variant={variant}
      aria-hidden="true"
    >
      {/* Claude's ClayMark base: a solid 7px-at-20px dot under the sprite,
          so the mark never disappears between frames. */}
      <span
        className={styles.markDot}
        style={{
          width: Math.max(5, Math.round(size * 0.35)),
          height: Math.max(5, Math.round(size * 0.35)),
        }}
      />
      {variants.map((v) => {
        const isActive = v === variant;
        const n = SHEET_FRAMES[v];
        return (
          <span
            key={v}
            className={styles.markSheet}
            data-active={isActive ? "on" : undefined}
            style={{
              opacity: isActive ? 1 : 0.001,
              zIndex: isActive ? 1 : undefined,
              willChange: isActive ? "transform" : undefined,
            }}
          >
            <span
              className={styles.markStrip}
              style={{
                backgroundImage: strips[v] ? `url(${strips[v]})` : undefined,
                height: n * size,
                transform: `translateY(${-(isActive ? frame : 0) * size}px)`,
              }}
            />
          </span>
        );
      })}
    </span>
  );
}
