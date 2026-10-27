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
import styles from "./AgentThinking.module.css";

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

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

function StepRow({
  step,
  active,
  showCheck,
  order,
  animate,
}: {
  step: SimStep;
  active: boolean;
  showCheck: boolean;
  order: number;
  animate: boolean;
}) {
  return (
    <div
      data-step={step.id}
      data-state={active ? "active" : "done"}
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
        <span
          className={styles.spinner}
          style={{ animation: "spin 700ms linear infinite" }}
        />
      )}
      <span className={styles.rowBody}>
        <span className={styles.rowLine}>
          <span
            className={active ? styles.rowActiveText : styles.rowPrimary}
          >
            {step.label}
          </span>
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
  const activeIndex = final
    ? -1
    : Math.max(0, Math.min(index, count - 1));
  const steps = script.steps.slice(0, count);
  const activeStep = final ? undefined : script.steps[activeIndex];
  const label = final
    ? `Thought for ${formatDuration(elapsedMs)}`
    : (activeStep ?? script.steps[0]).label;

  const panelId = useId();
  const rowsRef = useRef<HTMLDivElement>(null);
  const [lineHeight, setLineHeight] = useState(0);
  useLayoutEffect(() => {
    if (rowsRef.current) setLineHeight(rowsRef.current.offsetHeight);
  }, [count, expanded, final]);

  const toggle = () => setManual(!expanded);

  let headerIcon: ReactNode;
  if (final) {
    headerIcon = <Sparkle />;
  } else if (activeStep?.kind === "social") {
    headerIcon = (
      <SocialIconCycler
        platforms={activeStep.platforms ?? []}
        reduced={reduced}
      />
    );
  } else if (activeStep?.kind === "action") {
    headerIcon = (
      <span
        className={styles.spinner}
        style={{ animation: reduced ? undefined : "spin 700ms linear infinite" }}
      />
    );
  } else {
    headerIcon = <Sparkle />;
  }

  return (
    <div
      data-agent-thinking
      data-state={final ? "settled" : "running"}
      className={`${styles.wrap} ${settled ? styles.static : ""}`}
      style={{
        minHeight: expanded ? 176 : undefined,
        transition: "min-height 400ms cubic-bezier(0.23,1,0.32,1)",
      }}
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        className={styles.header}
        onClick={toggle}
      >
        <span className={styles.headerIcon} aria-hidden="true">
          {headerIcon}
        </span>
        <span className={styles.statusGroup} role="status" aria-live="polite">
          {final ? (
            <span className={styles.doneText}>{label}</span>
          ) : (
            <span
              key={activeStep?.id ?? "start"}
              className={`${styles.activeText} ${
                reduced ? styles.noMotion : ""
              }`}
            >
              {label}
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
          aria-hidden="true"
          style={{
            transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
          }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

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
                  showCheck={final || i < activeIndex}
                  order={i}
                  animate={!settled && !reduced}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
