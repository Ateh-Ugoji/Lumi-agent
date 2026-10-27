export type SimStepKind = "social" | "analysis" | "writing" | "action";

export type SamplePost = {
  author?: string;
  text?: string;
  likes?: number;
  url?: string;
};

export type SimStep = {
  id: string;
  label: string;
  kind: SimStepKind;
  durationMs: number;
  detail?: string;
  meta?: string;
  platforms?: string[];
  samplePosts?: SamplePost[];
};

export type SimScript = {
  id: string;
  steps: SimStep[];
  finalDelayMs: number;
};

export const ALL_PLATFORMS = [
  "x",
  "instagram",
  "linkedin",
  "tiktok",
  "youtube",
  "facebook",
];

const DEFAULT_SCRIPT: SimScript = {
  id: "default",
  finalDelayMs: 300,
  steps: [
    {
      id: "read",
      label: "Reading your recent posts",
      kind: "social",
      durationMs: 1500,
      detail: "Pulled your last 24 posts",
      platforms: ALL_PLATFORMS,
    },
    {
      id: "score",
      label: "Scoring engagement signals",
      kind: "analysis",
      durationMs: 1300,
      detail: "Weighting saves, replies and shares",
      meta: "6 platforms",
    },
    {
      id: "write",
      label: "Writing the reply",
      kind: "writing",
      durationMs: 1200,
    },
  ],
};

const CONTENT_MIX_SCRIPT: SimScript = {
  id: "contentMix",
  finalDelayMs: 300,
  steps: [
    {
      id: "read",
      label: "Reading your recent posts",
      kind: "social",
      durationMs: 1500,
      detail: "Pulled your last 24 posts",
      platforms: ["x", "instagram", "linkedin", "tiktok"],
    },
    {
      id: "score",
      label: "Scoring engagement signals",
      kind: "analysis",
      durationMs: 1300,
      detail: "Weighting saves, replies and shares",
      meta: "6 platforms",
    },
    {
      id: "tone",
      label: "Comparing platform tone",
      kind: "social",
      durationMs: 1400,
      detail: "Benchmarked against your top posts",
      platforms: ["instagram", "x", "linkedin", "youtube", "facebook"],
    },
    {
      id: "write",
      label: "Writing the reply",
      kind: "writing",
      durationMs: 1200,
    },
  ],
};

const SCHEDULING_SCRIPT: SimScript = {
  id: "scheduling",
  finalDelayMs: 300,
  steps: [
    {
      id: "queue",
      label: "Checking your calendar and queue",
      kind: "action",
      durationMs: 1300,
      detail: "Scanned your drafts and scheduled posts",
    },
    {
      id: "times",
      label: "Finding best posting times",
      kind: "analysis",
      durationMs: 1500,
      detail: "90 days of engagement",
      meta: "6 platforms",
    },
    {
      id: "captions",
      label: "Drafting captions",
      kind: "writing",
      durationMs: 1300,
    },
    {
      id: "schedule",
      label: "Scheduling posts",
      kind: "social",
      durationMs: 1400,
      platforms: ["x", "instagram", "linkedin", "tiktok"],
    },
  ],
};

const LAST_POST_SCRIPT: SimScript = {
  id: "lastPost",
  finalDelayMs: 300,
  steps: [
    {
      id: "view",
      label: "Viewing recent posts",
      kind: "social",
      durationMs: 1200,
      detail: "Fetched your last 7 posts",
      platforms: ["x", "instagram"],
    },
    {
      id: "stats",
      label: "Pulling engagement stats",
      kind: "social",
      durationMs: 1400,
      detail: "Impressions, saves and shares",
      platforms: ["instagram", "facebook", "youtube"],
    },
    {
      id: "write",
      label: "Writing the reply",
      kind: "writing",
      durationMs: 1200,
    },
  ],
};

const SOCIALS_SCRIPT: SimScript = {
  id: "socials",
  finalDelayMs: 300,
  steps: [
    {
      id: "read",
      label: "Reading your socials",
      kind: "social",
      durationMs: 1500,
      detail: "Pulled posts from 6 accounts",
      platforms: ALL_PLATFORMS,
    },
    {
      id: "mentions",
      label: "Checking mentions this week",
      kind: "social",
      durationMs: 1300,
      platforms: ["x", "instagram", "linkedin"],
    },
    {
      id: "write",
      label: "Writing the reply",
      kind: "writing",
      durationMs: 1200,
    },
  ],
};

const DEFS: { script: SimScript; match: RegExp }[] = [
  {
    script: CONTENT_MIX_SCRIPT,
    match: /rebalance|content mix|content strateg|what should i post|what to post/i,
  },
  {
    script: SCHEDULING_SCRIPT,
    match: /best time|schedul|posting time|when.*(?:post|publish)|calendar|queue/i,
  },
  {
    script: LAST_POST_SCRIPT,
    match:
      /last post|recent post|happened to|how (?:did|was|is|are)|performed|performance|impression|reach|analytic|engagement|metric|stat|view|follower|score|report|trend|growth|numbers?/i,
  },
  {
    script: SOCIALS_SCRIPT,
    match:
      /social|instagram|linkedin|tiktok|facebook|youtube|twitter|reel|hashtag|caption|follow|logo|threads/i,
  },
];

export const SCRIPTS: Record<string, SimScript> = {
  [DEFAULT_SCRIPT.id]: DEFAULT_SCRIPT,
  [CONTENT_MIX_SCRIPT.id]: CONTENT_MIX_SCRIPT,
  [SCHEDULING_SCRIPT.id]: SCHEDULING_SCRIPT,
  [LAST_POST_SCRIPT.id]: LAST_POST_SCRIPT,
  [SOCIALS_SCRIPT.id]: SOCIALS_SCRIPT,
};

export function defaultScript(): SimScript {
  return DEFAULT_SCRIPT;
}

export function scriptById(id: string): SimScript {
  return SCRIPTS[id] ?? DEFAULT_SCRIPT;
}

export function pickScript(text: string): SimScript {
  for (const def of DEFS) {
    if (def.match.test(text)) return def.script;
  }
  return DEFAULT_SCRIPT;
}
