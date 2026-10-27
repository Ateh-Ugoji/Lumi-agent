import { test } from "node:test";
import assert from "node:assert/strict";

import {
  BASE_CPS,
  CATCHUP,
  MAX_CPS,
  flushReveal,
  initialRevealPos,
  revealStep,
} from "../src/reveal/revealEngine.ts";

// A reveal loop driven by a fake clock, mirroring what useSmoothText does:
// run frames while `running`; a chunk that grows the target keeps/restarts
// the loop; `done` stops it until the next chunk arrives.
function runStream(
  chunks: { atMs: number; text: string }[],
  frameMs = 16.67,
) {
  let target = "";
  let pos = initialRevealPos();
  let running = false;
  let t = 0;
  let growIdx = 0;
  const counts: number[] = [];
  const atGrow: { targetLenBefore: number; shown: number }[] = [];
  let doneAtMs: number | null = null;

  const deadline = 120_000;
  while (t <= deadline) {
    while (growIdx < chunks.length && chunks[growIdx].atMs <= t) {
      atGrow.push({ targetLenBefore: target.length, shown: pos.shown });
      target += chunks[growIdx].text;
      growIdx += 1;
      if (!running) pos = { shown: pos.shown, last: 0 }; // effect restarts with default dt
    }
    if (!running && pos.shown < target.length) running = true;
    if (running) {
      const step = revealStep(pos, target, t);
      pos = step.pos;
      counts.push(step.count);
      if (step.done) running = false;
    }
    if (growIdx === chunks.length && !running && doneAtMs === null && target.length > 0) {
      doneAtMs = t;
      break;
    }
    t += frameMs;
  }
  return { target, pos, counts, atGrow, doneAtMs };
}

test("fast burst: 2,000 chars in one chunk reveal gradually, not instantly", () => {
  const target = "x".repeat(2000);
  let pos = initialRevealPos();

  // First frame shows only a small slice — the text must not appear at once.
  const first = revealStep(pos, target, 1000);
  assert.ok(first.count > 0, "first frame advances");
  assert.ok(first.count < 100, `first frame reveals a small slice, got ${first.count}`);

  // Drive frames at ~60fps until caught up.
  let t = 1000;
  let frames = 0;
  pos = first.pos;
  while (frames < 500) {
    const step = revealStep(pos, target, (t += 16.67));
    frames += 1;
    const prev = pos.shown;
    assert.ok(
      step.pos.shown >= prev,
      "reveal only moves forward",
    );
    pos = step.pos;
    if (step.done) {
      assert.equal(step.count, 2000, "finishes on the full text");
      break;
    }
  }

  const elapsedMs = frames * 16.67;
  assert.ok(elapsedMs <= 2000, `catch-up within a couple of seconds, took ${elapsedMs}ms`);
  assert.ok(elapsedMs > 300, `not instant (took ${elapsedMs}ms)`);
});

test("slow stream: one word every 300ms reveals smoothly with no stalls", () => {
  const words: { atMs: number; text: string }[] = [];
  for (let i = 0; i < 20; i += 1) {
    words.push({ atMs: 200 + i * 300, text: `word${i} ` });
  }
  const { counts, atGrow, pos, target, doneAtMs } = runStream(words);

  // Monotonic progress; per-frame advance bounded (no dumps, no stalls).
  let prev = 0;
  const maxFrame = Math.ceil(MAX_CPS * 0.01667) + 1;
  for (const count of counts) {
    assert.ok(count >= prev, "never goes backwards");
    assert.ok(count - prev <= maxFrame, `per-frame advance bounded, got ${count - prev}`);
    prev = count;
  }

  // Every word that arrived in time was fully revealed before the next one.
  for (const g of atGrow) {
    assert.ok(
      g.shown >= g.targetLenBefore,
      `caught up before next chunk (shown ${g.shown}, target was ${g.targetLenBefore})`,
    );
  }

  // After the last word the loop finishes on its own.
  assert.ok(doneAtMs !== null, "stream completes");
  assert.equal(pos.shown, target.length);
  assert.equal(counts[counts.length - 1], target.length);
  assert.ok(
    doneAtMs! > 200 + 19 * 300,
    "still animating after the final word arrived",
  );
});

