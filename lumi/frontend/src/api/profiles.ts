import { request } from "./http.ts";

export type ProfileSummary = {
  id: number;
  name: string;
  platform: string;
  handle: string;
  has_voice_profile: boolean;
  listening_active: boolean;
  timezone?: string | null;
};

export async function getProfiles(): Promise<ProfileSummary[]> {
  const data = await request<{ profiles?: ProfileSummary[] }>("/profiles");
  return data.profiles ?? [];
}

export async function createProfile(
  platform: string,
  handle: string,
): Promise<ProfileSummary> {
  return request<ProfileSummary>("/profiles", {
    method: "POST",
    body: { platform, handle: handle.trim().replace(/^@/, "") },
  });
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

export async function getProfileAnalytics(
  profileId: number,
): Promise<ProfileAnalytics | null> {
  try {
    return await request<ProfileAnalytics>(`/profiles/${profileId}/analytics`);
  } catch {
    return null;
  }
}
