import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import SocialIcon from "../ThinkingState/SocialIcons";
import { formatDuration } from "../../simulation/formatDuration";
import type { SimScript, SimStep } from "../../simulation/simScripts";
import WorkingMark from "./WorkingMark";
import usePrefersReducedMotion from "./usePrefersReducedMotion";
import { formatClock } from "./formatClock";
import styles from "./AgentThinking.module.css";

const GLIDE_MS = 320;

function shuffle<T>(input: readonly T[]): T[] {
  const arr = [...input];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function SocialIconCycler({
  platforms,
  reduced,
}: {
  platforms: string[];
  reduced: boolean;
}) {
  const key = platforms.join(",");
  const order = useMemo(
    () => shuffle(key ? key.split(",") : []),
    [key],
  );
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (reduced || order.length < 2) return;
    const period = 700 + Math.floor(Math.random() * 200);
    const timer = window.setInterval(
      () => setIdx((i) => (i + 1) % order.length),
      period,
    );
    return () => window.clearInterval(timer);
  }, [order, reduced]);

  const name = order.length ? order[idx % order.length] : null;
  if (!name) return null;
  return (
    <span
      key={name}
      data-icon={name}
      className={`${styles.iconSocial} ${
        name === "x" ? styles.iconSocialLight : ""
      }`}
    >
      <SocialIcon name={name} size={name === "x" ? 13 : 17} />
    </span>
  );
}

/** The account's face in the header — crossfades in where the orb/logo was.
 * Falls back to the sparkle if the picture 404s, never a broken image. */
function AvatarIcon({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <Sparkle />;
  return (
    <img
      className={styles.iconAvatar}
      src={src}
      alt=""
      onError={() => setFailed(true)}
    />
  );
}

/** Small round author picture on a discovered-post card (letter if unknown). */
function PostAvatar({ author, url }: { author?: string; url?: string }) {
  const [failed, setFailed] = useState(false);
  const src = url || (author ? `https://unavatar.io/x/${author}` : "");
  if (!src || failed) {
    return <span className={styles.postAvatarLetter}>{(author || "?").slice(0, 1).toUpperCase()}</span>;
  }
  return (
    <img
      className={styles.postAvatar}
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function Sparkle() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
    </svg>
  );
}

function Check() {
  return (
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
      aria-hidden="true"
    >
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

/**
 * Shimmer label — Claude's ShimmerText logic: the text keeps a readable base
 * colour, and a second, stacked copy (aria-hidden + inert) carries the
 * travelling highlight on top. The glyphs are never painted with the gradient
 * itself, so resting contrast stays normal body-text contrast.
 */
function ShimmerLabel({
  text,
  small = false,
}: {
  text: string;
  small?: boolean;
}) {
  const size = small ? ` ${styles.shimmerSm}` : "";
  return (
    <span className={styles.shimmer}>
      <span className={`${styles.shimmerLayer}${size} ${styles.shimmerBase}`}>
        {text}
      </span>
      <span
        aria-hidden="true"
        inert
        // Inline on purpose: CSS modules scope `animation` names inside
        // *.module.css, so a module rule pointing at the GLOBAL
        // @keyframes shimmer-text resolves to a scoped name that exists
        // nowhere and the sweep freezes. (Same pattern as ThinkingState.)
        style={{ animation: "shimmer-text 1.6s linear infinite" }}
        className={`${styles.shimmerLayer}${size} ${styles.shimmerSweep}`}
      >
        {text}
      </span>
    </span>
  );
}

/** Keeps the previous value mounted for `holdMs` so it can glide out. */
function useStaggered<T>(value: T, holdMs: number, enabled: boolean) {
  const [previous, setPrevious] = useState<T | null>(null);
  const [gliding, setGliding] = useState(false);
  const lastRef = useRef(value);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!enabled) {
      setPrevious(null);
      setGliding(false);
      return;
    }
    if (lastRef.current === value) return;
    const old = lastRef.current;
    lastRef.current = value;
    setPrevious(old);
    setGliding(true);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      setGliding(false);
      setPrevious(null);
    }, holdMs);
    return () => window.clearTimeout(timerRef.current);
  }, [value, holdMs, enabled]);

  return { previous, gliding };
}

/**
 * Morph label — Claude's `data-morph-key` grid stack: old and new label share
 * ONE grid cell while the change glides, and the container's width eases from
 * the old label's width to the new one instead of snapping.
 */
