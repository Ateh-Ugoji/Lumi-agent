import { useState } from "react";
import { startConnect, startConnectMessage, syncPfm } from "../../api";
import { useT } from "../../i18n/index.ts";
import SocialIcon from "../ThinkingState/SocialIcons";
import { IconCrossSmall, IconCheckmarkSmall } from "../Sidebar/Icons";
import styles from "./ConnectSocialsModal.module.css";

export type SocialTarget = {
  key: string;
  name: string;
  hint: string;
};

const SOCIALS: SocialTarget[] = [
  { key: "x", name: "X (Twitter)", hint: "Read timeline & post" },
  { key: "instagram", name: "Instagram", hint: "Search trends & analyze" },
  { key: "tiktok", name: "TikTok", hint: "Explore viral videos & topics" },
  { key: "linkedin", name: "LinkedIn", hint: "Network insights & articles" },
  { key: "facebook", name: "Facebook", hint: "Pages publishing & metrics" },
];

export default function ConnectSocialsModal({
  isOpen,
  onClose,
  connectedPlatforms = [],
  onAccountSynced,
}: {
  isOpen: boolean;
  onClose: () => void;
  connectedPlatforms?: string[];
  onAccountSynced?: (
    account: { handle: string | null; name?: string | null; avatar_url?: string | null; platform?: string },
    jobId?: string | null,
    profileId?: number | null,
  ) => void;
}) {
  const t = useT();
  const [connecting, setConnecting] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleConnect = async (platform: string) => {
    setConnecting(platform);
    setError(null);
    try {
      try {
        localStorage.setItem(
          "lumi_pending_connect",
          JSON.stringify({ timestamp: Date.now(), platform, provider: "pfm" })
        );
      } catch {
        // storage disabled
      }
      const url = await startConnect("pfm", {
        platform,
        redirectAfter: "/",
      });
      window.location.assign(url);
    } catch (err) {
      try {
        localStorage.removeItem("lumi_pending_connect");
      } catch {
        // ignore
      }
      setConnecting(null);
      setError(startConnectMessage(err));
    }
  };

  const handleSyncAccounts = async () => {
    setSyncing(true);
    setError(null);
    try {
      const res = await syncPfm();
      const active = res.accounts.find((a) => a.status === "active") || res.accounts[0];
      if (active) {
        try {
          localStorage.removeItem("lumi_pending_connect");
        } catch {
          // ignore
        }
        if (onAccountSynced) {
          const jobId = res.job_id || (res.details?.job_id as string | undefined) || null;
          onAccountSynced(
            {
              handle: active.handle,
              name: active.display_name,
              avatar_url: active.avatar_url,
              platform: active.platform || "x",
            },
            jobId,
            res.profile_id ?? active.profile_id,
          );
        } else {
          onClose();
        }
      } else {
        setError(
          "No connected accounts found in Post for Me. Please connect your account first using the buttons below.",
        );
      }
    } catch (err) {
      setError(startConnectMessage(err));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className={styles.backdrop} onClick={onClose} role="dialog" aria-modal="true">
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Close"
        >
          <IconCrossSmall size={16} />
        </button>

        <div className={styles.header}>
          <span className={styles.badge}>Post for Me OAuth</span>
          <h2 className={styles.title}>{t("modal.connect_title")}</h2>
          <p className={styles.desc}>{t("modal.connect_desc")}</p>
        </div>

        {error && (
          <div role="alert" className={styles.errorBanner}>
            {error}
          </div>
        )}

        <div className={styles.syncBox}>
          <div className={styles.syncBoxText}>
            <span className={styles.syncBoxTitle}>Already connected in Post for Me?</span>
            <span className={styles.syncBoxDesc}>
              Pull active accounts and high-resolution profile pictures instantly.
            </span>
          </div>
          <button
            type="button"
            className={styles.syncBtn}
            disabled={syncing || connecting !== null}
            onClick={() => void handleSyncAccounts()}
          >
            {syncing ? "Syncing..." : "Sync Accounts"}
          </button>
        </div>

        <div className={styles.grid}>
          {SOCIALS.map((s) => {
            const isConnected = connectedPlatforms.includes(s.key);
            const isBusy = connecting === s.key;
            return (
              <div key={s.key} className={styles.row}>
                <div className={styles.rowPlatform}>
                  <span className={styles.iconWrap}>
                    <SocialIcon name={s.key} size={18} />
                  </span>
                  <div>
                    <span className={styles.platformName}>{s.name}</span>
                    <span className={styles.platformHint}>{s.hint}</span>
                  </div>
                </div>

                {isConnected ? (
                  <span className={styles.connectedBadge}>
                    <IconCheckmarkSmall size={14} />
                    {t("modal.connected")}
                  </span>
                ) : (
                  <button
                    type="button"
                    className={styles.connectBtn}
                    disabled={connecting !== null || syncing}
                    onClick={() => void handleConnect(s.key)}
                  >
                    {isBusy ? t("settings.connecting") : t("modal.connect_cta")}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className={styles.redirectNotice}>
          <span style={{ fontSize: "14px" }}>💡</span>
          <span>
            <strong>Note:</strong> If Post for Me redirected to your other app (e.g. Onscript) after OAuth, click <strong>Sync Accounts</strong> above. To enable automatic redirect back to Lumi, set the <em>Project Redirect URL</em> in your{" "}
            <a href="https://app.postforme.dev" target="_blank" rel="noreferrer" className={styles.link}>
              Post for Me Dashboard
            </a>{" "}
            to <code>http://localhost:3010/connections/pfm/callback</code>.
          </span>
        </div>

        <div className={styles.footer}>
          <span className={styles.footerNote}>Secure OAuth via Post for Me</span>
          <button type="button" className={styles.skipBtn} onClick={onClose}>
            {t("modal.skip")}
          </button>
        </div>
      </div>
    </div>
  );
}
