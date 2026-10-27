import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
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
  streamChatMessage,
  sendChatMessage,
  getProfiles,
  getProfileAnalytics,
  generateChatTitle,
  deleteChatHistory,
  type StreamEvent,
  type ProfileSummary,
  type ProfileAnalytics,
} from "./api/agent";
import styles from "./App.module.css";


type Message = {
  id: number;
  role: "user" | "agent";
  text: string;
  insights?: boolean;
  analytics?: ProfileAnalytics | null;
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

const CHATS_KEY = "lumi_agent_chats";
const ACTIVE_KEY = "lumi_agent_active";
const DRAFTS_KEY = "lumi_agent_drafts";

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
        for (const c of parsed) {
          nextChatId = Math.max(nextChatId, (c.id ?? 0) + 1);
          for (const msg of c.messages ?? []) {
            nextId = Math.max(nextId, (msg.id ?? 0) + 1);
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

/** X bird icon (simple SVG) */
function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.748l7.73-8.835L1.254 2.25H8.08l4.26 5.634 5.905-5.634zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

/** Detect if a markdown link is a "Connect X" / OAuth / platform auth link */
function isConnectLink(text: string, _url: string): boolean {
  const low = text.toLowerCase();
  return low.includes("connect") || low.includes("link") || low.includes("authorize");
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
  onPill,
}: {
  text: string;
  analytics?: ProfileAnalytics | null;
  onPill?: (t: string) => void;
}) {
  const nodes = useMemo(() => {
    // Split text into paragraphs first
    const paragraphs = text.split(/\n\n+/);
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
          if (isConnectLink(label, url)) {
            parts.push(
              <a key={m.index} href={url} target="_blank" rel="noopener noreferrer" className={styles.connectCard}>
                <XIcon className={styles.connectCardIcon} />
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
  }, [text]);

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
  const [view, setView] = useState<"chat" | "chronic" | "settings">("chat");
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection>("profile");
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profilesLoaded, setProfilesLoaded] = useState(false);
  const [analytics, setAnalytics] = useState<ProfileAnalytics | null>(null);

  useEffect(() => {
    getProfiles()
      .then((data) => {
        setProfiles(data);
        setProfilesLoaded(true);
        // Fetch analytics for the first (active) profile
        if (data.length > 0) {
          getProfileAnalytics(data[0].id).then((a) => {
            if (a) setAnalytics(a);
          });
        }
      })
      .catch(() => setProfilesLoaded(true));
  }, [view]);

  const hasConnectedAccounts = profiles.length > 0;

  const runCounterRef = useRef(0);
  const settledReplyRef = useRef(0);
  const pendingChatIdRef = useRef(0);

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

  useEffect(() => {
    try {
      localStorage.setItem(CHATS_KEY, JSON.stringify(chats));
      localStorage.setItem(ACTIVE_KEY, String(activeId));
    } catch {
      // storage unavailable (private mode etc.) - ignore
    }
  }, [chats, activeId]);

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
    if (!text) return;
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

    const startTime = performance.now();
    const liveSteps: SimStep[] = [...initialScript.steps];

    setActiveRun({
      runId,
      script: initialScript,
      startedAt: startTime,
    });
    setBusy(true);

    (async () => {
      try {
        const activeProfileId = profiles.length > 0 ? profiles[0].id : 1;
        const result = await streamChatMessage(activeProfileId, text, (evt: StreamEvent) => {
          if (evt.type === "tool_start") {
            const toolName = evt.tool;
            const args = evt.arguments || {};
            let label = `Executing ${toolName}...`;
            let kind: SimStepKind = "action";
            // The connected account's platform drives the header icon: steps
            // marked "social" crossfade the ball into that platform's logo.
            const activePlatform: string = profiles[0]?.platform || "x";
            const activeHandle = profiles[0]?.handle || "";
            // The connected account's face — same unavatar source the Sidebar uses.
            const activeAvatarUrl = activeHandle
              ? `https://unavatar.io/${activePlatform === "x" ? "x" : activePlatform}/${activeHandle}`
              : "";
            let platforms: string[] = [activePlatform];
            let avatarUrl: string | undefined;

            if (toolName === "connect_account") {
              label = "Generating secure X authorization link...";
              kind = "action";
              platforms = ["x"];
            } else if (toolName === "check_niche_trends") {
              label = `Searching high-impression peer posts (${args.query || "niche"})`;
              kind = "social";
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
              platforms = [args.target_platform || "x"];
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
        });

        // Finished streaming response
        const elapsed = Math.round(performance.now() - startTime);
        liveSteps.push({
          id: `step-finish`,
          label: "Synthesizing response",
          kind: "writing",
          durationMs: 400,
        });

        const completedScript: SimScript = {
          id: `live-${runId}`,
          finalDelayMs: 200,
          steps: [...liveSteps],
        };

        const target = pendingChatIdRef.current;
        const analyticsExec = result.tool_executions?.find(
          (e) => e.name === "get_analytics" && e.result,
        );

        setChats((prev) =>
          prev.map((c) =>
            c.id === target
              ? {
                  ...c,
                  messages: [
                    ...c.messages,
                    {
                      id: nextId++,
                      role: "agent",
                      text: result.content?.trim() || "I finished working on that — let me know if you'd like more detail.",
                      analytics: analyticsExec ? analyticsExec.result : undefined,
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

      } catch (err: any) {
        console.warn("Live stream failed, falling back to direct chat:", err);
        const target = pendingChatIdRef.current;
        const activeProfileId = profiles.length > 0 ? profiles[0].id : 1;

        try {
          const direct = await sendChatMessage(activeProfileId, text);
          const elapsed = Math.round(performance.now() - startTime);
          const directAnalyticsExec = direct.tool_executions?.find(
            (e) => e.name === "get_analytics" && e.result,
          );
          setChats((prev) =>
            prev.map((c) =>
              c.id === target
                ? {
                    ...c,
                    messages: [
                      ...c.messages,
                      {
                        id: nextId++,
                        role: "agent",
                        text: direct.content || "Done!",
                        analytics: directAnalyticsExec ? directAnalyticsExec.result : undefined,
                      },
                    ],
                  }
                : c,
            ),
          );
        } catch (fallbackErr: any) {
          const errorMsg =
            fallbackErr?.message ||
            err?.message ||
            "Unable to reach the Lumi agent backend. Please check that the server is running on http://localhost:8000.";

          setChats((prev) =>
            prev.map((c) =>
              c.id === target
                ? {
                    ...c,
                    messages: [
                      ...c.messages,
                      {
                        id: nextId++,
                        role: "agent",
                        text: `⚠️ Connection error: ${errorMsg}`,
                      },
                    ],
                  }
                : c,
            ),
          );
        }
      } finally {
        setActiveRun(null);
        setBusy(false);
      }
    })();
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
    if (profiles.length > 0) {
      deleteChatHistory(profiles[0].id).catch(() => {});
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

  useLayoutEffect(() => {
    const say = new URLSearchParams(window.location.search).get(
      "say",
    );
    if (say && messages.length === 0 && !busy) send(say);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
            profiles.length > 0
              ? { name: profiles[0].name, handle: profiles[0].handle }
              : null
          }
          activeNav={view === "settings" ? "settings" : view === "chronic" ? "chronic" : "home"}
          onNavigate={(key) => {
            if (key === "settings") setView("settings");
            else if (key === "chronic") setView("chronic");
            else setView("chat");
          }}
          onOpenSettings={(section) => {
            setSettingsSection(section as SettingsSection);
            setView("settings");
          }}
        />
        <main className={styles.main}>
          {view === "settings" ? (
            <Settings
              section={settingsSection}
              onSectionChange={setSettingsSection}
              onBack={() => setView("chat")}
            />
          ) : view === "chronic" ? (
            <ChronicOnline
              profileId={profiles.length > 0 ? profiles[0].id : 1}
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
                              onPill={(t) => handleInput(t)}
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
                <div
                  className={`${styles.edge} ${styles.edgeBottom}`}
                  aria-hidden="true"
                />
              </div>

              <div className={styles.dock}>
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
