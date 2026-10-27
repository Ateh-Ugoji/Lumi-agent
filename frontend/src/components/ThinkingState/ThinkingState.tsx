import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import SocialIcon from "./SocialIcons";
import styles from "./ThinkingState.module.css";

const STAGES = [800, 600, 1800, 2600, 1600];
const NO_STEPS: number[] = [];

function useSequence(steps: number[]) {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    if (stage >= steps.length - 1) return;
    const t = setTimeout(() => setStage((s) => s + 1), steps[stage]);
    return () => clearTimeout(t);
  }, [stage, steps]);
  return stage;
}

type Row = {
  primary: string;
  secondary?: string;
  mono?: boolean;
  add?: number;
  del?: number;
  href?: string;
  logo?: string;
};

const VARIANTS: Record<
  string,
  { active: string; done: string; rows: Row[]; query?: string }
> = {
  Steps: {
    active: "Thinking",
    done: "Thought for 4 seconds",
    rows: [
      { primary: "Reading your recent posts" },
      { primary: "Scoring engagement signals" },
      { primary: "Comparing platform tone", secondary: "6 platforms" },
      { primary: "Writing the reply" },
    ],
  },
  Reasoning: {
    active: "Thinking",
    done: "Thought for 4 seconds",
    rows: [
      {
        primary:
          "Engagement dipped this week — carousels outperforming single images.",
      },
      {
        primary:
          "I should check the scheduled drafts before suggesting a new posting slot.",
      },
    ],
  },
  Search: {
    active: "Searching the web",
    done: "Searched the web",
    query: "best posting time for devtool audiences",
    rows: [
      {
        primary: "Sprout Social",
        secondary: "sproutsocial.com",
        href: "https://sproutsocial.com/insights/best-times-to-post/",
        logo: "tiktok",
      },
      {
        primary: "Hootsuite",
        secondary: "hootsuite.com",
        href: "https://blog.hootsuite.com/best-time-to-post-on-social-media/",
        logo: "youtube",
      },
      {
        primary: "Buffer",
        secondary: "buffer.com",
        href: "https://buffer.com/resources/best-time-to-post-on-social-media/",
        logo: "facebook",
      },
    ],
  },
  Social: {
    active: "Reading your socials",
    done: "Read your socials",
    query: "posts mentioning lumi this week",
    rows: [
      {
        primary: "@lumi",
        secondary: "x.com",
        href: "https://x.com",
        logo: "x",
      },
      {
        primary: "Lumi",
        secondary: "instagram.com",
        href: "https://instagram.com",
        logo: "instagram",
      },
      {
        primary: "Lumi Social",
        secondary: "linkedin.com",
        href: "https://linkedin.com",
        logo: "linkedin",
      },
    ],
  },
  Coding: {
    active: "Running tools",
    done: "Ran 3 tools",
    rows: [
      { primary: "Read", secondary: "posts.ts", mono: true },
      {
        primary: "Edit",
        secondary: "Scheduler.tsx",
        mono: true,
        add: 74,
        del: 41,
      },
      { primary: "Run", secondary: "npm run analyze", mono: true },
    ],
  },
};

function Dot({ tone }: { tone: string }) {
  return (
    <span className={`${styles.dot} ${tone}`}>
      <svg
        width="9"
        height="9"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M3.5 12h17M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </svg>
    </span>
  );
}

const TONES = [styles.dotAccent, styles.dotOrange, styles.dotGreen];

