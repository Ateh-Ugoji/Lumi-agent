import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import AmbientBackground from "./components/AmbientBackground/AmbientBackground";
import PromptBar from "./components/PromptBar/PromptBar";
import InsightCards from "./components/InsightCards/InsightCards";

import Settings, { type SettingsSection } from "./components/Settings/Settings";
import ChronicOnline from "./components/ChronicOnline/ChronicOnline";
import SidebarNav from "./components/Sidebar/Sidebar";
import ThinkingState from "./components/ThinkingState/ThinkingState";
import AgentThinking from "./components/AgentThinking/AgentThinking";

import {
  scriptById,
  type SimScript,
  type SimStep,
  type SimStepKind,
} from "./simulation/simScripts";
import {
  SUBLINES,
  SUBLINE_ROTATE_JITTER_MS,
  SUBLINE_ROTATE_MIN_MS,
  SUBLINE_STORE_KEY,
} from "./constants/sublines";
import {
  ApiError,
  analyticsFrom,
  connectLinksFrom,
  deleteChatHistory,
  generateChatTitle,
  finishConnect,
  getProfileAnalytics,
  parseCallbackLanding,
  sendChatMessage,
  streamChatMessage,
  agentErrorMessage,
  chatErrorMessage,
  CALLBACK_DONE_URL,
  type CallbackLanding,
  type ConnectLink,
  type ConnectReturn,
  type ProfileAnalytics,
  type StreamEvent,
} from "./api";
import { useAuth } from "./auth/AuthContext";
import { useProfiles } from "./hooks/useProfiles";
import PublishStudio from "./components/Publish/PublishStudio";
import { ACTIVE_KEY, CHATS_KEY, DRAFTS_KEY } from "./session";
import styles from "./App.module.css";
import { speak, stopSpeaking } from "./voice/speak";
import { useSmoothText } from "./reveal/useSmoothText";


type Message = {
  id: number;
  role: "user" | "agent";
  text: string;
  insights?: boolean;
  analytics?: ProfileAnalytics | null;
  /** Connect links the server returned for this reply; only these are drawn as connect cards. */
  connectLinks?: ConnectLink[];
  sim?: { scriptId: string; elapsedMs: number; customScript?: SimScript };
  thinking?: string;
};

type Chat = {
  id: number;
  title: string;
  messages: Message[];
};

const PROMPT_POOL = [
  "Check viral tweets and trending topics in my niche",
  "Repurpose a caption in my voice for LinkedIn and X",
  "Start listening for engagement spikes on my accounts",
  "Analyze winning content frameworks in tech",
  "Audit my creator voice profile from recent posts",
  "What viral hook should I use for a product launch?",
];

const pickPills = () => {
  const shuffled = [...PROMPT_POOL].sort(() => Math.random() - 0.5);
  const count = 2 + Math.floor(Math.random() * 2);
  return shuffled.slice(0, count);
};


let nextId = 1;
let nextChatId = 1;
let sessionPick: number | null = null;

const loadDrafts = (): Record<string, string> => {
  try {
    const raw = localStorage.getItem(DRAFTS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, string>;
      }
    }
  } catch {
    // corrupted storage -> start with no drafts
  }
  return {};
};

const loadChats = (): Chat[] => {
  try {
    const raw = localStorage.getItem(CHATS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Chat[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        // Reissue duplicate message ids: a Vite Fast Refresh re-ran this
        // module (resetting `nextId` to 1) while React state survived, so
        // ids collided. Duplicates break `key` uniqueness AND make an old
        // message share `revealingId` with the fresh reply — its settled
        // onRevealDone then clears the flag and the new reply renders full
        // instantly (no reveal). Healing on load keeps ids unique.
        const seen = new Set<number>();
        for (const c of parsed) {
          nextChatId = Math.max(nextChatId, (c.id ?? 0) + 1);
          for (const msg of c.messages ?? []) {
            let id = msg.id ?? 0;
            if (seen.has(id)) {
              id = nextId++;
              msg.id = id;
            }
            seen.add(id);
            nextId = Math.max(nextId, id + 1);
          }
        }
        return parsed;
      }
    }
  } catch {
    // corrupted storage -> fall through to a fresh chat
  }
  return [{ id: 0, title: "", messages: [] }];
};

const applyEdgeGates = (el: HTMLElement) => {
  const max = Math.max(el.scrollHeight - el.clientHeight, 0);
  const top = max > 0 && el.scrollTop > 4 ? "on" : "off";
  const bottom = max > 0 && max - el.scrollTop > 4 ? "on" : "off";
  const zone = el.parentElement;
  if (el.dataset.edgeTop !== top) el.dataset.edgeTop = top;
  if (el.dataset.edgeBottom !== bottom) el.dataset.edgeBottom = bottom;
  if (zone) {
    if (zone.dataset.edgeTop !== top) zone.dataset.edgeTop = top;
    if (zone.dataset.edgeBottom !== bottom) zone.dataset.edgeBottom = bottom;
  }
};

