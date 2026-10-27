export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  if (total < 60) {
    return `${total} second${total === 1 ? "" : "s"}`;
  }
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  const min = `${minutes} minute${minutes === 1 ? "" : "s"}`;
  if (seconds === 0) return min;
  return `${min} ${seconds} second${seconds === 1 ? "" : "s"}`;
}
