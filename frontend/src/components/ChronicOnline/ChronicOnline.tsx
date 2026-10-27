import { useEffect, useMemo, useState } from "react";
import { getTrendMatches, scanNicheTrends, type TrendMatch } from "../../api/agent";
import styles from "./ChronicOnline.module.css";

type ChronicOnlineProps = {
  profileId?: number;
  onRepurpose: (caption: string, author: string) => void;
  onBack?: () => void;
};

const DISPLAY_NAMES: Record<string, string> = {
  sama: "Sam Altman",
  levelsio: "Pieter Levels",
  karpathy: "Andrej Karpathy",
  paulg: "Paul Graham",
  swyx: "swyx",
  AtehOfficial: "Ateh Ugoji",
};

// Authentic X Post Icons
const Icons = {
  reply: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" />
    </svg>
  ),
  repost: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M17 1l4 4-4 4" />
      <path d="M3 11V9a4 4 0 014-4h14" />
      <path d="M7 23l-4-4 4-4" />
      <path d="M21 13v2a4 4 0 01-4 4H3" />
    </svg>
  ),
  heart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" />
    </svg>
  ),
  views: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  share: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8" />
      <polyline points="16 6 12 2 8 6" />
      <line x1="12" y1="2" x2="12" y2="15" />
    </svg>
  ),
  verified: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="#1d9bf0">
      <path d="M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.67-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.67-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34zm-11.71 4.2L6.8 12.46l1.41-1.42 2.26 2.26 4.8-5.23 1.47 1.36-6.2 6.77z" />
    </svg>
  ),
  xLogo: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  ),
};

