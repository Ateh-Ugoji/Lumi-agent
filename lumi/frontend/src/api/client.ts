const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export type SamplePost = {
  author?: string;
  text?: string;
  likes?: number;
  url?: string;
  /** Picture for the author (handle DB); blank -> UI falls back to unavatar */
  avatar_url?: string;
};

export type ToolExecution = {
  name: string;
  arguments: Record<string, any>;
  sample_posts: SamplePost[];
  result?: any;
};

export type AgentResponse = {
  role: string;
  content: string;
  tool_calls_made: string[];
  tool_executions: ToolExecution[];
};

export type ProfileSummary = {
  id: number;
  name: string;
  platform: string;
  handle: string;
  has_voice_profile: boolean;
  listening_active: boolean;
};

export async function sendChatMessage(profileId: number, message: string): Promise<AgentResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_id: profileId, message }),
  });

  if (!res.ok) {
    throw new Error(`Agent error (${res.status}): ${await res.text()}`);
  }

  return res.json();
}

export type StreamEvent =
  | { type: "tool_start"; tool: string; arguments: Record<string, any> }
  | { type: "tool_done"; tool: string; sample_posts: SamplePost[] }
  | { type: "done"; content: string; tool_executions: ToolExecution[] }
  | { type: "error"; error: string };

export async function streamChatMessage(
  profileId: number,
  message: string,
  onEvent: (event: StreamEvent) => void,
): Promise<{ content: string; tool_executions: ToolExecution[] }> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ profile_id: profileId, message }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Streaming error (${response.status}): ${await response.text()}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = { content: "", tool_executions: [] as ToolExecution[] };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr) continue;

      try {
        const parsed = JSON.parse(jsonStr) as StreamEvent;
        onEvent(parsed);
        if (parsed.type === "done") {
          finalResult = {
            content: parsed.content,
            tool_executions: parsed.tool_executions || [],
          };
        }
      } catch (e) {
        console.warn("Failed to parse SSE payload", jsonStr, e);
      }
    }
  }

  return finalResult;
}

export async function getProfiles(): Promise<ProfileSummary[]> {
  const res = await fetch(`${API_BASE}/profiles`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.profiles || [];
}

export async function getProfileAlerts(profileId: number): Promise<any[]> {
  const res = await fetch(`${API_BASE}/profiles/${profileId}/alerts/unread`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.alerts || [];
}

export async function getChatHistory(profileId: number): Promise<any[]> {
  const res = await fetch(`${API_BASE}/chat/history?profile_id=${profileId}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.messages || [];
}

export async function deleteChatHistory(profileId: number): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/chat/history?profile_id=${profileId}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function generateChatTitle(message: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/chat/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) throw new Error("Title generation failed");
    const data = await res.json();
    return data.title || "New chat";
  } catch {
    const words = message.trim().split(/\s+/);
    return words.slice(0, 4).join(" ") || "New chat";
  }
}


export async function getConnectAuthUrl(platform: string): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/pfm/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.url || null;
  } catch {
    return null;
  }
}

export type TrendMatch = {
  id: number;
  profile_id: number;
  platform: string;
  platform_post_id: string;
  author_handle: string;
  author_avatar_url?: string | null;
  caption: string;
  platform_url: string;
  metrics: {
    like_count?: number;
    retweet_count?: number;
    reply_count?: number;
    impression_count?: number;
  } | null;
  discovered_at: string;
};

export async function getTrendMatches(profileId: number = 1, limit: number = 50): Promise<TrendMatch[]> {
  try {
    const res = await fetch(`${API_BASE}/trends/matches?profile_id=${profileId}&limit=${limit}`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.matches || [];
  } catch {
    return [];
  }
}

export async function scanNicheTrends(
  profileId: number = 1,
  handles: string[] = ["sama", "levelsio", "karpathy", "paulg", "swyx"],
  minLikes: number = 20,
): Promise<{ new_matches_found: number; viral_posts: any[] }> {
  const res = await fetch(`${API_BASE}/trends/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_id: profileId, handles, min_likes: minLikes }),
  });
  if (!res.ok) throw new Error(`Scan error: ${await res.text()}`);
  return res.json();
}

export type ProfileAnalytics = {
  profile_id: number;
  handle: string;
  name: string;
  total_impressions: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  reach_change_pct: number;
  saves_change_pct: number;
  reach_series: number[];
  saves_series: number[];
  allocation: {
    name: string;
    label: string;
    pct: number;
    amount: string;
    color: string;
    textColor: string;
  }[];
  top_posts: { caption: string; impressions: number; likes: number }[];
  is_live_data: boolean;
  summary: string;
};

export async function getProfileAnalytics(profileId: number): Promise<ProfileAnalytics | null> {
  try {
    const res = await fetch(`${API_BASE}/profiles/${profileId}/analytics`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// --- @-handle search (the composer's tag-an-account dropdown) -----------------
// Served by the main backend (app/routers/handles.py), which delegates to the
// handle-search core: local db head-start -> remembered store -> 60-min cache
// (prefix-chain reuse) -> budget-guarded Xpoz live. One API base, no :8010.

export type HandleRow = {
  handle: string;
  display_name?: string;
  avatar_url?: string;
  followers?: number | null;
  /** db | cache | live — where the data came from on that search */
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

export async function searchHandles(
  q: string,
  context = "",
): Promise<HandleSearchResponse> {
  const url =
    `${API_BASE}/handles/search?q=${encodeURIComponent(q)}` +
    `&context=${encodeURIComponent(context)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Handle search error (${res.status})`);
  }
  return res.json();
}

/** Instant-suggest snapshot (local db + remembered), deduped, followers first.
 *  The composer prefix-filters this in-browser per keystroke: 0 ms, 0 credits. */
export async function getSavedHandles(): Promise<HandleRow[]> {
  try {
    const res = await fetch(`${API_BASE}/handles/saved`);
    if (!res.ok) return [];
    const payload = await res.json();
    return (payload.results as HandleRow[]) ?? [];
  } catch {
    return []; // offline/failed snapshot degrades to "no instant paint", never an error
  }
}

/** Remember a picked handle (pfp/name/followers) for the next search. 0 credits.
 *  Fire-and-forget: forgetting a handle must never block or fail the composer. */
export async function selectHandle(row: HandleRow): Promise<void> {
  try {
    await fetch(`${API_BASE}/handles/select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        handle: row.handle,
        display_name: row.display_name ?? "",
        avatar_url: row.avatar_url ?? "",
        followers: row.followers ?? null,
      }),
    });
  } catch {
    // remembered-next-time is best-effort
  }
}