function MorphLabel({
  label,
  small = false,
  enabled = true,
}: {
  label: string;
  small?: boolean;
  enabled?: boolean;
}) {
  const { previous, gliding } = useStaggered(label, GLIDE_MS, enabled);
  const stackRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const el = stackRef.current;
    if (!el) return;
    if (!gliding || el.children.length < 2) {
      if (el.style.width) {
        el.style.transition = "none";
        el.style.width = "";
      }
      return;
    }
    const outgoing = el.children[0] as HTMLElement;
    const incoming = el.children[1] as HTMLElement;
    const wOld = outgoing.getBoundingClientRect().width;
    const wNew = incoming.getBoundingClientRect().width;
    if (!(wOld > 0) || !(wNew > 0) || Math.abs(wOld - wNew) < 0.5) return;
    el.style.transition = "none";
    el.style.width = `${wOld}px`;
    void el.offsetWidth; // reflow: paint the old width before easing
    el.style.transition = `width ${GLIDE_MS}ms cubic-bezier(0.23, 1, 0.32, 1)`;
    el.style.width = `${wNew}px`;
  }, [gliding, label]);

  return (
    <span
      ref={stackRef}
      className={styles.labelStack}
      data-glide={gliding ? "on" : undefined}
    >
      {previous !== null && (
        <span
          key={`out-${previous}`}
          className={`${styles.labelCell} ${styles.labelOut}`}
          aria-hidden="true"
        >
          <ShimmerLabel text={previous} small={small} />
        </span>
      )}
      <span
        key={`in-${label}`}
        className={`${styles.labelCell} ${gliding ? styles.labelIn : ""}`}
      >
        <ShimmerLabel text={label} small={small} />
      </span>
    </span>
  );
}

/** Platform names ``SocialIcon`` can actually draw — an unknown name would
 *  render an empty chip, so rows filter against this set first. */
const ROW_LOGO_PLATFORMS = new Set([
  "x",
  "facebook",
  "instagram",
  "linkedin",
  "tiktok",
  "youtube",
]);

/** The logo chips that lead a row: steps that search a social network show that
 *  network's mark (old Lumi c466c5d behaviour). Action/writing rows stay clean. */
function rowLogos(step: SimStep): string[] {
  if (step.kind !== "social" && step.kind !== "analysis") return [];
  return (step.platforms ?? [])
    .filter((name) => ROW_LOGO_PLATFORMS.has(name))
    .slice(0, 3);
}

function StepRow({
  step,
  active,
  showCheck,
  order,
  animate,
  reduced,
}: {
  step: SimStep;
  active: boolean;
  showCheck: boolean;
  order: number;
  animate: boolean;
  reduced: boolean;
}) {
  return (
    <div
      data-step={step.id}
      data-state={active ? "active" : showCheck ? "done" : "pending"}
      className={`${styles.row} ${active ? styles.rowActive : ""}`}
      style={
        animate
          ? { animation: `fade-up 320ms cubic-bezier(0.23,1,0.32,1) ${order * 120}ms both` }
          : undefined
      }
    >
      {showCheck ? (
        <Check />
      ) : (
        <WorkingMark size={16} variant="busy" className={styles.rowMark} />
      )}
      <span className={styles.rowBody}>
        <span className={styles.rowLine}>
          {rowLogos(step).map((name) => (
            <span
              key={name}
              // Decorative — the row's label already names what is happening.
              aria-hidden="true"
              className={`${styles.iconSocial} ${
                name === "x" ? styles.iconSocialLight : ""
              }`}
            >
              <SocialIcon name={name} size={name === "x" ? 13 : 17} />
            </span>
          ))}
          {active ? (
            <MorphLabel label={step.label} small enabled={!reduced} />
          ) : (
            <span className={styles.rowPrimary}>{step.label}</span>
          )}
          {step.meta && <span className={styles.meta}>{step.meta}</span>}
        </span>
        {step.detail && <span className={styles.detail}>{step.detail}</span>}
        {step.samplePosts && step.samplePosts.length > 0 && (
          <div className={styles.samplePostsGrid}>
            {step.samplePosts.slice(0, 4).map((p, pIdx) => (
              <a
                key={pIdx}
                href={p.url || "#"}
                target="_blank"
                rel="noreferrer"
                className={styles.postCard}
              >
                <div className={styles.postAuthorRow}>
                  <PostAvatar author={p.author} url={p.avatar_url} />
                  <span>{p.author ? `@${p.author}` : "Leader post"}</span>
                  {p.likes !== undefined && (
                    <span className={styles.postLikes}>
                      ❤️ {typeof p.likes === "number" ? p.likes.toLocaleString() : p.likes}
                    </span>
                  )}
                </div>
                <p className={styles.postText}>{p.text}</p>
              </a>
            ))}
          </div>
        )}
      </span>
    </div>
  );
}

/** Header icon keyed by identity so the crossfade knows what is swapping. */
function iconNode(key: string, reduced: boolean): ReactNode {
  if (key === "spark") return <Sparkle />;
  if (key.startsWith("avatar:")) return <AvatarIcon src={key.slice("avatar:".length)} />;
  if (key === "busy" || key === "calm")
    return <WorkingMark size={20} variant={key} />;
  if (key.startsWith("social:"))
    return (
      <SocialIconCycler
        platforms={key.slice("social:".length).split(",").filter(Boolean)}
        reduced={reduced}
      />
    );
  return <Sparkle />;
}