export default function ChronicOnline({
  profileId = 1,
  onRepurpose,
  onBack,
}: ChronicOnlineProps) {
  const [matches, setMatches] = useState<TrendMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [search, setSearch] = useState("");
  const [primaryTab, setPrimaryTab] = useState<"posts" | "conversations" | "all">("posts");
  const [topicFilter, setTopicFilter] = useState<"all" | "indie" | "ai" | "viral">("all");
  const [avatarErrors, setAvatarErrors] = useState<Record<string, boolean>>({});

  const loadMatches = async () => {
    try {
      setLoading(true);
      const data = await getTrendMatches(profileId, 80);
      setMatches(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMatches();
  }, [profileId]);

  const handleScan = async () => {
    try {
      setScanning(true);
      await scanNicheTrends(
        profileId,
        ["sama", "levelsio", "karpathy", "paulg", "swyx"],
        20,
      );
      await loadMatches();
    } catch (err) {
      console.error("Scan failed", err);
    } finally {
      setScanning(false);
    }
  };

  const isReply = (caption: string) => caption.trim().startsWith("@");

  const extractReplyTarget = (caption: string) => {
    const match = caption.trim().match(/^@(\w+)/);
    return match ? match[1] : null;
  };

  const counts = useMemo(() => {
    let postCount = 0;
    let convoCount = 0;
    for (const m of matches) {
      if (isReply(m.caption)) convoCount += 1;
      else postCount += 1;
    }
    return { posts: postCount, conversations: convoCount, all: matches.length };
  }, [matches]);

  const filteredMatches = useMemo(() => {
    return matches.filter((m) => {
      const isConvo = isReply(m.caption);

      // Primary tab filtering: Posts vs Conversations vs All
      if (primaryTab === "posts" && isConvo) return false;
      if (primaryTab === "conversations" && !isConvo) return false;

      const text = `${m.author_handle} ${m.caption}`.toLowerCase();
      const matchesSearch = !search.trim() || text.includes(search.toLowerCase());
      if (!matchesSearch) return false;

      const likes = m.metrics?.like_count || 0;
      if (topicFilter === "viral") return likes >= 100;
      if (topicFilter === "ai") return /ai|agent|model|chatgpt|claude|llm|devday/i.test(text);
      if (topicFilter === "indie") return /software|builder|build|startup|user|product|founder|code/i.test(text);

      return true;
    });
  }, [matches, primaryTab, topicFilter, search]);

  const formatCount = (count?: number) => {
    if (!count) return "0";
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return String(count);
  };

  const getDisplayName = (handle: string) => {
    return DISPLAY_NAMES[handle] || `@${handle}`;
  };

  return (
    <div className={styles.root}>
      <div className={styles.wrap}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.titleRow}>
            <div className={styles.titleBadge}>
              <span className={styles.pulseDot} />
              <span>Live Social Radar</span>
            </div>
            <h1 className={styles.title}>Chronically Online</h1>
            <p className={styles.subtitle}>
              Monitor viral peer posts in your niche. Spot winning formats and adapt them to your
              voice across socials with 1 click.
            </p>
          </div>
          <button
            type="button"
            className={styles.scanBtn}
            onClick={handleScan}
            disabled={scanning}
          >
            {scanning ? "Scanning Niche..." : "⚡ Scan Niche Trends"}
          </button>
        </div>

        {/* Primary Tabs: Posts vs Conversations */}
        <div className={styles.primaryTabs}>
          <button
            type="button"
            className={`${styles.primaryTab} ${primaryTab === "posts" ? styles.primaryTabActive : ""}`}
            onClick={() => setPrimaryTab("posts")}
          >
            <span>Posts</span>
            <span className={styles.tabBadge}>{counts.posts}</span>
          </button>
          <button
            type="button"
            className={`${styles.primaryTab} ${primaryTab === "conversations" ? styles.primaryTabActive : ""}`}
            onClick={() => setPrimaryTab("conversations")}
          >
            <span>Conversations</span>
            <span className={styles.tabBadge}>{counts.conversations}</span>
          </button>
          <button
            type="button"
            className={`${styles.primaryTab} ${primaryTab === "all" ? styles.primaryTabActive : ""}`}
            onClick={() => setPrimaryTab("all")}
          >
            <span>All Signals</span>
            <span className={styles.tabBadge}>{counts.all}</span>
          </button>
        </div>

        {/* Secondary Topic Filter & Search */}
        <div className={styles.filterRow}>
          <div className={styles.topicChips}>
            <button
              type="button"
              className={`${styles.topicChip} ${topicFilter === "all" ? styles.topicChipActive : ""}`}
              onClick={() => setTopicFilter("all")}
            >
              All Topics
            </button>
            <button
              type="button"
              className={`${styles.topicChip} ${topicFilter === "indie" ? styles.topicChipActive : ""}`}
              onClick={() => setTopicFilter("indie")}
            >
              Indie Builders
            </button>
            <button
              type="button"
              className={`${styles.topicChip} ${topicFilter === "ai" ? styles.topicChipActive : ""}`}
              onClick={() => setTopicFilter("ai")}
            >
              AI &amp; Tech
            </button>
            <button
              type="button"
              className={`${styles.topicChip} ${topicFilter === "viral" ? styles.topicChipActive : ""}`}
              onClick={() => setTopicFilter("viral")}
            >
              Viral Only (&gt;100 likes)
            </button>
          </div>

          <div className={styles.searchBox}>
            <input
              type="text"
              placeholder="Filter by keyword or @handle..."
              className={styles.searchInput}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* Content Feed */}
        {loading ? (
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>Scanning social radar...</p>
            <p className={styles.emptyDesc}>Retrieving trending niche tweets and signals.</p>
          </div>
        ) : filteredMatches.length === 0 ? (
          <div className={styles.emptyState}>
            <p className={styles.emptyTitle}>No matching {primaryTab} found</p>
            <p className={styles.emptyDesc}>
              Try switching tabs, clearing search filters, or click "Scan Niche Trends" above.
            </p>
          </div>
        ) : (
          <div className={styles.feed}>
            {filteredMatches.map((item) => {
              const replyTarget = extractReplyTarget(item.caption);
              const avatarFailed = avatarErrors[item.author_handle];
              const pfpUrl = `https://unavatar.io/x/${item.author_handle}`;

              return (
                <div key={item.id} className={styles.tweetCard}>
                  <div className={styles.tweetMain}>
                    {/* Left Column: Avatar */}
                    <div className={styles.avatarCol}>
                      {!avatarFailed ? (
                        <img
                          src={pfpUrl}
                          alt={item.author_handle}
                          className={styles.avatarImg}
                          onError={() =>
                            setAvatarErrors((prev) => ({
                              ...prev,
                              [item.author_handle]: true,
                            }))
                          }
                        />
                      ) : (
                        <div className={styles.avatarFallback}>
                          {item.author_handle.slice(0, 1).toUpperCase()}
                        </div>
                      )}
                    </div>

                    {/* Right Column: Tweet Content & Actions */}
                    <div className={styles.contentCol}>
                      {/* Header Row */}
                      <div className={styles.authorRow}>
                        <div className={styles.authorMeta}>
                          <span className={styles.authorName}>
                            {getDisplayName(item.author_handle)}
                          </span>
                          <span className={styles.verifiedBadge}>{Icons.verified}</span>
                          <span className={styles.authorHandle}>@{item.author_handle}</span>
                          <span className={styles.dot}>·</span>
                          <span className={styles.timestamp}>1d</span>
                        </div>
                        <div className={styles.topLinks}>
                          {item.platform_url && (
                            <a
                              href={item.platform_url}
                              target="_blank"
                              rel="noreferrer"
                              className={styles.extLink}
                              title="Open on X"
                            >
                              <span className={styles.xLogo}>{Icons.xLogo}</span>
                            </a>
                          )}
                        </div>
                      </div>

                      {/* Replying To indicator if conversation */}
                      {replyTarget && (
                        <div className={styles.replyingTo}>
                          Replying to <span className={styles.replyTarget}>@{replyTarget}</span>
                        </div>
                      )}

                      {/* Tweet Body */}
                      <p className={styles.tweetText}>{item.caption}</p>

                      {/* Authentic X Tweet Action Bar */}
                      <div className={styles.tweetActions}>
                        <div className={`${styles.actionItem} ${styles.actionReply}`} title="Replies">
                          {Icons.reply}
                          <span>{formatCount(item.metrics?.reply_count || 12)}</span>
                        </div>
                        <div className={`${styles.actionItem} ${styles.actionRepost}`} title="Reposts">
                          {Icons.repost}
                          <span>{formatCount(item.metrics?.retweet_count || 24)}</span>
                        </div>
                        <div className={`${styles.actionItem} ${styles.actionLike}`} title="Likes">
                          {Icons.heart}
                          <span>{formatCount(item.metrics?.like_count || 120)}</span>
                        </div>
                        <div className={`${styles.actionItem} ${styles.actionViews}`} title="Views">
                          {Icons.views}
                          <span>{formatCount(item.metrics?.impression_count || 14000)}</span>
                        </div>
                        <div className={`${styles.actionItem} ${styles.actionShare}`} title="Share">
                          {Icons.share}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Lumi Repurposing Footer */}
                  <div className={styles.repurposeBar}>
                    <div className={styles.voiceHint}>
                      <span>⚡ Adapt into your creator voice</span>
                    </div>
                    <button
                      type="button"
                      className={styles.repurposeBtn}
                      onClick={() => onRepurpose(item.caption, item.author_handle)}
                    >
                      <span>⚡ Repurpose in My Voice</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
