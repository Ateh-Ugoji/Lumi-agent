/**
 * Smooth gradual reveal — pure math, no DOM, no rAF.
 *
 * Streamed replies are buffered in full (`target`); this engine decides how
 * many characters of it are visible after each animation frame. The React
 * layer (useSmoothText) owns the requestAnimationFrame loop and renders
 * `target.slice(0, count)`.
 *
 * Reveal speed adapts to the backlog (buffered but not yet shown characters):
 * slow and steady when the backlog is small, faster when it grows, capped so
 * it never dumps everything at once.
 */

// Characters/sec when the backlog is tiny.
export const BASE_CPS = 60;
// Extra chars/sec per character of backlog.
export const CATCHUP = 6;
// Hard cap — a large burst still finishes in a bounded time.
export const MAX_CPS = 1500;

/** Fractional reveal position. `last` = timestamp of the previous frame (ms), 0 = loop not running. */
export type RevealPos = { shown: number; last: number };

export type RevealStep = {
  pos: RevealPos;
  /** Whole characters safe to render (never splits a surrogate pair). */
  count: number;
  /** True when fully caught up — the caller should stop scheduling frames. */
  done: boolean;
};

export function initialRevealPos(): RevealPos {
  return { shown: 0, last: 0 };
}

/**
 * Advance one frame.
 *
 * - A *shorter* target than what's already shown means a new message replaced
 *   the old one mid-reveal: reset to 0 (no leftover text).
 * - When caught up, returns `done` with `last` reset to 0 so the next chunk
 *   restarts the loop with the default first-frame timestep.
 */
export function revealStep(pos: RevealPos, target: string, now: number): RevealStep {
  const len = target.length;

  if (len < pos.shown) {
    return { pos: initialRevealPos(), count: 0, done: false };
  }

  const dt = pos.last ? (now - pos.last) / 1000 : 0.016;
  const backlog = len - pos.shown;
  if (backlog <= 0) {
    return { pos: { shown: len, last: 0 }, count: len, done: true };
  }

  const cps = Math.min(MAX_CPS, BASE_CPS + backlog * CATCHUP);
  const shown = Math.min(len, pos.shown + cps * dt);

  // Don't stop mid-reveal inside a surrogate pair (emoji / astral chars).
  let n = Math.floor(shown);
  const code = target.charCodeAt(n - 1);
  if (code >= 0xd800 && code <= 0xdbff) n += 1;

  return { pos: { shown, last: now }, count: n, done: false };
}

/** Stop pressed / reveal abandoned: show everything received so far at once. */
export function flushReveal(target: string): RevealStep {
  return { pos: { shown: target.length, last: 0 }, count: target.length, done: true };
}
