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
  /** The keyword search that found the post. `null`: a scan of tracked accounts found it. */
  keyword?: string | null;
};

/** `keyword` narrows to what one keyword search found; leave it out for every match. */
export async function getTrendMatches(
  profileId: number,
  limit = 50,
  keyword?: string,
): Promise<TrendMatch[]> {
  const data = await request<{ matches?: TrendMatch[] }>("/trends/matches", {
    query: { profile_id: profileId, limit, ...(keyword ? { keyword } : {}) },
  });
  return data.matches ?? [];
}

/** `handles` is optional: without it the server scans the niche of the profile, and with
 *  `keywords` it searches posts by keyword instead (or uses the keywords saved in listening). */
export function scanNicheTrends(
  profileId: number,
  opts: { handles?: string[]; keywords?: string[]; minLikes?: number } = {},
): Promise<{
  profile_id: number;
  new_matches_found: number;
  viral_posts: unknown[];
  keywords?: string[];
}> {
  return request("/trends/scan", {
    method: "POST",
    body: {
      profile_id: profileId,
      ...(opts.handles?.length ? { handles: opts.handles } : {}),
      ...(opts.keywords?.length ? { keywords: opts.keywords } : {}),
      min_likes: opts.minLikes ?? 20,
    },
  });
}
