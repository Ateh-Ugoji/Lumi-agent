import { request } from "./http.ts";

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

export async function getTrendMatches(profileId: number, limit = 50): Promise<TrendMatch[]> {
  const data = await request<{ matches?: TrendMatch[] }>("/trends/matches", {
    query: { profile_id: profileId, limit },
  });
  return data.matches ?? [];
}

/** `handles` is optional: without it the server scans the niche of the profile. */
export function scanNicheTrends(
  profileId: number,
  opts: { handles?: string[]; minLikes?: number } = {},
): Promise<{ profile_id: number; new_matches_found: number; viral_posts: unknown[] }> {
  return request("/trends/scan", {
    method: "POST",
    body: {
      profile_id: profileId,
      ...(opts.handles?.length ? { handles: opts.handles } : {}),
      min_likes: opts.minLikes ?? 20,
    },
  });
}
