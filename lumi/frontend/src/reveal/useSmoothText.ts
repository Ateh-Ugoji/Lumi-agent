import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushReveal, initialRevealPos, revealStep, type RevealPos } from "./revealEngine";

/**
 * Buffer-and-reveal for streamed text.
 *
 * Never render `target` directly while `active`: incoming text goes into the
 * buffer (`target`), a separate counter (`shown`) says how many characters are
 * visible, and a requestAnimationFrame loop advances it at an adaptive speed
 * (see revealEngine). The caller renders `text` (= `target.slice(0, shown)`).
 *
 * - `active = false` (message not the freshly-streamed one, or reveal
 *   abandoned): show the full text instantly and cancel any running loop.
 * - `prefers-reduced-motion`: skip the animation, show text as it arrives.
 * - `flush()`: Stop pressed — show everything received so far at once.
 *
 * Returns `revealing` (loop has backlog) so the caller can pin auto-scroll
 * while the text grows and clear its "this message is revealing" flag when
 * the reveal settles.
 */
export function useSmoothText(target: string, active: boolean) {
  // Static messages (history, reloads) start fully shown — never a flash of
  // empty text while an effect catches up.
  const [shown, setShown] = useState(() => (active ? 0 : target.length));

  const targetRef = useRef(target);
  targetRef.current = target;

  const posRef = useRef<RevealPos>(initialRevealPos());
  const rafRef = useRef<number | null>(null);

  const reduceMotion = useMemo(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const stopLoop = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!active) {
      // Reveal abandoned (chat switched, message no longer current): cancel
      // and show everything — never leave a half-drawn message behind.
      stopLoop();
      posRef.current = { shown: target.length, last: 0 };
      setShown(target.length);
      return;
    }

    // New message started while the old one was still revealing (target got
    // shorter than what's shown): reset.
    if (target.length < posRef.current.shown) {
      posRef.current = initialRevealPos();
      setShown(0);
    }

    if (reduceMotion) {
      stopLoop();
      posRef.current = { shown: target.length, last: 0 };
      setShown(target.length);
      return;
    }

    if (rafRef.current !== null) return; // loop already running

    const tick = (now: number) => {
      const step = revealStep(posRef.current, targetRef.current, now);
      posRef.current = step.pos;
      setShown(step.count);
      if (step.done) {
        rafRef.current = null; // caught up; a new chunk will restart the loop
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [target, active, reduceMotion, stopLoop]);

  // Unmount: never leak a rAF callback.
  useEffect(() => stopLoop, [stopLoop]);

  const flush = useCallback(() => {
    stopLoop();
    const step = flushReveal(targetRef.current);
    posRef.current = step.pos;
    setShown(step.count);
  }, [stopLoop]);

  return {
    text: target.slice(0, shown),
    revealing: shown < target.length,
    flush,
  };
}
