/**
 * Compact elapsed-time readout for the live thinking header (e.g. `47s`, `1m 07s`).
 * Deliberately separate from `simulation/formatDuration.ts` (that one spells out
 * "47 seconds" for the settled "Thought for …" line and its tests lock that shape).
 * Non-negative: a clock never counts backwards.
 */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return minutes > 0
    ? `${minutes}m ${String(seconds).padStart(2, "0")}s`
    : `${seconds}s`;
}
