import { request } from "./http.ts";

// The composer's @-handle dropdown. Served by /api/v1/handles/*: local rows first, then the
// remembered store, the 60-minute cache and, last, a budget-guarded Xpoz query.

export type HandleRow = {
  handle: string;
  display_name?: string;
  avatar_url?: string;
  followers?: number | null;
  /** The network of this row (x, instagram, ...). Every row of /handles/search and /saved has it. */
  platform?: string;
  /** db | cache | live: where the data came from on that search */
  source?: string;
};

export type HandleSearchResponse = {
  query: string;
  results: HandleRow[];
  live: boolean;
  refreshed: boolean;
  reason?: string | null;
  context?: string;
};

/**
 * The network the composer asks about. The server has no default: `platforms` is required on
 * /handles/search and /handles/saved and `platform` on /handles/select (400 without it). The
 * composer only searches X today, so every call names it explicitly.
 */
export const HANDLE_PLATFORM = "x";

export function searchHandles(q: string, context = ""): Promise<HandleSearchResponse> {
  return request<HandleSearchResponse>("/handles/search", {
    query: { q, context, platforms: HANDLE_PLATFORM },
  });
}

/** Instant-suggest snapshot. The composer prefix-filters it in the browser: 0 ms, 0 credits. */
export async function getSavedHandles(): Promise<HandleRow[]> {
  try {
    const payload = await request<{ results?: HandleRow[] }>("/handles/saved", {
      query: { platforms: HANDLE_PLATFORM },
    });
    return payload.results ?? [];
  } catch {
    return []; // no snapshot means no instant paint, never an error in the composer
  }
}

/**
 * Tell the server which handle was picked, so it joins the user's saved list. Only the handle and
 * its network go: the row's own `platform`, or the network the composer searched when the row
 * carries none (the server requires one). Nothing else goes:
 * the photo, name and followers stay in this browser's search state and are never sent back,
 * because the server shares what it stores with every user and takes those only from the provider.
 * Best effort: it never blocks the composer.
 */
export async function selectHandle(row: HandleRow): Promise<void> {
  try {
    await request<unknown>("/handles/select", {
      method: "POST",
      body: { handle: row.handle, platform: row.platform ?? HANDLE_PLATFORM },
    });
  } catch {
    // remembered-next-time is best effort
  }
}
