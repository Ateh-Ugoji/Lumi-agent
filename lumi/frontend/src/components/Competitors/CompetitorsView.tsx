import { useEffect, useState } from "react";
import {
  getCompetitorOverview,
  type CompetitorFramework,
  type CompetitorItem,
  type CompetitorOverviewResponse,
  type CompetitorPost,
} from "../../api";
import styles from "./CompetitorsView.module.css";

interface CompetitorsViewProps {
  profileId?: number | null;
  onUseFramework?: (framework: CompetitorFramework, competitor: CompetitorItem) => void;
  onRepurposePost?: (caption: string, author: string) => void;
  onBack?: () => void;
}

function formatCount(num?: number | null): string {
  if (num === null || num === undefined) return "0";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return num.toString();
}

export default function CompetitorsView({
  profileId,
  onUseFramework,
  onRepurposePost,
  onBack,
}: CompetitorsViewProps) {
  const [data, setData] = useState<CompetitorOverviewResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedCompetitors, setExpandedCompetitors] = useState<Record<string, boolean>>({});
  const [copiedHookId, setCopiedHookId] = useState<number | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getCompetitorOverview(profileId);
      setData(res);
      // By default expand the framework dropdown for all competitors that have frameworks
      const initialExpanded: Record<string, boolean> = {};
      res.competitors.forEach((c) => {
        initialExpanded[c.handle] = true;
      });
      setExpandedCompetitors(initialExpanded);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load competitor intelligence.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchData();
  }, [profileId]);

  const toggleAccordion = (handle: string) => {
    setExpandedCompetitors((prev) => ({
      ...prev,
      [handle]: !prev[handle],
    }));
  };

  const copyHookFormula = (id: number, hook: string) => {
    void navigator.clipboard.writeText(hook);
    setCopiedHookId(id);
    setTimeout(() => {
      setCopiedHookId((current) => (current === id ? null : current));
    }, 2000);
  };

  const filteredCompetitors = (data?.competitors ?? []).filter((c) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      c.handle.toLowerCase().includes(q) ||
      c.display_name.toLowerCase().includes(q) ||
      (c.role && c.role.toLowerCase().includes(q))
    );
  });

  return (
    <div className={styles.root}>
      <div className={styles.wrap}>
        {/* Top Header */}
        <div className={styles.header}>
          <div className={styles.titleRow}>
            <div className={styles.nicheBadge}>
              <span className={styles.pulseDot} />
              <span>{data?.niche ? `${data.niche} Niche` : "Competitor Reverse Engineering"}</span>
            </div>
            <h1 className={styles.title}>Competitor Intelligence</h1>
            <p className={styles.subtitle}>
              Reverse-engineer the winning formulas in your niche. Inspect their X TweepCred health,
              expand their high-converting frameworks, and repurpose their best-performing posts.
            </p>
          </div>

          <div className={styles.headerActions}>
            <button
              type="button"
              className={styles.refreshBtn}
              onClick={() => void fetchData()}
              disabled={loading}
              title="Refresh competitor intelligence"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" />
              </svg>
              <span>{loading ? "Analyzing..." : "Refresh"}</span>
            </button>
          </div>
        </div>

        {/* Search bar & summary */}
        {!loading && data && data.competitors.length > 0 && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
            <input
              type="text"
              placeholder="Search competitors by handle or name..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                flex: 1,
                maxWidth: 380,
                padding: "8px 14px",
                fontSize: 13,
                borderRadius: 20,
                background: "#16181c",
                border: "1px solid #2f3336",
                color: "#e7e9ea",
                outline: "none",
              }}
            />
            <div style={{ fontSize: 13, color: "#71767b" }}>
              Tracking <strong style={{ color: "#e7e9ea" }}>{data.competitors_count}</strong> key accounts in {data.niche}
            </div>
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className={styles.loadingBox}>
            <div className={styles.loadingSpinner} />
            <div style={{ fontWeight: 600, color: "#e7e9ea" }}>
              Auditing niche competitors & reverse-engineering frameworks...
            </div>
            <div style={{ fontSize: 13 }}>
              Calculating TweepCred PageRank scores, Heavy Ranker probabilities, and viral hooks.
            </div>
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className={styles.emptyBox}>
            <div style={{ color: "#f4212e", fontWeight: 700 }}>Unable to load competitors</div>
            <div style={{ fontSize: 13 }}>{error}</div>
            <button
              type="button"
              className={styles.refreshBtn}
              onClick={() => void fetchData()}
              style={{ marginTop: 8 }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && filteredCompetitors.length === 0 && (
          <div className={styles.emptyBox}>
            <div style={{ fontWeight: 700, color: "#e7e9ea", fontSize: 16 }}>No competitors found</div>
            <div style={{ fontSize: 13, maxWidth: 440 }}>
              {searchQuery
                ? `No accounts matching "${searchQuery}". Try clearing your search.`
                : "Connect your social accounts in Settings or chat with Lumi to discover niche peers and track their winning frameworks."}
            </div>
            {onBack && (
              <button
                type="button"
                className={styles.refreshBtn}
                onClick={onBack}
                style={{ marginTop: 8 }}
              >
                Go to Chat
              </button>
            )}
          </div>
        )}

        {/* Competitor Cards */}
        {!loading && !error && filteredCompetitors.length > 0 && (
          <div className={styles.competitorsGrid}>
            {filteredCompetitors.map((comp) => {
              const isExpanded = expandedCompetitors[comp.handle] ?? false;
              const hasFrameworks = comp.frameworks && comp.frameworks.length > 0;
              const hasPosts = comp.best_posts && comp.best_posts.length > 0;
              const tweepcred = comp.tweepcred;

              return (
                <div key={comp.handle} className={styles.competitorCard}>
                  {/* Top Profile Header */}
                  <div className={styles.profileRow}>
                    <div className={styles.profileInfo}>
                      {comp.avatar_url ? (
                        <img
                          src={comp.avatar_url}
                          alt={comp.display_name}
                          className={styles.avatar}
                          onError={(e) => {
                            (e.currentTarget as HTMLElement).style.display = "none";
                          }}
                        />
                      ) : (
                        <div className={styles.avatarFallback}>
                          {comp.display_name.slice(0, 1).toUpperCase()}
                        </div>
                      )}

                      <div className={styles.namesCol}>
                        <div className={styles.displayName}>
                          <span>{comp.display_name}</span>
                          <span className={styles.platformPill}>
                            {comp.platform === "x" ? "X / Twitter" : comp.platform}
                          </span>
                        </div>
                        <div className={styles.handleText}>
                          @{comp.handle}
                          {comp.follower_count ? ` • ${formatCount(comp.follower_count)} followers` : ""}
                        </div>
                      </div>
                    </div>

                    <div className={styles.profileMeta}>
                      {/* TweepCred Health Indicator */}
                      {tweepcred && (
                        <div
                          className={`${styles.tweepcredBadge} ${
                            tweepcred.status === "healthy"
                              ? styles.tweepcredHealthy
                              : styles.tweepcredWarning
                          }`}
                          title={
                            tweepcred.status === "healthy"
                              ? `Ratio: ${tweepcred.following_to_followers_ratio.toFixed(2)}. Full TweepCred reach active.`
                              : `Ratio: ${tweepcred.following_to_followers_ratio.toFixed(2)}. Twitter algorithm applies a ${tweepcred.division_factor.toFixed(1)}x penalty (${tweepcred.reach_loss_percentage}% reach suppression).`
                          }
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            {tweepcred.status === "healthy" ? (
                              <path d="M20 6 9 17l-5-5" />
                            ) : (
                              <path d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                            )}
                          </svg>
                          <span>
                            {tweepcred.status === "healthy"
                              ? "TweepCred Healthy"
                              : `${tweepcred.division_factor.toFixed(1)}x Suppression`}
                          </span>
                        </div>
                      )}

                      {/* External profile link */}
                      <a
                        href={comp.profile_url}
                        target="_blank"
                        rel="noreferrer"
                        className={styles.externalLink}
                      >
                        <span>Profile</span>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" />
                        </svg>
                      </a>
                    </div>
                  </div>

                  {/* Dropdown / Accordion Framework Breakdown */}
                  {hasFrameworks && (
                    <div className={styles.frameworkSection}>
                      <button
                        type="button"
                        className={styles.accordionHeader}
                        onClick={() => toggleAccordion(comp.handle)}
                        aria-expanded={isExpanded}
                      >
                        <div className={styles.accordionTitleGroup}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1d9bf0" strokeWidth="2.2">
                            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                          </svg>
                          <span>Winning Frameworks Breakdown</span>
                          <span className={styles.frameworkCountBadge}>
                            {comp.frameworks.length} {comp.frameworks.length === 1 ? "Formula" : "Formulas"}
                          </span>
                        </div>
                        <svg
                          className={`${styles.chevronIcon} ${isExpanded ? styles.chevronOpen : ""}`}
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                        >
                          <path d="M6 9l6 6 6-6" />
                        </svg>
                      </button>

                      {isExpanded && (
                        <div className={styles.accordionContent}>
                          {comp.frameworks.map((fw) => (
                            <div key={fw.id || fw.name} className={styles.frameworkItem}>
                              <div className={styles.frameworkItemHeader}>
                                <div className={styles.frameworkName}>
                                  {fw.title || fw.name}
                                </div>
                                {fw.lift && (
                                  <span className={styles.liftBadge}>
                                    +{fw.lift.toFixed(1)}x Lift
                                  </span>
                                )}
                              </div>

                              {/* Hook Formula with copy button */}
                              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                                <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "#71767b", letterSpacing: "0.04em" }}>
                                  Hook Formula
                                </div>
                                <div
                                  className={styles.hookFormula}
                                  title="Click to copy hook pattern"
                                  onClick={() => copyHookFormula(fw.id, fw.hook_formula)}
                                  style={{ cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}
                                >
                                  <span>{fw.hook_formula}</span>
                                  <span style={{ fontSize: 11, color: copiedHookId === fw.id ? "#00ba7c" : "#71767b" }}>
                                    {copiedHookId === fw.id ? "✓ Copied" : "Copy"}
                                  </span>
                                </div>
                              </div>

                              {/* Step-by-Step Structure */}
                              {fw.structure && (
                                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                                  <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "#71767b", letterSpacing: "0.04em" }}>
                                    Body Structure
                                  </div>
                                  <div className={styles.structureText}>{fw.structure}</div>
                                </div>
                              )}

                              {/* Why It Works / Psychology */}
                              {fw.why_it_works && (
                                <div className={styles.whyWorksText}>
                                  <strong>Why it works:</strong> {fw.why_it_works}
                                </div>
                              )}

                              {/* Action: Use in Lumi */}
                              {onUseFramework && (
                                <button
                                  type="button"
                                  className={styles.useFrameworkBtn}
                                  onClick={() => onUseFramework(fw, comp)}
                                >
                                  Use Framework in Lumi →
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Best Selling / Best Performing Posts */}
                  {hasPosts && (
                    <div className={styles.postsSection}>
                      <div className={styles.postsHeader}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                        </svg>
                        <span>Top Performing Posts</span>
                      </div>

                      <div className={styles.postsGrid}>
                        {comp.best_posts.map((post: CompetitorPost) => (
                          <div key={post.id || post.url} className={styles.postCard}>
                            <div className={styles.postCaption}>
                              {post.caption}
                            </div>

                            <div className={styles.postFooter}>
                              <div className={styles.postMetrics}>
                                {post.likes !== undefined && (
                                  <span className={styles.metricItem} title="Likes">
                                    ♥ {formatCount(post.likes)}
                                  </span>
                                )}
                                {post.replies !== undefined && (
                                  <span
                                    className={styles.metricItem}
                                    title="Replies (13.5x algorithm weight)"
                                    style={{ color: "#1d9bf0", fontWeight: 600 }}
                                  >
                                    💬 {formatCount(post.replies)}
                                  </span>
                                )}
                                {post.shares !== undefined && (
                                  <span className={styles.metricItem} title="Shares / Reposts">
                                    🔁 {formatCount(post.shares)}
                                  </span>
                                )}
                              </div>

                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                {onRepurposePost && (
                                  <button
                                    type="button"
                                    onClick={() => onRepurposePost(post.caption, comp.handle)}
                                    style={{
                                      background: "none",
                                      border: "none",
                                      color: "#8b98a5",
                                      fontSize: 11.5,
                                      fontWeight: 600,
                                      cursor: "pointer",
                                      padding: 0,
                                    }}
                                    onMouseOver={(e) => {
                                      (e.currentTarget as HTMLElement).style.color = "#1d9bf0";
                                    }}
                                    onMouseOut={(e) => {
                                      (e.currentTarget as HTMLElement).style.color = "#8b98a5";
                                    }}
                                  >
                                    Repurpose
                                  </button>
                                )}
                                <a
                                  href={post.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className={styles.postLink}
                                  title="Open live post"
                                >
                                  <span>View</span>
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" />
                                  </svg>
                                </a>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