test("stop mid-reveal: flush shows everything, then the loop stays stopped", () => {
  const target = "the reply I received so far ".repeat(10);
  let pos = revealStep(initialRevealPos(), target, 1000).pos;
  assert.ok(pos.shown > 0 && pos.shown < target.length, "mid-reveal");

  const flushed = flushReveal(target);
  assert.equal(flushed.count, target.length);
  assert.equal(flushed.done, true);

  // Subsequent frames keep reporting done — no further advancement is
  // scheduled (the hook cancels rAF and nothing re-arms it).
  const after = revealStep(flushed.pos, target, 1016);
  assert.equal(after.done, true);
  assert.equal(after.count, target.length);
  assert.equal(after.pos.shown, target.length);
  assert.equal(after.pos.last, 0, "loop state says stopped");

  const muchLater = revealStep(after.pos, target, 90_000);
  assert.equal(muchLater.done, true);
  assert.equal(muchLater.count, target.length);
});

test("a new (shorter) message while revealing resets — no leftover text", () => {
  const old = "the old reply that is still animating ".repeat(5);
  const pos = { shown: 50, last: 1000 };
  assert.ok(50 < old.length);

  const fresh = "short new reply";
  const reset = revealStep(pos, fresh, 1016); // fresh.length (15) < shown (50)
  assert.equal(reset.count, 0, "no leftover text from the old message");
  assert.equal(reset.pos.shown, 0);
  assert.equal(reset.done, false);

  // Reveals the new message from zero.
  let p = reset.pos;
  let guard = 0;
  while (guard < 500) {
    const step = revealStep(p, fresh, 1016 + guard * 16.67);
    p = step.pos;
    guard += 1;
    if (step.done) break;
  }
  assert.equal(p.shown, fresh.length);
});

test("emoji / astral chars are never split in half", () => {
  const target = "a\u{1F600}b"; // 😀 = surrogate pair at UTF-16 index 1..2

  // Exact-boundary case: floor(shown) lands on the HIGH surrogate (index 1).
  // Without the guard the visible text would end on a lone surrogate.
  const boundary = revealStep({ shown: 1, last: 1000 }, target, 1016);
  assert.equal(boundary.count, 3, "reveals the whole emoji, never half of it");

  // Sweep every fractional position: the rendered slice must never end on a
  // lone high surrogate.
  for (let shown = 0; shown <= target.length; shown += 0.25) {
    const step = revealStep({ shown, last: 1000 }, target, 1000); // dt = 0
    const visible = target.slice(0, step.count);
    const lastCode = visible.charCodeAt(visible.length - 1);
    assert.ok(
      !(lastCode >= 0xd800 && lastCode <= 0xdbff),
      `shown=${shown} produced a lone high surrogate at the end`,
    );
    assert.ok(step.count <= target.length, "never overruns the buffer");
  }
});

test("speed constants behave as specified", () => {
  // Tiny backlog -> slow base speed; large backlog -> capped catch-up.
  // (Compare per-frame ADVANCES — `count` equals the full length once a
  // step completes the reveal.)
  const len = 5000;
  const target = "y".repeat(len);
  const fast = revealStep({ shown: 0, last: 0 }, target, 1000); // first frame, dt = 0.016
  const slow = revealStep({ shown: len - 1, last: 0 }, target, 1000); // 1 char left
  assert.ok(
    fast.pos.shown > 10 * (len - slow.pos.shown),
    "bigger backlog advances much faster than a 1-char backlog",
  );
  const tiny = revealStep({ shown: 0, last: 0 }, "z".repeat(10), 1000);
  assert.ok(
    tiny.count <= Math.ceil((BASE_CPS + 10 * CATCHUP) * 0.016) + 1,
    "small backlog stays near BASE_CPS",
  );
});
