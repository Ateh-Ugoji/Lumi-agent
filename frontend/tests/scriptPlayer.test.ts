import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildTimeline,
  jitterDuration,
  stateAt,
  STEP_FLOOR_MS,
  JITTER_RATIO,
} from "../src/simulation/scriptPlayer.ts";
import type { SimScript } from "../src/simulation/simScripts.ts";

const makeScript = (
  durations: number[],
  finalDelayMs = 300,
): SimScript => ({
  id: "test",
  finalDelayMs,
  steps: durations.map((durationMs, i) => ({
    id: `s${i}`,
    label: `Step ${i}`,
    kind: "analysis",
    durationMs,
  })),
});

test("jitterDuration stays within ±15% and never drops below the floor", () => {
  assert.equal(jitterDuration(1000, () => 0), 850);
  assert.equal(jitterDuration(1000, () => 1), 1150);
  assert.equal(jitterDuration(1000, () => 0.5), 1000);
  assert.equal(jitterDuration(500, () => 1), STEP_FLOOR_MS);
  assert.equal(jitterDuration(100, () => 0), STEP_FLOOR_MS);
  for (const r of [0, 0.1, 0.33, 0.5, 0.77, 1]) {
    const d = jitterDuration(2000, () => r);
    assert.ok(d >= 2000 * (1 - JITTER_RATIO) - 1);
    assert.ok(d <= 2000 * (1 + JITTER_RATIO) + 1);
    assert.ok(d >= STEP_FLOOR_MS);
  }
});

test("buildTimeline is cumulative and includes the final delay", () => {
  const script = makeScript([1000, 700, 600], 300);
  const timeline = buildTimeline(script, () => 0.5);
  assert.deepEqual(timeline.durations, [1000, 700, 600]);
  assert.deepEqual(timeline.starts, [0, 1000, 1700]);
  assert.equal(timeline.finalDelayMs, 300);
  assert.equal(timeline.totalMs, 2600);
});

test("buildTimeline applies the 600ms floor per step", () => {
  const script = makeScript([100, 10000], 0);
  const timeline = buildTimeline(script, () => 1);
  assert.equal(timeline.durations[0], STEP_FLOOR_MS);
  assert.equal(timeline.durations[1], 11500);
  assert.equal(timeline.totalMs, STEP_FLOOR_MS + 11500);
});

test("stateAt walks through steps in order", () => {
  const timeline = buildTimeline(makeScript([1000, 700, 600], 300), () => 0.5);

  assert.deepEqual(stateAt(timeline, 0), {
    status: "running",
    index: 0,
    startedCount: 1,
  });
  assert.deepEqual(stateAt(timeline, 999), {
    status: "running",
    index: 0,
    startedCount: 1,
  });
  assert.deepEqual(stateAt(timeline, 1000), {
    status: "running",
    index: 1,
    startedCount: 2,
  });
  assert.deepEqual(stateAt(timeline, 1700), {
    status: "running",
    index: 2,
    startedCount: 3,
  });
  assert.deepEqual(stateAt(timeline, 2599), {
    status: "running",
    index: 2,
    startedCount: 3,
  });
  assert.deepEqual(stateAt(timeline, 2600), {
    status: "done",
    index: 2,
    startedCount: 3,
  });
  assert.deepEqual(stateAt(timeline, 999999), {
    status: "done",
    index: 2,
    startedCount: 3,
  });
});

test("stateAt reports done immediately for an empty script", () => {
  const timeline = buildTimeline(makeScript([], 0), () => 0.5);
  assert.deepEqual(stateAt(timeline, 0), {
    status: "done",
    index: -1,
    startedCount: 0,
  });
});
