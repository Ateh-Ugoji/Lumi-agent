import { useState } from "react";
import styles from "./WinnersCard.module.css";

export type WinnerPeer = {
  handle: string;
  name?: string;
  avatarUrl?: string;
  role?: string;
  peerRole?: "direct_competitor" | "parallel_founder" | "aspirational_leader" | "co_builder" | string;
  gradingScore?: number;
  relevance?: {
    geo_alignment?: number;
    icp_overlap?: number;
  };
};

function formatPeerRole(role?: string): { label: string; kind: string } {
  if (!role) return { label: "Niche Leader", kind: "default" };
  const r = role.toLowerCase().replace(/[\s-]+/g, "_");
  if (r.includes("direct") || r === "direct_competitor") return { label: "Direct Competitor", kind: "direct" };
  if (r.includes("parallel") || r === "parallel_founder") return { label: "Parallel Founder", kind: "parallel" };
  if (r.includes("aspiration") || r === "aspirational_leader") return { label: "Aspirational Leader", kind: "leader" };
  if (r.includes("co_builder") || r.includes("cobuilder") || r === "collaborator") return { label: "Co-Builder", kind: "cobuilder" };
  return { label: role, kind: "default" };
}

export type WinnerFramework = {
  name: string;
  hook?: string;
  structure?: string;
  whyItWorks?: string;
  pillar?: string;
  prompt?: string;
};

export type WinnerPost = {
  author: string;
  caption: string;
  likes?: number;
  retweets?: number;
  url?: string;
};

export type WinnersData = {
  title?: string;
  niche?: string;
  peers?: WinnerPeer[];
  frameworks?: WinnerFramework[];
  posts?: WinnerPost[];
};

export default function WinnersCard({
  data,
  onPill,
}: {
  data?: WinnersData | null;
  onPill?: (text: string) => void;
}) {
  const peers = data?.peers || [];
  const frameworks = data?.frameworks || [];
  const posts = data?.posts || [];

  // Pick default tab based on available data
  const [tab, setTab] = useState<"frameworks" | "peers" | "posts">(() => {
    if (frameworks.length > 0) return "frameworks";
    if (peers.length > 0) return "peers";
    return "posts";
  });

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <div className={styles.iconBadge}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
          </div>
          <span className={styles.title}>{data?.title || "Winners in the Space"}</span>
        </div>
        <span className={styles.liveBadge}>PEER BENCHMARK</span>
      </div>

      <div className={styles.tabs}>
        {frameworks.length > 0 && (
          <button
            type="button"
            className={`${styles.tabBtn} ${tab === "frameworks" ? styles.tabBtnActive : ""}`}
            onClick={() => setTab("frameworks")}
          >
            Frameworks ({frameworks.length})
          </button>
        )}
        <button
          type="button"
          className={`${styles.tabBtn} ${tab === "peers" ? styles.tabBtnActive : ""}`}
          onClick={() => setTab("peers")}
        >
          Top Peers ({peers.length})
        </button>
        {posts.length > 0 && (
          <button
            type="button"
            className={`${styles.tabBtn} ${tab === "posts" ? styles.tabBtnActive : ""}`}
            onClick={() => setTab("posts")}
          >
            Viral Posts ({posts.length})
          </button>
        )}
      </div>

      <div className={styles.tabContent}>
        {tab === "frameworks" && frameworks.length > 0 && (
          <>
            {frameworks.slice(0, 3).map((fw, i) => (
              <div key={i} className={styles.frameworkCard}>
                <div className={styles.frameworkHeader}>
                  <span className={styles.frameworkName}>{fw.name}</span>
                  {fw.pillar && <span className={styles.pillarTag}>{fw.pillar}</span>}
                </div>
                {fw.structure && (
                  <div className={styles.structureBox}>
                    <strong>Format: </strong>
                    {fw.structure}
                  </div>
                )}
                {fw.hook && (
                  <div className={styles.hookBox}>
                    <strong>Hook: </strong>"{fw.hook}"
                  </div>
                )}
                {fw.whyItWorks && (
                  <div className={styles.driverText}>
                    <span>💡 {fw.whyItWorks}</span>
                  </div>
                )}
                {onPill && (
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.applyBtn}
                      onClick={() => onPill(`Draft a post using "${fw.name}" framework`)}
                    >
                      Use framework ↗
                    </button>
                  </div>
                )}
              </div>
            ))}
          </>
        )}

        {tab === "peers" && (
          peers.length > 0 ? (
            <div className={styles.peerGrid}>
              {peers.map((peer, i) => {
                const clean = peer.handle.replace(/^@/, "");
                const roleInfo = formatPeerRole(peer.peerRole || peer.role);
                return (
                  <a
                    key={i}
                    href={`https://x.com/${clean}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.peerCard}
                    title={`View @${clean} on X`}
                  >
                    <div className={styles.peerCardTop}>
                      <div className={styles.peerCardLeft}>
                        {peer.avatarUrl ? (
                          <img src={peer.avatarUrl} alt={clean} className={styles.avatarImg} />
                        ) : (
                          <div className={styles.avatar}>{clean.slice(0, 2).toUpperCase()}</div>
                        )}
                        <div className={styles.peerInfo}>
                          <span className={styles.peerHandle}>@{clean}</span>
                          {peer.name && <span className={styles.peerName}>{peer.name}</span>}
                        </div>
                      </div>
                      {peer.gradingScore !== undefined && (
                        <span className={styles.matchBadge}>{Math.round(peer.gradingScore)}% Match</span>
                      )}
                    </div>
                    <div className={styles.peerCardBottom}>
                      <span className={`${styles.rolePill} ${styles[`role_${roleInfo.kind}`] || styles.role_default}`}>
                        {roleInfo.label}
                      </span>
                      {peer.relevance?.geo_alignment && peer.relevance.geo_alignment >= 0.8 && (
                        <span className={styles.geoPill}>🇳🇬 NG</span>
                      )}
                    </div>
                  </a>
                );
              })}
            </div>
          ) : (
            <div style={{ padding: "16px", color: "#9ca3af", fontSize: "13px" }}>
              No peers discovered yet. Run a niche discovery scan to populate your real competitor benchmarks.
            </div>
          )
        )}

        {tab === "posts" && posts.length > 0 && (
          <>
            {posts.slice(0, 3).map((p, i) => (
              <div key={i} className={styles.postCard}>
                <div className={styles.postHeader}>
                  <span className={styles.postAuthor}>@{p.author.replace(/^@/, "")}</span>
                  <div className={styles.metrics}>
                    {p.likes !== undefined && (
                      <span className={styles.metricItem}>❤️ {p.likes.toLocaleString()}</span>
                    )}
                    {p.retweets !== undefined && (
                      <span className={styles.metricItem}>🔁 {p.retweets.toLocaleString()}</span>
                    )}
                  </div>
                </div>
                <div className={styles.postText}>{p.caption}</div>
                {p.url && (
                  <a href={p.url} target="_blank" rel="noopener noreferrer" className={styles.postLink}>
                    View on X ↗
                  </a>
                )}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
