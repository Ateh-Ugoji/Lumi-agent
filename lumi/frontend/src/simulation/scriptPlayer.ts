import type { SimScript } from "./simScripts";

export type Rng = () => number;

export const STEP_FLOOR_MS = 600;
export const JITTER_RATIO = 0.15;

export function jitterDuration(baseMs: number, rng: Rng = Math.random): number {
  const factor = 1 - JITTER_RATIO + rng() * 2 * JITTER_RATIO;
  return Math.max(STEP_FLOOR_MS, Math.round(baseMs * factor));
}

export type Timeline = {
  starts: number[];
  durations: number[];
  finalDelayMs: number;
  totalMs: number;
};

export function buildTimeline(
  script: SimScript,
  rng: Rng = Math.random,
): Timeline {
  const durations = script.steps.map((s) => jitterDuration(s.durationMs, rng));
  const starts: number[] = [];
  let cursor = 0;
  for (const d of durations) {
    starts.push(cursor);
    cursor += d;
  }
  return {
    starts,
    durations,
    finalDelayMs: script.finalDelayMs,
    totalMs: cursor + script.finalDelayMs,
  };
}

export type PlayerState = {
  status: "running" | "done";
  index: number;
  startedCount: number;
};

export function stateAt(timeline: Timeline, elapsedMs: number): PlayerState {
  const count = timeline.durations.length;
  if (count === 0 || elapsedMs >= timeline.totalMs) {
    return { status: "done", index: count - 1, startedCount: count };
  }
  let index = 0;
  for (let i = 0; i < timeline.starts.length; i++) {
    if (elapsedMs >= timeline.starts[i]) index = i;
    else break;
  }
  return { status: "running", index, startedCount: index + 1 };
}
