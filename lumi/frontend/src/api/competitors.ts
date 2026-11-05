import { request } from "./http";

export type CompetitorPost = {
  id: number;
  caption: string;
  url: string;
  published_at?: string | null;
  likes?: number;
  replies?: number;
  shares?: number;
  views?: number | null;
  weighted_score?: number | null;
};

export type CompetitorFramework = {
  id: number;
  name: string;
  title: string;
  structure: string;
  hook_formula: string;
  when_to_use?: string;
  why_it_works?: string;
  lift?: number | null;
  confidence?: number;
};

export type CompetitorItem = {
  handle: string;
  display_name: string;
  platform: string;
  avatar_url?: string;
  follower_count?: number | null;
  profile_url: string;
  role: string;
  tweepcred?: {
    following_to_followers_ratio: number;
    is_penalized: boolean;
    division_factor: number;
    reach_loss_percentage: number;
    status: "healthy" | "warning" | "critical";
    unfollow_target_to_fix: number;
  } | null;
  frameworks: CompetitorFramework[];
  best_posts: CompetitorPost[];
};

export type CompetitorOverviewResponse = {
  profile_id: number;
  niche: string;
  niche_key: string;
  keywords: string[];
  competitors_count: number;
  competitors: CompetitorItem[];
  frameworks: CompetitorFramework[];
  own_top_posts: CompetitorPost[];
};

export async function getCompetitorOverview(
  profileId?: number | null
): Promise<CompetitorOverviewResponse> {
  return request<CompetitorOverviewResponse>("/intelligence/competitors", {
    query: profileId ? { profile_id: profileId } : undefined,
  });
}
