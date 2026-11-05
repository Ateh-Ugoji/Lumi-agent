import { useState } from "react";
import { startConnect, startConnectMessage } from "../../api";
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
}: {
  isOpen: boolean;
  onClose: () => void;
  connectedPlatforms?: string[];
}) {
  const t = useT();
  const [connecting, setConnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleConnect = async (platform: string) => {
    setConnecting(platform);
    setError(null);
    try {
      const url = await startConnect("pfm", {
        platform,
        redirectAfter: "/",
      });
      window.location.assign(url);
    } catch (err) {
      setConnecting(null);
      setError(startConnectMessage(err));
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
                    disabled={connecting !== null}
                    onClick={() => void handleConnect(s.key)}
                  >
                    {isBusy ? t("settings.connecting") : t("modal.connect_cta")}
                  </button>
                )}
              </div>
            );
          })}
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