export default function ThinkingState({
  variant = "Steps",
  onSettled,
  settled = false,
  rows,
  active,
  done,
  icon,
}: {
  variant?: string;
  onSettled?: () => void;
  settled?: boolean;
  rows?: Row[];
  active?: string;
  done?: string;
  icon?: ReactNode;
}) {
  const liveStage = useSequence(settled ? NO_STEPS : STAGES);
  const stage = settled ? STAGES.length - 1 : liveStage;
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const base = VARIANTS[variant] ?? VARIANTS.Steps;
  const v = {
    ...base,
    rows: rows ?? base.rows,
    active: active ?? base.active,
    done: done ?? base.done,
  };
  const autoExpanded = !settled && stage >= 1 && stage < 4;
  const expanded = manualExpanded ?? autoExpanded;
  const working = !settled && stage < 3;
  const visible = stage < 1 ? 0 : v.rows.length;
  const traceRef = useRef<HTMLDivElement>(null);
  const [lineHeight, setLineHeight] = useState(0);
  useLayoutEffect(() => {
    if (traceRef.current) setLineHeight(traceRef.current.offsetHeight);
  }, [visible, expanded, variant, stage]);

  const settledRef = useRef(false);
  useEffect(() => {
    if (settled || working || settledRef.current) return;
    settledRef.current = true;
    onSettled?.();
  }, [working, onSettled, settled]);

  return (
    <div
      key={variant}
      className={styles.wrap}
      style={{
        minHeight: working || expanded ? 176 : undefined,
        transition: "min-height 400ms cubic-bezier(0.23,1,0.32,1)",
      }}
    >
      <button
        type="button"
        aria-expanded={expanded}
        className={styles.header}
        onClick={() =>
          setManualExpanded((current) => !(current ?? autoExpanded))
        }
      >
        {icon ? (
          <span
            className={styles.headerIcon}
            style={{ color: working ? "var(--text-dim)" : "var(--text-muted)" }}
          >
            {icon}
          </span>
        ) : (
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill={working ? "var(--text-dim)" : "var(--text-muted)"}
          >
            <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
          </svg>
        )}
        <span role="status" className={styles.statusGroup}>
          {working ? (
            <span className={styles.activeText} style={{ animation: "shimmer-text 1.4s linear infinite" }}>
              {v.active}
            </span>
          ) : (
            <span
              className={styles.doneText}
              style={{ animation: "fade-in 350ms ease-out both" }}
            >
              {v.done}
            </span>
          )}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--text-muted)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={styles.chevron}
          style={{
            transform: expanded ? "rotate(180deg)" : "rotate(0)",
          }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      <div
        className={styles.traceGrid}
        style={{
          gridTemplateRows: expanded ? "1fr" : "0fr",
          opacity: expanded ? 1 : 0,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      >
        <div className={styles.traceClip}>
          <div className={styles.traceInner}>
            <span
              aria-hidden
              className={styles.traceLine}
              style={{
                top: -8,
                height: lineHeight ? lineHeight - 2 : 0,
                transition:
                  "height 500ms cubic-bezier(0.23,1,0.32,1)",
              }}
            />
            <div ref={traceRef} className={styles.rows}>
              {v.query && (
                <div
                  className={styles.queryRow}
                  style={{
                    animation: expanded
                      ? "fade-up 300ms cubic-bezier(0.23,1,0.32,1) both"
                      : undefined,
                  }}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="var(--text-muted)"
                    strokeWidth="2"
                    strokeLinecap="round"
                    className={styles.queryIcon}
                  >
                    <circle cx="11" cy="11" r="7" />
                    <path d="M21 21l-4.3-4.3" />
                  </svg>
                  <span className={styles.queryText}>{v.query}</span>
                </div>
              )}
              {v.rows.slice(0, visible).map((row, i) => {
                const content = (
                  <>
                    {variant === "Search" || variant === "Social" ? (
                      row.logo ? (
                        <span
                          className={`${styles.social} ${
                            row.logo === "x" ? styles.socialLight : ""
                          }`}
                        >
                          <SocialIcon
                            name={row.logo}
                            size={row.logo === "x" ? 13 : 17}
                          />
                        </span>
                      ) : (
                        <Dot tone={TONES[i % 3]} />
                      )
                    ) : null}
                    {variant === "Steps" &&
                      (i < visible - 1 || !working ? (
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="var(--text-muted)"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className={styles.check}
                        >
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                      ) : (
                        <span
                          className={styles.spinner}
                          style={{ animation: "spin 700ms linear infinite" }}
                        />
                      ))}
                    <span
                      className={[
                        styles.rowPrimary,
                        variant === "Reasoning" ? styles.reasoning : "",
                        variant === "Search" || variant === "Social"
                          ? styles.searchLink
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {row.primary}
                    </span>
                    {row.secondary && (
                      <span
                        className={`${styles.rowSecondary} ${
                          row.mono ? styles.mono : ""
                        }`}
                      >
                        {row.secondary}
                      </span>
                    )}
                    {row.add !== undefined && (
                      <span className={styles.diff}>
                        <span className={styles.diffAdd}>+{row.add}</span>{" "}
                        <span className={styles.diffDel}>−{row.del}</span>
                      </span>
                    )}
                  </>
                );
                const animation = {
                  animation: `fade-up 320ms cubic-bezier(0.23,1,0.32,1) ${
                    i * 120
                  }ms both`,
                };

                if (variant === "Search" || variant === "Social") {
                  return (
                    <a
                      key={row.primary}
                      href={row.href}
                      target="_blank"
                      rel="noreferrer"
                      className={`${styles.row} ${styles.rowHover}`}
                      style={animation}
                    >
                      {content}
                    </a>
                  );
                }

                if (variant === "Coding") {
                  const selected = selectedTool === row.primary;
                  return (
                    <button
                      key={row.primary}
                      type="button"
                      aria-pressed={selected}
                      onClick={() =>
                        setSelectedTool(selected ? null : row.primary)
                      }
                      className={`${styles.row} ${
                        selected ? styles.rowSelected : styles.rowHover
                      }`}
                      style={animation}
                    >
                      {content}
                    </button>
                  );
                }

                return (
                  <div key={row.primary} className={styles.row} style={animation}>
                    {content}
                  </div>
                );
              })}
              {(variant === "Search" || variant === "Social") &&
                stage >= 3 && (
                  <span
                    className={styles.more}
                    style={{ animation: "fade-in 300ms ease-out both" }}
                  >
                    +7 more
                  </span>
                )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
