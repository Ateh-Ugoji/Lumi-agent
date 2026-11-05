import type { ProfileSummary } from "../api/profiles.ts";

/** The stored id if it still exists, else the first profile, else null. */
export function pickActiveId(profiles: ProfileSummary[], stored: number | null): number | null {
  if (stored !== null && profiles.some((p) => p.id === stored)) return stored;
  return profiles[0]?.id ?? null;
}
