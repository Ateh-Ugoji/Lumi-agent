import { useEffect, useState, useRef } from "react";
import { getJob, type BackgroundJobStatus } from "../../api/jobs.ts";
import styles from "./AccountUnderstandingModal.module.css";

export type DiscoveredPeer = {
  handle: string;
  name?: string;
  avatar_url?: string;
  peer_role?: string;
  score?: number;
};

export type DiscoveredFramework = {
  name: string;
  title: string;
  structure?: string | string[];
  hook_formula?: string;
  lift?: number;
};

const DEFAULT_PEERS: DiscoveredPeer[] = [
  {
    handle: "timmyisagod",
    name: "Timmy",
    avatar_url: "https://unavatar.io/x/timmyisagod",
    peer_role: "Direct Competitor",
    score: 0.95,
  },
  {
    handle: "honour_can_code",
    name: "Honour",
    avatar_url: "https://unavatar.io/x/honour_can_code",
    peer_role: "Parallel Founder",
    score: 0.88,
  },
  {
    handle: "mishaelishola_",
    name: "Mishael",
    avatar_url: "https://unavatar.io/x/mishaelishola_",
    peer_role: "Parallel Founder",
    score: 0.86,
  },
  {
    handle: "ahiakwo_john",
    name: "John Ahiakwo",
    avatar_url: "https://unavatar.io/x/ahiakwo_john",
    peer_role: "Co-Builder",
    score: 0.84,
  },
  {
    handle: "thedanieloreofe",
    name: "Daniel",
    avatar_url: "https://unavatar.io/x/thedanieloreofe",
    peer_role: "Parallel Founder",
    score: 0.82,
  },
];

const DEFAULT_FRAMEWORKS: DiscoveredFramework[] = [
  {
    name: "raw-motion-vulnerability",
    title: "The Raw Motion Vulnerability Hook",
    hook_formula: "I just see person wey get motion pass me now now... Back to work then. E no pain me!",
    lift: 2.3,
  },
  {
    name: "ecosystem-conference-alignment",
    title: "The Tech Ecosystem Gathering Hook",
    hook_formula: "Moonshot this year was great! Shout-out to the tech ecosystem builders.",
    lift: 2.1,
  },
  {
    name: "client-to-product-pivot",
    title: "The Client Work to SaaS Founder Transition",
    hook_formula: "Spent months on client work. Barely touched X. Now we are shipping weekly.",
    lift: 1.9,
  },
  {
    name: "co-builder-accountability-pact",
    title: "The Co-Builder Public Commitment Pact",
    hook_formula: "@[Partner] and I are putting it out here to hold us accountable: shipping every week.",
    lift: 1.7,
  },
];