// Fast Refresh re-runs this module (resetting nextId/nextChatId to 1) but
// preserves React state, so re-derive the counters from storage right away.
// Without this, every hot update makes the next message reuse an existing id.
loadChats();

/** X bird icon (simple SVG) */
function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.748l7.73-8.835L1.254 2.25H8.08l4.26 5.634 5.905-5.634zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

/** The connect link the server returned for this URL, if any. The label text is never a signal. */
function connectLinkFor(url: string, links: ConnectLink[] | undefined): ConnectLink | undefined {
  return links?.find((link) => link.url === url);
}

/**
 * Renders a single agent message with inline markdown:
 * - `[text](url)` → Connect X card (if connect link) or plain <a>
 * - **bold** → <strong>
 * - `code` → <code>
 * - Paragraphs split by double newline
 */
function AgentMessage({
  text,
  analytics,
  connectLinks,
  onPill,
  animate = false,
  scrollRef,
  nearBottomRef,
  onRevealDone,
  flushRef,
}: {
  text: string;
  analytics?: ProfileAnalytics | null;
  connectLinks?: ConnectLink[];
  onPill?: (t: string) => void;
  /** True only for the freshly-streamed reply: reveal it gradually. */
  animate?: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  nearBottomRef?: RefObject<boolean>;
  onRevealDone?: () => void;
  flushRef?: { current: (() => void) | null };
}) {
  // Buffer-and-reveal: while `animate`, the message renders
  // `text.slice(0, shown)` and types itself out at an adaptive speed
  // (reveal/useSmoothText). History/reloads pass animate=false and render
  // the full text instantly — old messages never re-animate.
  const { text: visible, revealing, flush } = useSmoothText(text, animate);

  const nodes = useMemo(() => {
    // Split text into paragraphs first
    const paragraphs = visible.split(/\n\n+/);
    return paragraphs.map((para, pi) => {
      // Tokenise inline: **bold**, `code`, [label](url)
      const INLINE = /(\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)]+)\))/g;
      const parts: React.ReactNode[] = [];
      let last = 0;
      let m: RegExpExecArray | null;
      while ((m = INLINE.exec(para)) !== null) {
        if (m.index > last) parts.push(para.slice(last, m.index));
        if (m[2] !== undefined) {
          // **bold**
          parts.push(<strong key={m.index} className={styles.msgBold}>{m[2]}</strong>);
        } else if (m[3] !== undefined) {
          // `code`
          parts.push(<code key={m.index} className={styles.msgCode}>{m[3]}</code>);
        } else if (m[4] !== undefined && m[5]) {
          // [label](url)
          const label = m[4];
          const url = m[5];
          const connect = connectLinkFor(url, connectLinks);
          if (connect) {
            parts.push(
              <a key={m.index} href={url} target="_blank" rel="noopener noreferrer" className={styles.connectCard}>
                {connect.platform === "x" && <XIcon className={styles.connectCardIcon} />}
                {label}
              </a>
            );
          } else {
            parts.push(
              <a key={m.index} href={url} target="_blank" rel="noopener noreferrer" className={styles.msgLink}>{label}</a>
            );
          }
        }
        last = m.index + m[0].length;
      }
      if (last < para.length) parts.push(para.slice(last));
      // single-newline breaks inside a paragraph
      const withBreaks: React.ReactNode[] = [];
      parts.forEach((node, ni) => {
        if (typeof node === "string") {
          const lines = node.split("\n");
          lines.forEach((ln, li) => {
            if (li > 0) withBreaks.push(<br key={`${pi}-${ni}-br${li}`} />);
            if (ln) withBreaks.push(ln);
          });
        } else {
          withBreaks.push(node);
        }
      });
      return <p key={pi} className={styles.msgText}>{withBreaks}</p>;
    });
  }, [visible, connectLinks]);

  // While revealing, keep the growing text pinned to the bottom — only if the
  // user was already near the bottom (never fight manual scrolling).
  useLayoutEffect(() => {
    if (!animate || !revealing) return;
    const el = scrollRef?.current;
    if (!el || !nearBottomRef?.current) return;
    const max = Math.max(el.scrollHeight - el.clientHeight, 0);
    el.scrollTop = max;
  }, [visible, animate, revealing, scrollRef, nearBottomRef]);

  // Expose flush() to the Stop button while this message is the one revealing.
  useEffect(() => {
    if (!animate || !flushRef) return;
    flushRef.current = flush;
    return () => {
      if (flushRef.current === flush) flushRef.current = null;
    };
  }, [animate, flush, flushRef]);

  // Reveal settled: let the App clear its "this message is revealing" flag.
  useEffect(() => {
    if (animate && !revealing) onRevealDone?.();
  }, [animate, revealing, onRevealDone]);

  return (
    <>
      {nodes}
      {analytics && (
        <div className={styles.insightSlot}>
          <InsightCards analytics={analytics} onPill={onPill} />
        </div>
      )}
    </>
  );
}

