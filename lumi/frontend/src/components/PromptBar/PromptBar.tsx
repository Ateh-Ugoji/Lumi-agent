import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import {
  ACCENTS,
  accentChain,
  createShader,
  playSweep,
} from "glimm";
import { MicRecorder } from "../../voice/recorder";
import { stopSpeaking } from "../../voice/speak";
import styles from "./PromptBar.module.css";
import {
  getSavedHandles,
  searchHandles,
  selectHandle,
  transcribeWav,
  type HandleRow,
} from "../../api";

const RAINBOW = accentChain([
  ACCENTS.red,
  ACCENTS.orange,
  ACCENTS.yellow,
  ACCENTS.green,
  ACCENTS.cyan,
  ACCENTS.blue,
  ACCENTS.purple,
]);

function Icon({
  children,
  size = 15,
  strokeWidth = 1.8,
}: {
  children: ReactNode;
  size?: number;
  strokeWidth?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const GLYPHS: Record<string, ReactNode> = {
  clip: (
    <path d="m21.4 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  ),
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  layers: (
    <g>
      <path d="M12 2 2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5M2 12l10 5 10-5" />
    </g>
  ),
  globe: (
    <g>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </g>
  ),
};

const BRANDS: Record<string, ReactNode> = {
  figma: (
    <svg width="11" height="16" viewBox="0 0 38 57" aria-hidden="true">
      <path
        d="M9.5 57A9.5 9.5 0 0 0 19 47.5V38H9.5a9.5 9.5 0 0 0 0 19z"
        fill="#0ACF83"
      />
      <path
        d="M0 28.5A9.5 9.5 0 0 1 9.5 19H19v19H9.5A9.5 9.5 0 0 1 0 28.5z"
        fill="#A259FF"
      />
      <path
        d="M0 9.5A9.5 9.5 0 0 1 9.5 0H19v19H9.5A9.5 9.5 0 0 1 0 9.5z"
        fill="#F24E1E"
      />
      <path
        d="M19 0h9.5a9.5 9.5 0 1 1 0 19H19V0z"
        fill="#FF7262"
      />
      <path
        d="M38 28.5a9.5 9.5 0 1 1-19 0 9.5 9.5 0 0 1 19 0z"
        fill="#1ABCFE"
      />
    </svg>
  ),
  slack: (
    <svg width="15" height="15" viewBox="0 0 127 127" aria-hidden="true">
      <path
        d="M27.2 80c0 7.3-5.9 13.2-13.2 13.2C6.7 93.2.8 87.3.8 80c0-7.3 5.9-13.2 13.2-13.2h13.2V80zm6.6 0c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2v33c0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V80z"
        fill="#E01E5A"
      />
      <path
        d="M47 27.2c-7.3 0-13.2-5.9-13.2-13.2C33.8 6.7 39.7.8 47 .8c7.3 0 13.2 5.9 13.2 13.2v13.2H47zm0 6.7c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H13.9C6.6 60.3.7 54.4.7 47.1c0-7.3 5.9-13.2 13.2-13.2H47z"
        fill="#36C5F0"
      />
      <path
        d="M99.9 47.1c0-7.3 5.9-13.2 13.2-13.2 7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H99.9V47.1zm-6.6 0c0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V13.9C66.9 6.6 72.8.7 80.1.7c7.3 0 13.2 5.9 13.2 13.2v33.2z"
        fill="#2EB67D"
      />
      <path
        d="M80.1 99.8c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2-7.3 0-13.2-5.9-13.2-13.2V99.8h13.2zm0-6.6c-7.3 0-13.2-5.9-13.2-13.2 0-7.3 5.9-13.2 13.2-13.2h33.1c7.3 0 13.2 5.9 13.2 13.2 0 7.3-5.9 13.2-13.2 13.2H80.1z"
        fill="#ECB22E"
      />
    </svg>
  ),
  drive: (
    <svg width="16" height="14" viewBox="0 0 87.3 78" aria-hidden="true">
      <path
        d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z"
        fill="#0066da"
      />
      <path
        d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z"
        fill="#00ac47"
      />
      <path
        d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z"
        fill="#ea4335"
      />
      <path
        d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z"
        fill="#00832d"
      />
      <path
        d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z"
        fill="#2684fc"
      />
      <path
        d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z"
        fill="#ffba00"
      />
    </svg>
  ),
  gmail: (
    <svg width="15" height="12" viewBox="0 0 256 193" aria-hidden="true">
      <path
        d="M58.182 192.05V93.14L27.507 65.077 0 49.504v125.091c0 9.658 7.825 17.455 17.455 17.455h40.727Z"
        fill="#4285F4"
      />
      <path
        d="M197.818 192.05h40.727c9.659 0 17.455-7.826 17.455-17.455V49.505l-31.156 17.837-27.026 25.798v98.91Z"
        fill="#34A853"
      />
      <path
        d="m58.182 93.14-4.174-38.647 4.174-36.989L128 69.868l69.818-52.364 4.669 34.992-4.669 40.644L128 145.504 58.182 93.14Z"
        fill="#EA4335"
      />
      <path
        d="M197.818 17.504V93.14L256 49.504V26.231c0-21.585-24.64-33.89-41.89-20.945l-16.292 12.218Z"
        fill="#FBBC04"
      />
      <path
        d="m0 49.504 26.759 20.07L58.182 93.14V17.504L41.89 5.286C24.61-7.66 0 4.646 0 26.23v23.273Z"
        fill="#C5221F"
      />
    </svg>
  ),
};

type Source = {
  key: string;
  name: string;
  desc: string;
  glyph?: string;
  brand?: string;
  attach?: boolean;
  connect?: boolean;
};

const SOURCES: Source[] = [
  {
    key: "attach",
    name: "Add photos & files",
    desc: "Upload from your computer",
    glyph: "clip",
    attach: true,
  },
  { key: "analytics", name: "Post analytics", desc: "Reach, saves & scores", glyph: "chart" },
  { key: "posts", name: "Posts & drafts", desc: "128 posts, 9 drafts", glyph: "layers" },
  { key: "web", name: "Web search", desc: "Real-time news and info", glyph: "globe" },
  { key: "figma", name: "Figma", desc: "Design-to-code workflows", brand: "figma", connect: true },
  { key: "slack", name: "Add from slack", desc: "Read and manage Slack", brand: "slack" },
  { key: "drive", name: "Give context from google drive", desc: "Read Docs, Slides & Sheets", brand: "drive", connect: true },
  { key: "gmail", name: "Gmail", desc: "Read and manage Gmail", brand: "gmail", connect: true },
];

const COMMANDS = [
  { key: "compare", name: "/compare", desc: "Reach vs. last week" },
  { key: "schedule", name: "/schedule", desc: "Draft a posting plan" },
  { key: "repurpose", name: "/repurpose", desc: "Turn a post into a thread" },
  { key: "draft-post", name: "/draft-post", desc: "Write a new caption" },
  { key: "summarize", name: "/summarize", desc: "Digest the thread so far" },
];

const MODELS = [
  { key: "luna-6", name: "Luna 6", tag: "Flagship" },
  { key: "luna-mini", name: "Luna Mini", tag: "Basic" },
  { key: "legacy-04", name: "Legacy 0.4", tag: "Stale" },
];

const AUTO_STEPS: {
  draft: string;
  active?: number;
  connect?: boolean;
  modelOpen?: boolean;
  model?: string;
  hold: number;
}[] = [
  { draft: "", connect: false, model: "luna-mini", hold: 1100 },
  { draft: "@", active: 0, hold: 900 },
  { draft: "@", active: 1, hold: 620 },
  { draft: "@", active: 4, hold: 620 },
  { draft: "@", active: 7, hold: 700 },
  { draft: "@", active: 7, connect: true, hold: 1000 },
  { draft: "", hold: 700 },
  { draft: "/", active: 0, hold: 900 },
  { draft: "/", active: 1, hold: 620 },
  { draft: "/", active: 3, hold: 1000 },
  { draft: "", hold: 800 },
  { draft: "", modelOpen: true, hold: 1200 },
  { draft: "", model: "luna-6", hold: 2400 },
  { draft: "", hold: 900 },
];

function parseToken(
  draft: string,
): { kind: "at" | "slash"; query: string; start: number } | null {
  const match = /(^|\s)([@/])([\w-]*)$/.exec(draft);
  if (!match) return null;
  return {
    kind: match[2] === "@" ? "at" : "slash",
    query: match[3].toLowerCase(),
    start: match.index + match[1].length,
  };
}

type HandleMenuRow = { key: string; name: string; desc: string; handle?: HandleRow };

/** Server min length — shorter queries never reach the backend or Xpoz. */
const HANDLE_MIN_QUERY = 2;

function fmtFollowers(count?: number | null): string {
  if (count == null) return ""; // unknown followers stay unknown — never shown as 0
  if (count >= 1_000_000) return `${+(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${+(count / 1_000).toFixed(1)}k`;
  return `${count}`;
}

function handleDesc(row: HandleRow): string {
  return row.display_name?.trim() ?? "";
}

/** Instant layer: the server's ordering rules over the in-browser snapshot of
 * saved handles — 0 ms, no request, no credits. Every snapshot row is
 * memory-served (the "saved half"), so the 50/50 mix degenerates to: exact typed
 * handle first → local-db rows lead → followers desc (unknown followers last). */
function suggestLocalHandles(saved: HandleRow[], raw: string): HandleRow[] {
  const p = raw.toLowerCase();
  const hits = saved.filter((r) => (r.handle || "").toLowerCase().startsWith(p));
  hits.sort((a, b) => {
    const ea = a.handle.toLowerCase() === p ? 0 : 1;
    const eb = b.handle.toLowerCase() === p ? 0 : 1;
    if (ea !== eb) return ea - eb;
    const da = a.source === "db" ? 0 : 1;
    const db = b.source === "db" ? 0 : 1;
    if (da !== db) return da - db;
    const fa = a.followers;
    const fb = b.followers;
    if (fa == null && fb != null) return 1;
    if (fa != null && fb == null) return -1;
    return (fb ?? 0) - (fa ?? 0) || a.handle.localeCompare(b.handle);
  });
  return hits.slice(0, 10);
}

/** The up-to-3 words typed before the @ being completed. Sent as `context` for
 * ranking only — never appended to the Xpoz query (Lucene AND would kill it). */
function contextBefore(draft: string): string {
  const token = parseToken(draft);
  if (!token || token.kind !== "at") return "";
  const before = draft.slice(0, token.start).trim();
  if (!before) return "";
  return before.split(/\s+/).filter(Boolean).slice(-3).join(" ");
}

export default function PromptBar({
  variant = "Rounded",
  demo = true,
  tall = false,
  placeholder,
  onSend,
  text,
  onTextChange,
  busy = false,
}: {
  variant?: string;
  demo?: boolean;
  tall?: boolean;
  placeholder?: string;
  onSend?: (value: string, opts?: { voice?: boolean }) => void;
  text?: string;
  onTextChange?: (value: string) => void;
  busy?: boolean;
}) {
  const pill = variant === "Pill";
  const controlled = text !== undefined;
  const [innerDraft, setInnerDraft] = useState("");
  const draft = controlled ? (text as string) : innerDraft;
  const draftRef = useRef(draft);
  draftRef.current = draft;

  const setDraft = (next: string | ((current: string) => string)) => {
    const value =
      typeof next === "function" ? next(draftRef.current) : next;
    draftRef.current = value;
    if (controlled) onTextChange?.(value);
    else setInnerDraft(value);
  };

  const [dismissed, setDismissed] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [model, setModel] = useState(MODELS[1]);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [connected, setConnected] = useState<Record<string, boolean>>({});
  const [active, setActive] = useState(0);
  // Voice state machine: idle → listening → transcribing → (auto-send) idle.
  const [voiceState, setVoiceState] = useState<
    "idle" | "listening" | "transcribing"
  >("idle");
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recorderRef = useRef<MicRecorder | null>(null);
  const listening = voiceState === "listening";
  const [auto, setAuto] = useState(demo);
  const [autoStep, setAutoStep] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const wide = expanded || tall;
  const [rowBox, setRowBox] = useState<{
    top: number;
    height: number;
  } | null>(null);
  const [engaged, setEngaged] = useState(false);
  // --- @-handle search state (real X accounts behind a typed `@`) -----------
  const [savedHandles, setSavedHandles] = useState<HandleRow[]>([]); // instant layer
  const [liveRows, setLiveRows] = useState<HandleRow[] | null>(null); // refined results
  const [liveQuery, setLiveQuery] = useState(""); // which query `liveRows` belongs to
  const [handlesPending, setHandlesPending] = useState(false);
  const handleSeqRef = useRef(0); // drops stale refine responses (fast typing)
  const [modelBox, setModelBox] = useState<{
    top: number;
    height: number;
  } | null>(null);
  const [modelHovered, setModelHovered] = useState<number | null>(null);
  const [modelMenuLeft, setModelMenuLeft] = useState(0);
  const [modelMenuBottom, setModelMenuBottom] = useState(0);
  const composerAnchorRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const modelRef = useRef<HTMLButtonElement>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const modelRowRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const glimmRef = useRef<HTMLCanvasElement>(null);
  const shaderRef = useRef<ReturnType<typeof createShader> | null>(null);
  const sweepingRef = useRef(false);

  const takeOver = (event: { target: EventTarget | null }) => {
    setAuto(false);
    if (auto && event.target === inputRef.current) setDraft("");
  };

  const token = dismissed ? null : parseToken(draft);
  // Two `@` menus, never sharing rows: `plus` = the demo SOURCES list behind the
  // `+` button; `at` = the typed `@` handle search (armed at >=2 chars, the
  // server's min length — below that we show a hint instead of stale rows).
  const menu: "plus" | "at" | "slash" | null = plusOpen
    ? "plus"
    : (token?.kind ?? null);
  const query = plusOpen ? "" : (token?.query ?? "");
  const atToken = menu === "at";
  const handleMode = atToken && query.length >= HANDLE_MIN_QUERY;
  const refinedHere = handleMode && liveRows !== null && liveQuery === query;
  const handleCandidates: HandleRow[] = refinedHere
    ? (liveRows as HandleRow[])
    : handleMode
      ? suggestLocalHandles(savedHandles, query)
      : [];

  const rows: HandleMenuRow[] = menu === "plus"
    ? SOURCES.filter((s) => s.name.toLowerCase().includes(query))
    : atToken
      ? handleMode
        ? handleCandidates.map((h) => ({
            key: h.handle.toLowerCase(),
            name: h.handle,
            desc: handleDesc(h),
            handle: h,
          }))
        : []
      : menu === "slash"
        ? COMMANDS.filter((c) => c.name.slice(1).startsWith(query))
        : [];

  useEffect(() => {
    setActive(0);
    setEngaged(false);
  }, [menu, query, rows.length]);

  // The saved-handle snapshot loads once (0 credits) and paints instantly on
  // every keystroke; the debounced full search only refines it, never gates it.
  useEffect(() => {
    let cancelled = false;
    void getSavedHandles().then((loaded) => {
      if (!cancelled) setSavedHandles(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounced refine: 300 ms after typing stops — and only at >=2 chars, the
  // server's min length — ask the backend for cache/live results. The sequence
  // counter drops any response that no longer matches what's in the box, so fast
  // typing can never paint stale results over newer ones.
  useEffect(() => {
    if (!atToken) {
      handleSeqRef.current += 1; // in-flight refine for an older token is stale
      setHandlesPending(false);
      return;
    }
    const q = query;
    if (q.length < HANDLE_MIN_QUERY) {
      handleSeqRef.current += 1;
      setLiveRows(null);
      setLiveQuery("");
      setHandlesPending(false);
      return;
    }
    setHandlesPending(true);
    const timer = window.setTimeout(() => {
      const seq = ++handleSeqRef.current;
      searchHandles(q, contextBefore(draftRef.current))
        .then((res) => {
          if (handleSeqRef.current !== seq) return;
          setLiveRows(res.results);
          setLiveQuery(q);
          setHandlesPending(false);
        })
        .catch(() => {
          if (handleSeqRef.current !== seq) return;
          // a failed refine keeps the instant rows — never an empty-dropdown flash
          setLiveRows(null);
          setLiveQuery("");
          setHandlesPending(false);
        });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [atToken, query]);

  // Clicking anywhere outside the bar dismisses the typed-`@` menu (Escape does
  // the same via `dismissed`; this is the mouse equivalent). Menu rows live
  // inside [data-promptbar], so picking is never interrupted.
  useEffect(() => {
    if (!atToken) return;
    const dismiss = (event: PointerEvent) => {
      if (!(event.target as Element).closest("[data-promptbar]"))
        setDismissed(true);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [atToken]);

  useLayoutEffect(() => {
    const target = rowRefs.current[active];
    if (target)
      setRowBox({ top: target.offsetTop, height: target.offsetHeight });
  }, [menu, query, active, connected, rows.length]);

  const modelIndex = MODELS.findIndex((m) => m.key === model.key);
  useLayoutEffect(() => {
    if (!modelOpen) return;
    const target =
      modelRowRefs.current[modelHovered ?? modelIndex];
    if (target)
      setModelBox({ top: target.offsetTop, height: target.offsetHeight });
  }, [modelOpen, modelHovered, modelIndex]);

  useLayoutEffect(() => {
    if (
      !modelOpen ||
      !composerAnchorRef.current ||
      !modelRef.current
    )
      return;
    const anchorRect =
      composerAnchorRef.current.getBoundingClientRect();
    const triggerRect = modelRef.current.getBoundingClientRect();
    setModelMenuLeft(
      Math.max(
        0,
        Math.min(
          triggerRect.left - anchorRect.left,
          anchorRect.width - 176,
        ),
      ),
    );
    setModelMenuBottom(anchorRect.bottom - triggerRect.top + 8);
  }, [modelOpen, wide, model.name]);

  useEffect(() => {
    if (!modelOpen) setModelHovered(null);
  }, [modelOpen]);

  const makeShader = () => {
    const canvas = glimmRef.current;
    if (!canvas) return null;
    const random = Math.random;
    Math.random = () => 0;
    try {
      return createShader({
        canvas,
        palette: RAINBOW,
        direction: "ltr",
        bandTight: 10,
        swellAmount: 0.85,
      });
    } finally {
      Math.random = random;
    }
  };

  useEffect(() => {
    shaderRef.current = makeShader();
    return () => {
      shaderRef.current?.destroy();
      shaderRef.current = null;
    };
  }, []);

  const celebrate = () => {
    if (sweepingRef.current) return;
    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    shaderRef.current?.destroy();
    const shader = makeShader();
    shaderRef.current = shader;
    if (!shader) return;
    sweepingRef.current = true;
    const sweep = playSweep(shader, {
      palette: RAINBOW,
      direction: "ltr",
      sweepMs: 570,
      outroMs: 80,
      peakAlpha: 1.3,
      bandTight: 10,
      brightness: 1.4,
      swellAmount: 1,
      waveSpeed: 1.8,
      easing: "easeOutExpo",
    });
    sweep.done.finally(() => {
      sweepingRef.current = false;
    });
  };

  const selectModel = (next: (typeof MODELS)[number]) => {
    setModel(next);
    setModelOpen(false);
    if (next.key === "luna-6") celebrate();
  };

  useEffect(() => {
    if (!auto) return;
    const step = AUTO_STEPS[autoStep % AUTO_STEPS.length];
    setDraft(step.draft);
    if (step.active !== undefined) setActive(step.active);
    if (step.connect !== undefined) {
      const key = SOURCES[step.active ?? 0]?.key;
      setConnected(step.connect && key ? { [key]: true } : {});
    }
    if (step.modelOpen !== undefined) setModelOpen(step.modelOpen);
    if (step.model) {
      const next = MODELS.find((m) => m.key === step.model);
      if (next) selectModel(next);
    }
    const t = setTimeout(
      () => setAutoStep((s) => s + 1),
      step.hold,
    );
    return () => clearTimeout(t);
  }, [auto, autoStep]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    const controls = controlsRef.current;
    const measure = measureRef.current;
    const modelButton = modelRef.current;
    if (!input || !controls || !measure || !modelButton) return;

    const fixedControlsWidth = 28 * 3 + modelButton.offsetWidth;
    const inlineGaps = 4 * 4;
    const inlineInputWidth =
      controls.clientWidth - fixedControlsWidth - inlineGaps;
    const needsFullWidth =
      draft.includes("\n") ||
      measure.offsetWidth + 8 > inlineInputWidth;
    if (needsFullWidth !== expanded) {
      setExpanded(needsFullWidth);
    }

    const minHeight = 28;
    const maxHeight = 100;
    input.style.height = "0px";
    const contentHeight = input.scrollHeight;
    input.style.height = `${Math.min(
      Math.max(contentHeight, minHeight),
      maxHeight,
    )}px`;
    input.style.overflowY =
      contentHeight > maxHeight ? "auto" : "hidden";
  }, [draft, expanded]);

  useEffect(() => {
    if (!modelOpen && !plusOpen) return;
    const close = (event: PointerEvent) => {
      if (
        !(event.target as Element).closest("[data-promptbar]")
      ) {
        setModelOpen(false);
        setPlusOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [modelOpen, plusOpen]);

  const closeMenus = () => {
    setPlusOpen(false);
    setModelOpen(false);
  };

  const pick = (row?: HandleMenuRow) => {
    if (!row) return;
    if (row.handle) {
      // Tag the account: drop `@handle` in at the caret-token position and
      // tell the server which handle was picked (0 credits). Its picture, name and followers
      // stay in this row of the local search state; the server never stores them from here.
      // The lookup itself happens on send, per the agent's existing rule 13.
      const picked = row.handle;
      setDraft(`${token ? draft.slice(0, token.start) : draft}@${picked.handle} `);
      void selectHandle(picked);
      setPlusOpen(false);
      setDismissed(false);
      inputRef.current?.focus();
      return;
    }
    const source = SOURCES.find((s) => s.key === row.key);
    if (source?.attach) {
      fileInputRef.current?.click();
      if (token) setDraft(draft.slice(0, token.start));
    } else if (menu === "plus") {
      // demo sources menu behind the `+` button keeps its old insert-@ behaviour
      setDraft(
        `${token ? draft.slice(0, token.start) : draft}@${row.name} `,
      );
    } else {
      setDraft(
        `${token ? draft.slice(0, token.start) : draft}${row.name} `,
      );
    }
    setPlusOpen(false);
    setDismissed(false);
    inputRef.current?.focus();
  };

  const onFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const names = Array.from(event.target.files ?? []).map((f) => f.name);
    if (names.length > 0) {
      setAttachments((current) => [...current, ...names]);
    }
    event.target.value = "";
  };

  // While the agent is working a second turn would run in parallel, so sending is off.
  const canSend = !busy && (draft.trim().length > 0 || attachments.length > 0);
  const send = () => {
    if (!canSend) return;
    onSend?.(draft.trim());
    setDraft("");
    setAttachments([]);
    closeMenus();
  };

  // --- real voice capture ------------
  const finishVoice = async (fromEndpointer?: Blob) => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    setVoiceState("transcribing");
    try {
      // the endpointer already stopped the recorder and hands us the blob;
      // when the user taps stop manually we stop it here.
      const blob = fromEndpointer ?? (recorder ? await recorder.stop() : null);
      const text = blob ? (await transcribeWav(blob)).trim() : "";
      if (text && busy) {
        setVoiceError("Lumi is still working on the last request. Try again in a moment.");
      } else if (text) {
        stopSpeaking(); // barge-in: silence any reply still speaking
        onSend?.(text, { voice: true });
      } else {
        setVoiceError("Didn't catch that — no speech detected. Try again?");
      }
    } catch (err) {
      setVoiceError(
        `Voice input failed: ${err instanceof Error ? err.message : "unknown error"}`,
      );
    } finally {
      setVoiceState("idle");
      inputRef.current?.focus();
    }
  };

  const toggleVoice = () => {
    if (voiceState === "transcribing") return;
    if (voiceState === "listening") {
      void finishVoice(); // manual stop: recorder.stop() is called inside
      return;
    }
    setVoiceError(null);
    stopSpeaking(); // barge-in: silence any reply still speaking
    const recorder = new MicRecorder();
    recorderRef.current = recorder;
    recorder
      .start({
        onEnd: (blob) => {
          // silence endpointer already stopped the recorder — pass the blob through
          if (recorderRef.current === recorder) void finishVoice(blob);
        },
      })
      .then(() => setVoiceState("listening"))
      .catch((err: unknown) => {
        recorderRef.current = null;
        setVoiceState("idle");
        setVoiceError(
          err instanceof Error && /denied|not allowed/i.test(err.message)
            ? "Mic access denied — allow the microphone to talk to Lumi."
            : "Could not start the microphone.",
        );
      });
  };

  // stop capture if the component unmounts mid-recording
  useEffect(() => () => {
    recorderRef.current?.stop().catch(() => {});
  }, []);

  return (
    <div
      data-promptbar
      className={demo ? styles.demoRoot : styles.root}
      onPointerDownCapture={takeOver}
      onKeyDownCapture={takeOver}
    >
      <div ref={composerAnchorRef} className={styles.anchor}>
        {menu && (
          <div
            onMouseLeave={() => setEngaged(false)}
            className={styles.menu}
            style={{
              animation:
                "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both",
              transformOrigin: "bottom center",
            }}
          >
            <span
              aria-hidden
              className={styles.glideHighlight}
              style={{
                top: rowBox?.top ?? 0,
                height: rowBox?.height ?? 0,
                opacity:
                  rowBox && engaged && rows.length > 0 ? 1 : 0,
              }}
            />
            {rows.map((row, i) => {
              const source =
                menu === "plus"
                  ? SOURCES.find((s) => s.key === row.key)
                  : undefined;
              const handle = row.handle;
              return (
                <button
                  key={row.key}
                  type="button"
                  ref={(el) => {
                    rowRefs.current[i] = el;
                  }}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => {
                    setActive(i);
                    setEngaged(true);
                  }}
                  onClick={() => pick(row)}
                  className={styles.menuRow}
                >
                  {handle ? (
                    <span className={styles.menuRowAvatar}>
                      <img
                        src={
                          handle.avatar_url ||
                          `https://unavatar.io/x/${handle.handle}`
                        }
                        alt=""
                        loading="lazy"
                        onError={(event) => {
                          // stored pfp failed → try the unavatar fallback once,
                          // then hide quietly (never a broken-image icon)
                          const img = event.currentTarget;
                          if (!img.dataset.fallback) {
                            img.dataset.fallback = "1";
                            img.src = `https://unavatar.io/x/${handle.handle}`;
                          } else {
                            img.style.visibility = "hidden";
                          }
                        }}
                      />
                    </span>
                  ) : (
                    source && (
                      <span className={styles.menuRowIcon}>
                        {source.brand ? (
                          BRANDS[source.brand]
                        ) : (
                          <Icon size={15}>
                            {GLYPHS[source.glyph ?? "clip"]}
                          </Icon>
                        )}
                      </span>
                    )
                  )}
                  <span className={styles.menuRowName}>
                    {handle ? `@${row.name}` : row.name}
                  </span>
                  <span className={styles.menuRowDesc}>{row.desc}</span>
                  {handle && (
                    <span className={styles.menuRowMeta}>
                      {handle.followers != null && (
                        <span>{fmtFollowers(handle.followers)}</span>
                      )}
                      {handle.source && (
                        <span className={styles.handleBadge}>
                          {handle.source}
                        </span>
                      )}
                      {handlesPending && !refinedHere && (
                        // instant-painted row a live refine is about to replace
                        <span
                          className={styles.refineDot}
                          aria-hidden="true"
                        />
                      )}
                    </span>
                  )}
                  {source?.connect && (
                    <span
                      role="button"
                      tabIndex={-1}
                      onClick={(event) => {
                        event.stopPropagation();
                        setConnected((current) => ({
                          ...current,
                          [source.key]: !current[source.key],
                        }));
                      }}
                      className={`${styles.connectAction} ${
                        connected[source.key]
                          ? styles.connectOn
                          : styles.connectOff
                      }`}
                    >
                      {connected[source.key] ? "Connected" : "Connect"}
                    </span>
                  )}
                </button>
              );
            })}
            {rows.length === 0 && handleMode && handlesPending && (
              <div className={styles.menuSkeleton} aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            )}
            {rows.length === 0 && !(handleMode && handlesPending) && (
              <div className={styles.menuEmpty}>
                {atToken && query.length < HANDLE_MIN_QUERY
                  ? "Type at least 2 characters to search X"
                  : `No matches for “${query}”`}
              </div>
            )}
            <div className={styles.menuFoot}>
              {handleMode
                ? handlesPending
                  ? rows.length > 0
                    ? "Saved handles first · refining with a live search…"
                    : "Searching X… (a live search costs 2 credits)"
                  : "↑↓ to browse · Enter to tag · fresh results cost 2 credits"
                : atToken
                  ? "Keep typing — live search starts at 2 characters"
                  : menu === "plus"
                    ? "Type to search sources & files"
                    : "Type to search commands"}
            </div>
          </div>
        )}

        {modelOpen && (
          <div
            onMouseLeave={() => setModelHovered(null)}
            className={styles.modelMenu}
            style={{
              left: modelMenuLeft,
              bottom: modelMenuBottom,
              animation:
                "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both",
              transformOrigin: "bottom left",
            }}
          >
            <span
              aria-hidden
              className={styles.glideHighlight}
              style={{
                top: modelBox?.top ?? 0,
                height: modelBox?.height ?? 0,
                opacity:
                  modelBox && modelHovered !== null ? 1 : 0,
              }}
            />
            {MODELS.map((m, i) => (
              <button
                key={m.key}
                type="button"
                ref={(el) => {
                  modelRowRefs.current[i] = el;
                }}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setModelHovered(i)}
                onClick={() => {
                  selectModel(m);
                  inputRef.current?.focus();
                }}
                className={styles.modelRow}
              >
                <span className={styles.modelRowName}>
                  {m.name}
                </span>
                <span className={styles.modelRowTag}>{m.tag}</span>
                <span
                  className={`${styles.modelRowCheck} ${
                    m.key === model.key ? "" : styles.invisible
                  }`}
                >
                  <Icon size={13} strokeWidth={2.5}>
                    <path d="M20 6L9 17l-5-5" />
                  </Icon>
                </span>
              </button>
            ))}
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*,video/*,.pdf,.doc,.docx,.txt,.csv"
          hidden
          onChange={onFiles}
        />

        <div
          className={styles.composerBox}
          style={{
            borderRadius: pill
              ? attachments.length > 0 || wide
                ? 24
                : 999
              : tall
                ? 22
                : 14,
          }}
        >
          <canvas
            ref={glimmRef}
            aria-hidden="true"
            className={styles.glimmCanvas}
            style={{ borderRadius: "inherit" }}
          />
          <span
            ref={measureRef}
            aria-hidden="true"
            className={styles.measure}
          >
            {draft}
          </span>

          {attachments.length > 0 && (
            <div className={styles.attachmentRow}>
              {attachments.map((file, i) => (
                <span
                  key={`${file}-${i}`}
                  className={styles.attachmentChip}
                  style={{
                    animation:
                      "pop-in 200ms cubic-bezier(0.23,1,0.32,1) both",
                  }}
                >
                  <Icon size={12}>
                    <g>
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <path d="M14 2v6h6" />
                    </g>
                  </Icon>
                  <span className={styles.attachmentName}>
                    {file}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove ${file}`}
                    onClick={() =>
                      setAttachments((current) =>
                        current.filter((_, j) => j !== i),
                      )
                    }
                    className={styles.attachmentRemove}
                  >
                    <Icon size={10} strokeWidth={2.5}>
                      <path d="M18 6L6 18M6 6l12 12" />
                    </Icon>
                  </button>
                </span>
              ))}
            </div>
          )}

          <div
            ref={controlsRef}
            className={`${styles.controls} ${
              wide ? styles.controlsWide : ""
            }`}
          >
            <button
              type="button"
              aria-label="Add attachments and sources"
              aria-expanded={plusOpen}
              onClick={() => {
                setModelOpen(false);
                setPlusOpen((current) => !current);
                inputRef.current?.focus();
              }}
              className={`${styles.iconBtn} ${styles.plusBtn} ${
                plusOpen ? styles.iconBtnActive : ""
              }`}
            >
              <Icon size={16} strokeWidth={2}>
                <path d="M12 5v14M5 12h14" />
              </Icon>
            </button>

            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setDismissed(false);
                setPlusOpen(false);
              }}
              onKeyDown={(event) => {
                if (menu && rows.length > 0) {
                  if (
                    event.key === "ArrowDown" ||
                    event.key === "ArrowUp"
                  ) {
                    event.preventDefault();
                    setEngaged(true);
                    setActive(
                      (current) =>
                        (current +
                          (event.key === "ArrowDown"
                            ? 1
                            : rows.length - 1)) %
                        rows.length,
                    );
                    return;
                  }
                  if (
                    (event.key === "Enter" && !event.shiftKey) ||
                    event.key === "Tab"
                  ) {
                    event.preventDefault();
                    pick(rows[Math.min(active, rows.length - 1)]);
                    return;
                  }
                }
                if (event.key === "Escape") {
                  setDismissed(true);
                  closeMenus();
                  return;
                }
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  send();
                }
              }}
              placeholder={
                voiceState === "listening"
                  ? "Listening… tap to send"
                  : voiceState === "transcribing"
                    ? "Transcribing…"
                    : (voiceError ?? (placeholder ?? "Write a message…"))
              }
              aria-label="Prompt"
              className={styles.input}
            />

            <button
              ref={modelRef}
              type="button"
              aria-expanded={modelOpen}
              aria-label="Choose model"
              onClick={() => {
                setPlusOpen(false);
                setModelOpen((current) => !current);
              }}
              className={styles.modelBtn}
            >
              {model.name}
              <span className={styles.modelChev}>
                <Icon size={11} strokeWidth={2.4}>
                  <path d="M6 9l6 6 6-6" />
                </Icon>
              </span>
            </button>

            <button
              type="button"
              aria-label={
                voiceState === "listening"
                  ? "Stop recording and send"
                  : voiceState === "transcribing"
                    ? "Transcribing"
                    : "Talk to Lumi"
              }
              aria-pressed={listening}
              disabled={voiceState === "transcribing"}
              onClick={toggleVoice}
              className={`${styles.iconBtn} ${styles.micBtn} ${
                listening ? styles.micActive : ""
              }`}
            >
              {listening ? (
                <span className={styles.eqBars}>
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className={styles.eqBar}
                      style={{
                        animation: `eq-bounce 900ms ease-in-out ${
                          i * 150
                        }ms infinite`,
                      }}
                    />
                  ))}
                </span>
              ) : (
                <Icon size={15} strokeWidth={2}>
                  <g>
                    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" />
                  </g>
                </Icon>
              )}
            </button>

            <button
              type="button"
              aria-label="Send"
              disabled={!canSend}
              onClick={send}
              className={styles.sendBtn}
              style={{
                background: canSend
                  ? "var(--ink)"
                  : "var(--line-strong)",
                color: canSend
                  ? "var(--surface)"
                  : "var(--ink-2)",
              }}
            >
              <Icon size={16} strokeWidth={2.4}>
                <path d="M12 19V5M5 12l7-7 7 7" />
              </Icon>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