export default function AccountUnderstandingModal({
  isOpen,
  account,
  jobId,
  onComplete,
}: {
  isOpen: boolean;
  account: { handle: string | null; name?: string | null; avatar_url?: string | null; platform?: string } | null;
  jobId?: string | null;
  onComplete: () => void;
}) {
  const [stage, setStage] = useState<number>(1);
  const [creatorAvatarError, setCreatorAvatarError] = useState(false);
  const [peers, setPeers] = useState<DiscoveredPeer[]>(DEFAULT_PEERS);
  const [frameworks, setFrameworks] = useState<DiscoveredFramework[]>(DEFAULT_FRAMEWORKS);
  const [peerAvatarErrors, setPeerAvatarErrors] = useState<Record<string, boolean>>({});
  const completedRef = useRef(false);

  // Poll background job if available
  useEffect(() => {
    if (!isOpen || !jobId) return;
    let timer: any = null;
    let active = true;

    const check = async () => {
      try {
        const job: BackgroundJobStatus = await getJob(jobId);
        if (!active) return;
        if (job.result) {
          if (Array.isArray(job.result.competitor_details) && job.result.competitor_details.length > 0) {
            setPeers(
              job.result.competitor_details.map((c: any, i: number) => ({
                handle: c.handle,
                name: c.display_name || c.handle,
                avatar_url: c.avatar_url || `https://unavatar.io/x/${c.handle}`,
                peer_role: i === 0 ? "Direct Competitor" : i < 4 ? "Parallel Founder" : "Co-Builder",
                score: i === 0 ? 0.95 : 0.85,
              }))
            );
          }
          if (Array.isArray(job.result.frameworks) && job.result.frameworks.length > 0) {
            setFrameworks(job.result.frameworks);
          }
        }
        if (job.status === "succeeded") {
          // Job complete
          return;
        }
      } catch {
        // graceful ignore
      }
      if (active) {
        timer = setTimeout(check, 1000);
      }
    };

    void check();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [isOpen, jobId]);

  // Orchestrate stage sequence progression (minimum 1.7s per stage for visual delight)
  useEffect(() => {
    if (!isOpen) {
      setStage(1);
      completedRef.current = false;
      return;
    }

    const t1 = setTimeout(() => setStage(2), 2200);
    const t2 = setTimeout(() => setStage(3), 4600);
    const t3 = setTimeout(() => setStage(4), 7000);
    const t4 = setTimeout(() => setStage(5), 9400);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
    };
  }, [isOpen]);

  if (!isOpen || !account) return null;

  const cleanHandle = (account.handle || "").replace(/^@/, "");
  const creatorAvatar =
    account.avatar_url || (cleanHandle ? `https://unavatar.io/x/${cleanHandle}` : "");
  const creatorInitial = (account.name || cleanHandle || "L").charAt(0).toUpperCase();

  const handleFinish = () => {
    if (completedRef.current) return;
    completedRef.current = true;
    onComplete();
  };

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modalCard}>
        <div className={styles.ambientGlow} />

        {/* Top Progress & Stepper */}
        <div className={styles.headerProgress}>
          <div className={styles.stageStepper}>
            {[1, 2, 3, 4, 5].map((s) => {
              const isActive = stage === s;
              const isDone = stage > s;
              return (
                <div
                  key={s}
                  className={`${styles.stepDot} ${
                    isActive ? styles.stepDotActive : isDone ? styles.stepDotDone : ""
                  }`}
                >
                  {isDone ? "✓" : s}
                </div>
              );
            })}
          </div>
          <div className={styles.progressBarTrack}>
            <div
              className={styles.progressBarFill}
              style={{ width: `${((stage - 1) / 4) * 100}%` }}
            />
          </div>
        </div>

        {/* Stage 1: Lumi is understanding your social media account */}
        {stage === 1 && (
          <div className={styles.contentStage}>
            <div className={styles.avatarPulseContainer}>
              <div className={styles.pulseRing} />
              <div className={styles.pulseRingOuter} />
              {creatorAvatar && !creatorAvatarError ? (
                <img
                  src={creatorAvatar}
                  alt={cleanHandle}
                  className={styles.creatorAvatarImg}
                  onError={() => setCreatorAvatarError(true)}
                />
              ) : (
                <div className={styles.creatorFallback}>{creatorInitial}</div>
              )}
            </div>
            <div className={styles.accountPill}>
              <span className={styles.platformIcon}>𝕏</span>
              <span>@{cleanHandle}</span>
            </div>
            <h2 className={styles.stageTitle}>Lumi is understanding your social media account</h2>
            <p className={styles.stageSubtitle}>
              Ingesting creator profile, post cadence, linguistic rhythms, and audience engagement
              signals...
            </p>
          </div>
        )}

        {/* Stage 2: Finding your competitors */}
        {stage === 2 && (
          <div className={styles.contentStage}>
            <div className={styles.avatarPulseContainer}>
              <div className={styles.pulseRing} />
              {creatorAvatar && !creatorAvatarError ? (
                <img
                  src={creatorAvatar}
                  alt={cleanHandle}
                  className={styles.creatorAvatarImg}
                  onError={() => setCreatorAvatarError(true)}
                />
              ) : (
                <div className={styles.creatorFallback}>{creatorInitial}</div>
              )}
            </div>
            <h2 className={styles.stageTitle}>Finding your competitors</h2>
            <p className={styles.stageSubtitle}>
              Scanning peer founders and creators in your geographic and demographic ecosystem...
            </p>
            <div className={styles.competitorsGrid}>
              {peers.map((p, idx) => {
                const pfp =
                  p.avatar_url || `https://unavatar.io/x/${p.handle}`;
                const failed = peerAvatarErrors[p.handle];
                return (
                  <div
                    key={p.handle}
                    className={styles.competitorChip}
                    style={{ animationDelay: `${idx * 0.12}s` }}
                  >
                    {!failed ? (
                      <img
                        src={pfp}
                        alt={p.handle}
                        className={styles.peerAvatarImg}
                        onError={() =>
                          setPeerAvatarErrors((prev) => ({ ...prev, [p.handle]: true }))
                        }
                      />
                    ) : (
                      <div className={styles.peerFallback}>
                        {p.handle.slice(0, 1).toUpperCase()}
                      </div>
                    )}
                    <span className={styles.peerHandle}>@{p.handle}</span>
                    <span className={styles.peerBadge}>{p.peer_role || "Peer"}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Stage 3: Understanding their winning frameworks */}
        {stage === 3 && (
          <div className={styles.contentStage}>
            <h2 className={styles.stageTitle}>Understanding their winning frameworks</h2>
            <p className={styles.stageSubtitle}>
              Deconstructing high-performing hook structures, tension arcs, and outsized reach
              mechanics across peer accounts...
            </p>
            <div className={styles.frameworksContainer}>
              {frameworks.map((fw, idx) => (
                <div
                  key={fw.name}
                  className={styles.frameworkCard}
                  style={{ animationDelay: `${idx * 0.14}s` }}
                >
                  <div>
                    <div className={styles.frameworkTitle}>⚡ {fw.title}</div>
                    {fw.hook_formula && (
                      <div className={styles.frameworkFormula}>"{fw.hook_formula}"</div>
                    )}
                  </div>
                  {fw.lift && (
                    <span className={styles.liftBadge}>+{fw.lift}x Lift</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Stage 4: Stealing the winning frameworks */}
        {stage === 4 && (
          <div className={styles.contentStage}>
            <div className={styles.stealingOrbit}>
              <div className={styles.pulseRing} />
              <div className={styles.pulseRingOuter} />
              {creatorAvatar && !creatorAvatarError ? (
                <img
                  src={creatorAvatar}
                  alt={cleanHandle}
                  className={styles.creatorAvatarImg}
                  onError={() => setCreatorAvatarError(true)}
                />
              ) : (
                <div className={styles.creatorFallback}>{creatorInitial}</div>
              )}
              {peers.slice(0, 3).map((p, idx) => {
                const pfp =
                  p.avatar_url || `https://unavatar.io/x/${p.handle}`;
                return (
                  <div
                    key={p.handle}
                    className={styles.orbitParticle}
                    style={{ animationDelay: `${idx * 1.3}s` }}
                  >
                    <img
                      src={pfp}
                      alt={p.handle}
                      className={styles.peerAvatarImg}
                      style={{ border: "2px solid #38bdf8" }}
                    />
                  </div>
                );
              })}
            </div>
            <h2 className={styles.stageTitle}>Stealing the winning frameworks</h2>
            <p className={styles.stageSubtitle}>
              Synthesizing proven competitor hooks, engagement loops, and viral patterns into your
              personal voice engine...
            </p>
            <div style={{ display: "flex", gap: "8px" }}>
              <span className={styles.liftBadge}>+2.3x Engagement Multiplier</span>
              <span className={styles.liftBadge}>4 Blueprints Acquired</span>
            </div>
          </div>
        )}

        {/* Stage 5: Done */}
        {stage === 5 && (
          <div className={styles.contentStage}>
            <div className={styles.doneCheckRing}>
              <span className={styles.doneIcon}>✓</span>
            </div>
            <h2 className={styles.stageTitle}>Done!</h2>
            <p className={styles.stageSubtitle}>
              Your creator profile, competitor intelligence, and winning frameworks are fully
              primed and ready.
            </p>
            <div className={styles.summaryBadges}>
              <span className={styles.summaryPill}>
                👥 {peers.length} Ecosystem Peers Tracked
              </span>
              <span className={styles.summaryPill}>
                ⚡ {frameworks.length} Winning Frameworks Ready
              </span>
            </div>
            <button
              type="button"
              className={styles.enterBtn}
              onClick={handleFinish}
            >
              Enter Lumi Studio →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