export type AgentThinkingProps = {
  script: SimScript;
  status?: "running" | "done";
  elapsedMs?: number;
  index?: number;
  startedCount?: number;
  settled?: boolean;
};

export default function AgentThinking({
  script,
  status = "running",
  elapsedMs = 0,
  index = 0,
  startedCount = 1,
  settled = false,
}: AgentThinkingProps) {
  const reduced = usePrefersReducedMotion();
  const [manual, setManual] = useState<boolean | null>(null);
  const final = settled || status === "done";
  const isShort = script.steps.length <= 4;
  const expanded = manual ?? (!final || isShort);

  const count = final
    ? script.steps.length
    : Math.max(1, Math.min(startedCount, script.steps.length));
  // `index` = first step that has NOT completed yet; -1 = everything started
  // has finished (model is reasoning between turns) → nothing spins.
  const activeIndex = final
    ? -1
    : index < 0
      ? -1
      : Math.min(index, count - 1);
  const steps = script.steps.slice(0, count);
  const activeStep = activeIndex >= 0 ? script.steps[activeIndex] : undefined;
  const runningLabel = activeStep ? activeStep.label : "Thinking…";
  const label = final
    ? `Thought for ${formatDuration(elapsedMs)}`
    : runningLabel;

  const panelId = useId();
  const labelId = useId();
  const stateId = useId();
  const rowsRef = useRef<HTMLDivElement>(null);
  const [lineHeight, setLineHeight] = useState(0);
  useLayoutEffect(() => {
    if (rowsRef.current) setLineHeight(rowsRef.current.offsetHeight);
  }, [count, expanded, final]);

  const toggle = () => setManual(!expanded);

  // Header icon identity: swapped pieces crossfade (150ms delay / 200ms fade).
  const iconKey = final
    ? "spark"
    : activeStep?.avatar_url
      ? `avatar:${activeStep.avatar_url}`
      : activeStep?.kind === "social"
        ? `social:${(activeStep.platforms ?? ["x"]).join(",")}`
        : activeStep?.kind === "action"
          ? "busy"
          : "calm";
  const { previous: prevIconKey, gliding: iconGlide } = useStaggered(
    iconKey,
    GLIDE_MS + 40,
    !reduced,
  );

  return (
    <div
      data-agent-thinking
      data-state={final ? "settled" : "running"}
      data-closed={expanded ? undefined : ""}
      className={styles.wrap}
      style={{
        minHeight: expanded ? 176 : undefined,
        transition: "min-height 400ms cubic-bezier(0.23,1,0.32,1)",
      }}
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        aria-labelledby={`${labelId} ${stateId}`}
        className={styles.header}
        onClick={toggle}
      >
        <span className={`${styles.headerIcon} ${styles.iconStack}`} aria-hidden="true">
          {prevIconKey !== null && (
            <span
              key={`out-${prevIconKey}`}
              className={`${styles.iconCell} ${styles.iconOut}`}
            >
              {iconNode(prevIconKey, reduced)}
            </span>
          )}
          <span
            key={`in-${iconKey}`}
            className={`${styles.iconCell} ${iconGlide ? styles.iconIn : ""}`}
          >
            {iconNode(iconKey, reduced)}
          </span>
        </span>

        {final ? (
          <span
            id={labelId}
            className={styles.doneText}
            // Inline like the sweep: module scoping would break the global
            // `fade-in` keyframes reference. Settled messages don't replay.
            style={{
              animation: settled
                ? "none"
                : "fade-in 350ms ease-out both",
            }}
          >
            {label}
          </span>
        ) : (
          <MorphLabel label={runningLabel} enabled={!reduced} />
        )}
        {/* Clock joins late like the reference's (no "0s" at t=0). */}
        {!final && elapsedMs >= 5000 && (
          <span className={styles.clock}>{formatClock(elapsedMs)}</span>
        )}
        <span id={stateId} className={styles.srOnly}>
          {final ? "done" : "running"}
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
          aria-hidden="true"
          style={{
            transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
          }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      <span className={styles.srOnly} role="status" aria-live="polite">
        {label}
      </span>

      <div
        id={panelId}
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
              aria-hidden="true"
              className={styles.traceLine}
              style={{
                top: -8,
                height: lineHeight ? lineHeight - 2 : 0,
                transition: "height 500ms cubic-bezier(0.23,1,0.32,1)",
              }}
            />
            <div ref={rowsRef} className={styles.rows}>
              {steps.map((step, i) => (
                <StepRow
                  key={step.id}
                  step={step}
                  active={!final && i === activeIndex}
                  showCheck={
                    final || i < activeIndex || step.detail === "Completed"
                  }
                  order={i}
                  animate={!settled && !reduced}
                  reduced={reduced}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