export default function App() {
  const [chats, setChats] = useState<Chat[]>(loadChats);
  const [activeId, setActiveId] = useState(() => {
    const saved = Number(localStorage.getItem(ACTIVE_KEY));
    return loadChats().some((c) => c.id === saved) ? saved : 0;
  });
  const draftsRef = useRef<Record<string, string> | null>(null);
  if (draftsRef.current === null) draftsRef.current = loadDrafts();

  const draftFor = (id: number) => draftsRef.current?.[String(id)] ?? "";

  const [input, setInput] = useState(() => draftFor(activeId));

  const persistDrafts = () => {
    try {
      localStorage.setItem(DRAFTS_KEY, JSON.stringify(draftsRef.current));
    } catch {
      // storage unavailable -> drafts stay in memory for this session
    }
  };

  const handleInput = (value: string) => {
    setInput(value);
    if (draftsRef.current) draftsRef.current[String(activeId)] = value;
    persistDrafts();
  };

  useEffect(() => {
    setInput(draftFor(activeId));
  }, [activeId]);
  const [busy, setBusy] = useState(false);
  // Id of the freshly-streamed agent reply that is revealing right now
  // (null = nothing animating; history/reloads never re-animate).
  const [revealingId, setRevealingId] = useState<number | null>(null);
  type ActiveRun = {
    runId: number;
    script: SimScript;
    startedAt: number;
  };

  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    if (!activeRun) {
      setElapsedMs(0);
      return;
    }
    const timer = window.setInterval(() => {
      setElapsedMs(Math.round(performance.now() - activeRun.startedAt));
    }, 100);
    return () => window.clearInterval(timer);
  }, [activeRun]);

  const [pills, setPills] = useState<string[]>(pickPills);
  const [subline, setSubline] = useState<string | null>(null);
  const [sublineShown, setSublineShown] = useState(false);
  const [view, setView] = useState<"chat" | "chronic" | "publish" | "settings">("chat");
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection>("profile");
  const { user, logout } = useAuth();
  const {
    profiles,
    activeId: activeProfileId,
    active: activeProfile,
    select: selectProfile,
    create: createProfile,
    refresh: refreshProfiles,
  } = useProfiles();
  const [analytics, setAnalytics] = useState<ProfileAnalytics | null>(null);
  const [connectReturn, setConnectReturn] = useState<ConnectReturn | null>(null);

  useEffect(() => {
    setAnalytics(null);
    if (activeProfileId === null) return;
    let cancelled = false;
    getProfileAnalytics(activeProfileId).then((a) => {
      if (!cancelled && a) setAnalytics(a);
    });
    return () => {
      cancelled = true;
    };
  }, [activeProfileId]);

  // The provider redirects the browser to /connections/<provider>/callback on this app. Finish the
  // grant here with this user's Token: the server refuses a state that someone else started. The
  // URL is replaced at once, so a reload or a shared link never repeats the grant.
  const landingRef = useRef<CallbackLanding | null>(null);
  const landingSentRef = useRef(false);
  useLayoutEffect(() => {
    const found = parseCallbackLanding(window.location.pathname, window.location.search);
    if (!found) return;
    landingRef.current = found;
    window.history.replaceState(null, "", CALLBACK_DONE_URL);
    setSettingsSection(found.kind !== "pfm" && found.provider === "google" ? "connectors" : "social");
    setView("settings");
  }, []);
  useEffect(() => {
    const landing = landingRef.current;
    if (!landing || landingSentRef.current) return;
    landingSentRef.current = true;
    finishConnect(landing)
      .then((done) => {
        setConnectReturn(
          done.connected
            ? { kind: "connected", provider: done.provider }
            : {
                kind: "error",
                code: "connections.no_accounts",
                provider: landing.kind === "pfm" ? "pfm" : landing.provider,
              },
        );
        refreshProfiles();
      })
      .catch((err: unknown) => {
        const code = err instanceof ApiError ? err.code : "internal_error";
        setConnectReturn({
          kind: "error",
          code,
          provider: landing.kind === "pfm" ? "pfm" : landing.provider,
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runCounterRef = useRef(0);
  const settledReplyRef = useRef(0);
  const pendingChatIdRef = useRef(0);
  // True when the in-flight send came from the mic — the reply is spoken aloud.
  const voiceReplyRef = useRef(false);
  // In-flight /chat/stream fetch — aborted by the Stop button.
  const abortRef = useRef<AbortController | null>(null);
  // Registered by the revealing message so Stop can flush it to full text.
  const flushRef = useRef<(() => void) | null>(null);

  const streamRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const handledUserRef = useRef<HTMLElement | null>(null);
  const handledAgentRef = useRef<HTMLElement | null>(null);

  const activeChat = chats.find((c) => c.id === activeId);
  const messages = activeChat ? activeChat.messages : [];

  useEffect(() => {
    const el = streamRef.current;
    if (!el) return;
    let frame = 0;
    const apply = () => {
      frame = 0;
      applyEdgeGates(el);
    };
    const onScroll = () => {
      const max = Math.max(el.scrollHeight - el.clientHeight, 0);
      nearBottomRef.current = max - el.scrollTop < 96;
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const onResize = () => {
      if (!frame) frame = requestAnimationFrame(apply);
    };
    applyEdgeGates(el);
    el.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [view]);

  // Heal duplicate message ids in LIVE state (a Fast Refresh used to reset
  // nextId while this state survived). Idempotent: returns the same
  // reference when ids are already unique, so it never re-renders on its own.
  useEffect(() => {
    setChats((prev) => {
      const seen = new Set<number>();
      let dirty = false;
      const healed = prev.map((c) => ({
        ...c,
        messages: c.messages.map((m) => {
          if (seen.has(m.id)) {
            dirty = true;
            const id = nextId++;
            seen.add(id);
            nextId = Math.max(nextId, id + 1);
            return { ...m, id };
          }
          seen.add(m.id);
          nextId = Math.max(nextId, m.id + 1);
          return m;
        }),
      }));
      return dirty ? healed : prev;
    });
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(CHATS_KEY, JSON.stringify(chats));
      localStorage.setItem(ACTIVE_KEY, String(activeId));
    } catch {
      // storage unavailable (private mode etc.) - ignore
    }
  }, [chats, activeId]);

  // Leaving a chat mid-reveal (or returning to it later) shows full text —
  // the reveal only ever plays once, right after the reply streams in.
  useEffect(() => {
    setRevealingId(null);
  }, [activeId]);

  useEffect(() => {
    let alive = true;
    let rotateTimer = 0;
    let fadeTimer = 0;

    const readLast = (): number => {
      try {
        const v = Number(localStorage.getItem(SUBLINE_STORE_KEY));
        return Number.isInteger(v) && v >= 0 && v < SUBLINES.length ? v : -1;
      } catch {
        return -1;
      }
    };
    const writeLast = (i: number) => {
      try {
        localStorage.setItem(SUBLINE_STORE_KEY, String(i));
      } catch {
        // storage unavailable - rotation still works, just no repeat-guard
      }
    };
    const pickAvoiding = (avoid: number): number => {
      if (SUBLINES.length < 2) return 0;
      let i = Math.floor(Math.random() * SUBLINES.length);
      while (i === avoid) i = Math.floor(Math.random() * SUBLINES.length);
      return i;
    };
    const commit = (i: number) => {
      setSubline(SUBLINES[i]);
      writeLast(i);
      requestAnimationFrame(() => {
        if (alive) setSublineShown(true);
      });
    };

    // module scope: StrictMode re-runs this effect on mount - pick exactly
    // once per real page load so the repeat-guard advances only once too
    if (sessionPick === null) sessionPick = pickAvoiding(readLast());
    setSubline(SUBLINES[sessionPick]);
    writeLast(sessionPick);
    requestAnimationFrame(() => {
      if (alive) setSublineShown(true);
    });

    const schedule = () => {
      const delay =
        SUBLINE_ROTATE_MIN_MS + Math.random() * SUBLINE_ROTATE_JITTER_MS;
      rotateTimer = window.setTimeout(() => {
        if (!alive) return;
        setSublineShown(false);
        fadeTimer = window.setTimeout(() => {
          if (!alive) return;
          sessionPick = pickAvoiding(readLast());
          commit(sessionPick);
          schedule();
        }, 220);
      }, delay);
    };
    schedule();

    return () => {
      alive = false;
      window.clearTimeout(rotateTimer);
      window.clearTimeout(fadeTimer);
    };
  }, []);

  useLayoutEffect(() => {
    const el = streamRef.current;
    if (!el) return;
    const max = Math.max(el.scrollHeight - el.clientHeight, 0);
    const users = el.querySelectorAll<HTMLElement>(
      '[data-role="user"]',
    );
    const agents = el.querySelectorAll<HTMLElement>(
      '[data-role="agent"]',
    );
    const lastUser = users[users.length - 1] ?? null;
    const lastAgent = agents[agents.length - 1] ?? null;
    const userNew = lastUser !== null && lastUser !== handledUserRef.current;
    const agentNew =
      lastAgent !== null && lastAgent !== handledAgentRef.current;

    const contentTopOf = (elm: HTMLElement) =>
      elm.getBoundingClientRect().top -
      el.getBoundingClientRect().top +
      el.scrollTop;

    if (nearBottomRef.current) {
      if (agentNew && lastUser) {
        const ub = lastUser.getBoundingClientRect();
        const s = el.getBoundingClientRect();
        const userInside = ub.top >= s.top - 1 && ub.bottom <= s.bottom + 1;
        el.scrollTop = userInside
          ? max
          : Math.min(Math.max(contentTopOf(lastUser) - 12, 0), max);
      } else {
        el.scrollTop = max;
      }
    } else if (userNew && lastUser) {
      el.scrollTop = Math.min(
        Math.max(contentTopOf(lastUser) - 12, 0),
        max,
      );
    } else if (agentNew && lastAgent) {
      const b = lastAgent.getBoundingClientRect();
      const s = el.getBoundingClientRect();
      const inside = b.top >= s.top - 1 && b.bottom <= s.bottom + 1;
      if (!inside) {
        el.scrollTop = Math.min(
          Math.max(
            contentTopOf(lastAgent) + b.height - el.clientHeight + 16,
            0,
          ),
          max,
        );
      }
    }
    handledUserRef.current = lastUser;
    handledAgentRef.current = lastAgent;
    nearBottomRef.current = max - el.scrollTop < 96;
    applyEdgeGates(el);
  }, [messages, busy, view]);

  const send = (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    if (activeProfileId === null) {
      // Chat works on a profile. Without one, send the user where it is created.
      setSettingsSection("profile");
      setView("settings");
      return;
    }
    pendingChatIdRef.current = activeId;
    const targetChatId = activeId;
    const currentChat = chats.find((c) => c.id === targetChatId);
    const isFirstMessage = !currentChat || currentChat.messages.length === 0 || !currentChat.title;

    setChats((prev) =>
      prev.map((c) =>
        c.id === targetChatId
          ? {
              ...c,
              title:
                c.title ||
                (text.length > 28 ? `${text.slice(0, 28)}…` : text),
              messages: [
                ...c.messages,
                { id: nextId++, role: "user", text },
              ],
            }
          : c,
      ),
    );

    if (isFirstMessage) {
      generateChatTitle(text)
        .then((aiTitle) => {
          if (aiTitle) {
            setChats((prev) =>
              prev.map((c) => (c.id === targetChatId ? { ...c, title: aiTitle } : c)),
            );
          }
        })
        .catch(() => {});
    }

    handleInput("");
    runCounterRef.current += 1;
    const runId = runCounterRef.current;

    const initialScript: SimScript = {
      id: `live-${runId}`,
      finalDelayMs: 200,
      steps: [
        {
          id: "step-init",
          label: "Thinking...",
          kind: "analysis",
          durationMs: 1200,
        },
      ],
    };

    const chatProfileId = activeProfileId;
    const startTime = performance.now();
    const liveSteps: SimStep[] = [...initialScript.steps];

    setActiveRun({
      runId,
      script: initialScript,
      startedAt: startTime,
    });
    setBusy(true);

    // One abort controller per run: the Stop button cancels the fetch, and
    // the catch below must then NOT fall through to the direct-POST retry
    // (that would re-run the whole agent turn server-side).
    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        let streamError: string | null = null;
        const result = await streamChatMessage(chatProfileId, text, (evt: StreamEvent) => {
          if (evt.type === "error") {
            // Agent failures arrive as a normal SSE event, not a rejected HTTP
            // request. Dropping them makes a crashed run look like a success
            // with an empty reply.
            streamError = agentErrorMessage(evt.code, evt.error);
            return;
          }
          if (evt.type === "tool_start") {
            const toolName = evt.tool;
            const args = evt.arguments || {};
            let label = `Executing ${toolName}...`;
            let kind: SimStepKind = "action";
            // The connected account's platform drives the header icon: steps
            // marked "social" crossfade the ball into that platform's logo.
            const activePlatform: string = activeProfile?.platform || "x";
            const activeHandle = activeProfile?.handle || "";
            // The connected account's face — same unavatar source the Sidebar uses.
            const activeAvatarUrl = activeHandle
              ? `https://unavatar.io/${activePlatform === "x" ? "x" : activePlatform}/${activeHandle}`
              : "";
            let platforms: string[] = [activePlatform];
            let avatarUrl: string | undefined;

            if (toolName === "connect_account") {
              const target = String(args.platform || activeProfile?.platform || "x");
              label = `Generating secure ${target} authorization link...`;
              kind = "action";
              platforms = [target];
            } else if (toolName === "check_niche_trends") {
              label = `Searching high-impression peer posts (${args.query || "niche"})`;
              kind = "social";
              platforms = ["x"];
            } else if (toolName === "save_user_request") {
              label = "Saving your requested handles (as user requests, not peers)";
              kind = "action";
              platforms = ["x"];
            } else if (toolName === "discover_and_extract_niche_frameworks") {
              label = `Extracting winning content frameworks (${args.niche || "tech"})`;
              kind = "analysis";
              platforms = ["x", "linkedin"];
            } else if (toolName === "extract_voice_profile") {
              label = "Extracting your creator voice profile";
              kind = "social";
              platforms = [activePlatform];
            } else if (toolName === "get_posts") {
              label = "Fetching your recent posts";
              kind = "social";
              platforms = [activePlatform];
            } else if (toolName === "get_user_activity") {
              label = "Reviewing your replies and activity";
              kind = "social";
              platforms = [activePlatform];
            } else if (toolName === "get_analytics") {
              label = "Pulling your performance analytics";
              kind = "social";
              platforms = [activePlatform];
            } else if (toolName === "check_trending") {
              label = "Watching your posts for velocity spikes";
              kind = "social";
              platforms = [activePlatform];
            } else if (toolName === "backfill_posts") {
              label = "Backfilling your post history";
              kind = "social";
              platforms = [activePlatform];
            } else if (toolName === "repurpose_caption") {
              label = `Repurposing caption for ${args.target_platform || "socials"}`;
              kind = "writing";
              platforms = [String(args.target_platform || "x")];
            }


            // Account-walking steps show that account's face in the header;
            // the niche search keeps its X logo until results land (tool_done
            // then swaps in the first account it actually found).
            if (kind === "social" && toolName !== "check_niche_trends") {
              avatarUrl = activeAvatarUrl;
            }

            liveSteps.push({
              id: `tool-${liveSteps.length}`,
              label,
              kind,
              durationMs: 1500,
              platforms,
              avatar_url: avatarUrl,
            });

            setActiveRun({
              runId,
              script: {
                id: `live-${runId}`,
                finalDelayMs: 200,
                steps: [...liveSteps],
              },
              startedAt: startTime,
            });
          } else if (evt.type === "tool_done") {
            const lastStep = liveSteps[liveSteps.length - 1];
            if (lastStep) {
              lastStep.detail = "Completed";
              if (evt.sample_posts && evt.sample_posts.length > 0) {
                lastStep.samplePosts = evt.sample_posts.slice(0, 4);
                lastStep.meta = `${evt.sample_posts.length} discovered posts`;
                // Results landed: the X logo morphs into the first account found.
                const first = evt.sample_posts[0];
                if (!lastStep.avatar_url) {
                  lastStep.avatar_url =
                    first.avatar_url || (first.author ? `https://unavatar.io/x/${first.author}` : undefined);
                }
              }
            }
            setActiveRun({
              runId,
              script: {
                id: `live-${runId}`,
                finalDelayMs: 200,
                steps: [...liveSteps],
              },
              startedAt: startTime,
            });
          }
        }, { signal: controller.signal });

        // Finished streaming response
        const elapsed = Math.round(performance.now() - startTime);
        if (streamError) {
          const lastStep = liveSteps[liveSteps.length - 1];
          if (lastStep) lastStep.detail = "Failed";
        } else {
          liveSteps.push({
            id: `step-finish`,
            label: "Synthesizing response",
            kind: "writing",
            durationMs: 400,
          });
        }

        const completedScript: SimScript = {
          id: `live-${runId}`,
          finalDelayMs: 200,
          steps: [...liveSteps],
        };

        const target = pendingChatIdRef.current;

        const replyText = streamError
          ? `⚠️ ${streamError}`
          : result.content?.trim() ||
            "I finished working on that — let me know if you'd like more detail.";

        // Pre-generate the reply id so the same batch can mark it as
        // "revealing"; the updater itself stays pure (StrictMode-safe).
        const replyId = nextId++;
        setRevealingId(replyId);
        setChats((prev) =>
          prev.map((c) =>
            c.id === target
              ? {
                  ...c,
                  messages: [
                    ...c.messages,
                    {
                      id: replyId,
                      role: "agent",
                      text: replyText,
                      analytics: analyticsFrom(result.tool_executions),
                      connectLinks: connectLinksFrom(result.tool_executions),
                      sim: {
                        scriptId: completedScript.id,
                        elapsedMs: elapsed,
                        customScript: completedScript,
                      },
                    },
                  ],
                }
              : c,
          ),
        );

        if (voiceReplyRef.current) {
          voiceReplyRef.current = false;
          speak(replyText.replace(/^⚠️\s*/, ""));
        }

      } catch (err: any) {
        if (controller.signal.aborted) {
          // Stop pressed: an honest "stopped" note — and never the direct
          // POST below, which would re-run the whole agent turn server-side.
          voiceReplyRef.current = false;
          const stoppedTarget = pendingChatIdRef.current;
          const stoppedId = nextId++;
          setRevealingId(stoppedId);
          setChats((prev) =>
            prev.map((c) =>
              c.id === stoppedTarget
                ? {
                    ...c,
                    messages: [
                      ...c.messages,
                      { id: stoppedId, role: "agent", text: "⏹ Stopped — I didn't finish that." },
                    ],
                  }
                : c,
            ),
          );
          return; // finally still clears activeRun / busy
        }
        console.warn("Live stream failed, falling back to direct chat:", err);
        const target = pendingChatIdRef.current;
        const noRetryCodes = ["agent_timeout", "stream_incomplete", "bad_response"];
        if (
          err instanceof ApiError &&
          ((err.status >= 400 && err.status < 500) || noRetryCodes.includes(err.code))
        ) {
          // The server answered and refused, or the agent already started and went silent:
          // running the turn again would only repeat the refusal or double the work.
          const refusedId = nextId++;
          setRevealingId(refusedId);
          setChats((prev) =>
            prev.map((c) =>
              c.id === target
                ? {
                    ...c,
                    messages: [
                      ...c.messages,
                      { id: refusedId, role: "agent", text: `⚠️ ${chatErrorMessage(err)}` },
                    ],
                  }
                : c,
            ),
          );
          return;
        }

        try {
          const direct = await sendChatMessage(chatProfileId, text);
          const elapsed = Math.round(performance.now() - startTime);
          const directId = nextId++;
          setRevealingId(directId);
          setChats((prev) =>
            prev.map((c) =>
              c.id === target
                ? {
                    ...c,
                    messages: [
                      ...c.messages,
                      {
                        id: directId,
                        role: "agent",
                        text: direct.content || "Done!",
                        analytics: analyticsFrom(direct.tool_executions),
                        connectLinks: connectLinksFrom(direct.tool_executions),
                      },
                    ],
                  }
                : c,
            ),
          );
          if (voiceReplyRef.current) {
            voiceReplyRef.current = false;
            speak(direct.content || "Done!");
          }
        } catch (fallbackErr: any) {
          const errorMsg = chatErrorMessage(fallbackErr ?? err);

          const errorId = nextId++;
          setRevealingId(errorId);
          setChats((prev) =>
            prev.map((c) =>
              c.id === target
                ? {
                    ...c,
                    messages: [
                      ...c.messages,
                      {
                        id: errorId,
                        role: "agent",
                        text: `⚠️ ${errorMsg}`,
                      },
                    ],
                  }
                : c,
            ),
          );
          if (voiceReplyRef.current) {
            voiceReplyRef.current = false;
            speak(`Sorry — I could not reach the backend. ${errorMsg}`);
          }
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setActiveRun(null);
        setBusy(false);
      }
    })();
  };

  // Stop: abort the in-flight stream, and flush any mid-flight reveal so
  // everything received so far appears at once.
  const stopRun = () => {
    abortRef.current?.abort();
    flushRef.current?.();
  };

  const resetChat = () => {
    const current = chats.find((c) => c.id === activeId);
    const withMessages = chats.filter((c) => c.messages.length > 0);
    if (current && current.messages.length === 0) {
      setChats([...withMessages, current]);
      setActiveId(current.id);
      if (draftsRef.current) delete draftsRef.current[String(current.id)];
      persistDrafts();
    } else {
      const fresh = { id: nextChatId++, title: "", messages: [] };
      setChats([...withMessages, fresh]);
      setActiveId(fresh.id);
    }
    setActiveRun(null);
    setBusy(false);
    setRevealingId(null);
    setInput("");
    setPills(pickPills());
  };

  const handleDeleteChat = (idStr: string) => {
    const targetId = Number(idStr);
    setChats((prev) => {
      const remaining = prev.filter((c) => c.id !== targetId);
      const nextChats = remaining.length > 0 ? remaining : [{ id: nextChatId++, title: "", messages: [] }];
      if (activeId === targetId) {
        setActiveId(nextChats[0].id);
      }
      try {
        localStorage.setItem(CHATS_KEY, JSON.stringify(nextChats));
      } catch {}
      return nextChats;
    });
    if (draftsRef.current) {
      delete draftsRef.current[idStr];
      persistDrafts();
    }
  };

  const live = activeRun
    ? {
        runId: activeRun.runId,
        script: activeRun.script,
        status: "running" as const,
        elapsedMs,
        // First step that has NOT completed; -1 = everything started has
        // finished (the model is reasoning between turns) → nothing spins.
        index: activeRun.script.steps.findIndex(
          (s) => s.detail !== "Completed",
        ),
        startedCount: activeRun.script.steps.length,
      }
    : null;


  const recents = chats
    .filter((c) => c.messages.length > 0)
    .slice()
    .reverse()
    .map((c) => ({ id: String(c.id), label: c.title || "Untitled" }));

  return (
    <div className={styles.page}>
      <AmbientBackground />
      <div className={styles.shell}>
        <SidebarNav
          fill
          onNewChat={resetChat}
          onDeleteChat={handleDeleteChat}
          onPick={(id) => {
            setActiveId(Number(id));
            setView("chat");
          }}
          activeTitle={activeChat ? activeChat.title || null : null}

          recents={recents}
          userProfile={
            activeProfile ? { name: activeProfile.name, handle: activeProfile.handle } : null
          }
          activeNav={
            view === "settings"
              ? "settings"
              : view === "chronic"
                ? "chronic"
                : view === "publish"
                  ? "publish"
                  : "home"
          }
          onNavigate={(key) => {
            if (key === "settings") setView("settings");
            else if (key === "chronic") setView("chronic");
            else if (key === "publish") setView("publish");
            else setView("chat");
          }}
          onOpenSettings={(section) => {
            setSettingsSection(section as SettingsSection);
            setView("settings");
          }}
          onSignOut={() => void logout()}
          footerLabel="Log out"
          onFooterClick={() => void logout()}
        />
        <main className={styles.main}>
          {view === "settings" ? (
            <Settings
              section={settingsSection}
              onSectionChange={setSettingsSection}
              onBack={() => setView("chat")}
              user={user}
              profiles={profiles}
              activeProfileId={activeProfileId}
              onSelectProfile={selectProfile}
              onCreateProfile={createProfile}
              onClearHistory={deleteChatHistory}
              onLogout={() => void logout()}
              returned={connectReturn}
              onDismissReturn={() => setConnectReturn(null)}
              onConnectionsChanged={() => void refreshProfiles()}
            />
          ) : view === "publish" ? (
            <PublishStudio
              profileId={activeProfileId}
              handle={activeProfile?.handle ?? null}
              onOpenConnections={() => {
                setSettingsSection("social");
                setView("settings");
              }}
            />
          ) : view === "chronic" ? (
            <ChronicOnline
              profileId={activeProfileId}
              onRepurpose={(caption, author) => {
                setView("chat");
                send(
                  `Repurpose this viral post from @${author} in my voice for X, LinkedIn, and Instagram:\n\n"${caption}"`,
                );
              }}
              onBack={() => setView("chat")}
            />
          ) : (

            <>
              <header className={styles.header}>
                <h1 className={styles.title}>
                  {activeChat && activeChat.title ? activeChat.title : "New chat"}
                </h1>
              </header>

              <div
                className={styles.streamZone}
                data-edge-top="off"
                data-edge-bottom="off"
              >
                <div
                  className={`${styles.edge} ${styles.edgeTop}`}
                  aria-hidden="true"
                />
                <div
                  className={styles.stream}
                  ref={streamRef}
                  data-edge-top="off"
                  data-edge-bottom="off"
                >
                  <div className={styles.streamInner}>
                    {messages.length === 0 && !busy && (
                      <div className={styles.empty}>
                        <span className={styles.emptyMark}>Lumi</span>
                        <p
                          className={styles.emptyText}
                          aria-live="polite"
                          data-subline-shown={sublineShown ? "true" : "false"}
                        >
                          {subline}
                        </p>
                      </div>
                    )}
                    {messages.map((m) => (
                      <Fragment key={m.id}>
                        {m.role === "agent" && m.sim && (
                          <div className={styles.thinkingSlot}>
                            <AgentThinking
                              settled
                              script={m.sim.customScript || scriptById(m.sim.scriptId)}
                              elapsedMs={m.sim.elapsedMs}
                            />
                          </div>
                        )}
                        {m.role === "agent" && !m.sim && m.thinking && (
                          <div className={styles.thinkingSlot}>
                            <ThinkingState variant={m.thinking} settled />
                          </div>
                        )}
                        <div
                          data-role={m.role}
                          className={
                            m.role === "user"
                              ? styles.userMsg
                              : styles.agentMsg
                          }
                        >
                          {m.role === "agent" && (
                            <span className={styles.agentLabel}>Agent</span>
                          )}
                          {m.role === "agent" ? (
                            <AgentMessage
                              text={m.text}
                              analytics={m.analytics ?? (m.insights ? analytics : null)}
                              connectLinks={m.connectLinks}
                              onPill={(t) => handleInput(t)}
                              animate={m.id === revealingId}
                              scrollRef={streamRef}
                              nearBottomRef={nearBottomRef}
                              onRevealDone={() =>
                                setRevealingId((cur) => (cur === m.id ? null : cur))
                              }
                              flushRef={flushRef}
                            />
                          ) : (
                            <p className={styles.msgText}>{m.text}</p>
                          )}
                        </div>
                      </Fragment>

                    ))}
                    {live && (
                      <AgentThinking
                        key={live.runId}
                        script={live.script}
                        status={live.status}
                        elapsedMs={live.elapsedMs}
                        index={live.index}
                        startedCount={live.startedCount}
                      />
                    )}
                  </div>
                </div>
              </div>

              <div className={styles.dock}>
                {(busy || revealingId !== null) && (
                  <div className={styles.stopRow}>
                    <button
                      type="button"
                      className={styles.stopBtn}
                      onClick={stopRun}
                    >
                      ■ Stop
                    </button>
                  </div>
                )}
                {messages.length === 0 && !busy && (
                  <div className={styles.pills}>
                    {pills.map((p) => (
                      <button
                        key={p}
                        type="button"
                        className={styles.pill}
                        onClick={() => handleInput(p)}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                )}
                <PromptBar
                  demo={false}
                  text={input}
                  onTextChange={handleInput}
                  onSend={send}
                  busy={busy}
                />
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
