import { request } from "./http.ts";

export type Network = "x" | "linkedin" | "facebook" | "instagram" | "tiktok";

/** Networks `POST /publish` can post to today (Instagram and TikTok are not built yet). */
export const PUBLISHABLE: readonly Network[] = ["x", "linkedin", "facebook"];

export const NETWORK_LABELS: Record<Network, string> = {
  x: "X",
  linkedin: "LinkedIn",
  facebook: "Facebook",
  instagram: "Instagram",
  tiktok: "TikTok",
};

/** Character limits per network, as `lumi_ai.generation.platforms` declares them. */
export const NETWORK_LIMITS: Record<Network, number> = {
  x: 280,
  linkedin: 3000,
  facebook: 63206,
  instagram: 2200,
  tiktok: 2200,
};

export function remainingChars(network: Network, text: string): number {
  return NETWORK_LIMITS[network] - [...text].length;
}

export type Evaluation = {
  decision: string;
  judge: string;
  scores: Record<string, number>;
  mean_score: number | null;
  style_similarity: number | null;
  deterministic_failures: string[];
  critique: string | null;
};

export type DraftOk = {
  platform: Network;
  ok: true;
  request_id: number;
  attempt_id: number;
  output: string;
  must_keep_passed: boolean | null;
  judge_verdict: string | null;
  judge_confidence: number | null;
  route_label: string | null;
  fallback: boolean;
  attempts: number;
  evaluation: Evaluation | null;
  warnings: string[];
  error: null;
};

export type DraftFailed = {
  platform: Network;
  ok: false;
  error: { code: string; message: string };
};

export type Draft = DraftOk | DraftFailed;

/** Draft one post per network from a source text, with the evaluation of each draft. */
export async function repurpose(input: {
  profileId: number;
  sourceText: string;
  platforms: Network[];
  mustKeep?: string[];
}): Promise<Draft[]> {
  const res = await request<{ results?: Draft[]; drafts?: Draft[] }>("/repurpose", {
    method: "POST",
    body: {
      profile_id: input.profileId,
      source_text: input.sourceText,
      platforms: input.platforms,
      must_keep_phrases: input.mustKeep ?? [],
    },
  });
  return res.results ?? res.drafts ?? [];
}

export type PublishResult = {
  status: "done" | "dry_run";
  dry_run: boolean;
  replayed: boolean;
  job_id: number | null;
  platform: string;
  external_post_id: string | null;
  url: string | null;
  estimated_cost_usd: number | null;
  warnings: string[];
};

export type PublishInput = {
  profileId: number;
  platform: Network;
  text: string;
  attemptId?: number | null;
  link?: string;
};

/** Check a post without sending it. Needs a connected account on that network. */
export function previewPublish(input: PublishInput): Promise<PublishResult> {
  return post(input, { dryRun: true });
}

/** Publish for real. `idempotencyKey` must stay the same for every retry of the same post. */
export function publishNow(input: PublishInput, idempotencyKey: string): Promise<PublishResult> {
  return post(input, { dryRun: false, idempotencyKey });
}

function post(
  input: PublishInput,
  mode: { dryRun: boolean; idempotencyKey?: string },
): Promise<PublishResult> {
  return request<PublishResult>("/publish", {
    method: "POST",
    headers: mode.idempotencyKey ? { "Idempotency-Key": mode.idempotencyKey } : undefined,
    body: {
      profile_id: input.profileId,
      platform: input.platform,
      text: input.text,
      ...(input.attemptId ? { attempt_id: input.attemptId } : {}),
      ...(input.link ? { link: input.link } : {}),
      confirm: !mode.dryRun,
      dry_run: mode.dryRun,
    },
  });
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
