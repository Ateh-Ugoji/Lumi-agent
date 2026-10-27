import { useEffect, useState } from "react";
import type { SimScript } from "./simScripts";
import { buildTimeline, stateAt } from "./scriptPlayer";

export type SimRunInput = {
  script: SimScript;
  runId: number;
};

export type SimRunState = {
  runId: number;
  status: "idle" | "running" | "done";
  elapsedMs: number;
  index: number;
  startedCount: number;
};

const IDLE: SimRunState = {
  runId: -1,
  status: "idle",
  elapsedMs: 0,
  index: -1,
  startedCount: 0,
};

export function useSimulatedRun(run: SimRunInput | null): SimRunState {
  const [state, setState] = useState<SimRunState>(IDLE);
  const runId = run?.runId ?? -1;

  useEffect(() => {
    if (!run) {
      setState(IDLE);
      return;
    }
    const timeline = buildTimeline(run.script);
    const startedAt = performance.now();
    const timeouts: number[] = [];

    const apply = (elapsed: number) => {
      const s = stateAt(timeline, elapsed);
      setState({
        runId: run.runId,
        status: s.status,
        elapsedMs: elapsed,
        index: s.index,
        startedCount: s.startedCount,
      });
    };

    apply(0);
    for (let i = 1; i < timeline.starts.length; i++) {
      const at = timeline.starts[i];
      timeouts.push(
        window.setTimeout(() => apply(performance.now() - startedAt), at),
      );
    }
    timeouts.push(
      window.setTimeout(() => apply(timeline.totalMs), timeline.totalMs),
    );

    return () => {
      for (const t of timeouts) window.clearTimeout(t);
    };
  }, [runId]);

  return state;
}
