import { useState } from "react";
import { useLightMode } from "../../hooks/useLightMode";
import { IconArrowBoxLeft, IconMoon, IconSun } from "../Sidebar/Icons";
import { errorMessage, type ConnectReturn, type ProfileSummary, type User } from "../../api";
import { useT } from "../../i18n/index.ts";
import LangToggle from "../../i18n/LangToggle";
import ConnectionsPanel from "./ConnectionsPanel";
import styles from "./Settings.module.css";

export type SettingsSection = "profile" | "appearance" | "social" | "connectors";

const SECTIONS: { key: SettingsSection; label: string }[] = [
  { key: "profile", label: "settings.section_profile" },
  { key: "appearance", label: "settings.section_appearance" },
  { key: "social", label: "settings.section_social" },
  { key: "connectors", label: "settings.section_connectors" },
];

const NETWORKS = ["x", "linkedin", "facebook", "instagram", "tiktok"] as const;

const initialsOf = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("") || "?";

export default function Settings({
  section,
  onSectionChange,
  onBack,
  user,
  profiles,
  activeProfileId,
  onSelectProfile,
  onCreateProfile,
  onClearHistory,
  onLogout,
  returned,
  onDismissReturn,
  onConnectionsChanged,
}: {
  section: SettingsSection;
  onSectionChange: (next: SettingsSection) => void;
  onBack: () => void;
  user: User;
  profiles: ProfileSummary[];
  activeProfileId: number | null;
  onSelectProfile: (id: number) => void;
  onCreateProfile: (platform: string, handle: string) => Promise<unknown>;
  onClearHistory: (profileId: number) => Promise<void>;
  onLogout: () => void;
  returned: ConnectReturn | null;
  onDismissReturn: () => void;
  onConnectionsChanged: () => void;
}) {
  const { light, set: setLight } = useLightMode();
  const t = useT();
  const [newPlatform, setNewPlatform] = useState<string>("x");
  const [newHandle, setNewHandle] = useState("");
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const [historyNote, setHistoryNote] = useState<string | null>(null);

  const active = profiles.find((p) => p.id === activeProfileId) ?? null;
  const shownName = user.display_name || user.email;

  const addProfile = async () => {
    if (!newHandle.trim() || profileBusy) return;
    setProfileBusy(true);
    setProfileError(null);
    try {
      await onCreateProfile(newPlatform, newHandle);
      setNewHandle("");
    } catch (err) {
      setProfileError(errorMessage(err, t("settings.profile_error")));
    } finally {
      setProfileBusy(false);
    }
  };

  const clearHistory = async () => {
    if (!active) return;
    if (!window.confirm(t("settings.delete_confirm", { handle: active.handle }))) return;
    try {
      await onClearHistory(active.id);
      setHistoryNote(t("settings.history_cleared"));
    } catch (err) {
      setHistoryNote(errorMessage(err, t("settings.history_error")));
    }
  };

  return (
    <div className={styles.root}>
      <div className={styles.wrap}>
        <div className={styles.head}>
          <button
            type="button"
            aria-label="Back to chat"
            onClick={onBack}
            className={styles.backBtn}
          >
            <IconArrowBoxLeft size={16} />
          </button>
          <div className={styles.headMeta}>
            <h1 className={styles.title}>{t("settings.title")}</h1>
            <p className={styles.subtitle}>Lumi by Onscript</p>
          </div>
        </div>

        <div className={styles.layout}>
          <nav className={styles.nav} aria-label="Settings sections">
            {SECTIONS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => onSectionChange(item.key)}
                className={`${styles.navBtn} ${section === item.key ? styles.navBtnActive : ""}`}
              >
                <span>{t(item.label)}</span>
              </button>
            ))}
          </nav>

          <div className={styles.panel}>
            {section === "profile" && (
              <>
                <section className={styles.card}>
                  <div className={styles.cardTitle}>{t("settings.account")}</div>
                  <div className={styles.profileRow}>
                    <span className={styles.avatar}>{initialsOf(shownName)}</span>
                    <span className={styles.profileMeta}>
                      <span className={styles.profileName}>{shownName}</span>
                      <span className={styles.profileMail}>{user.email}</span>
                    </span>
                  </div>
                  <div className={styles.cardActions}>
                    <button type="button" className={styles.btn} onClick={onLogout}>
                      {t("settings.logout")}
                    </button>
                  </div>
                </section>

                <section className={styles.card}>
                  <div className={styles.cardTitle}>{t("settings.profiles")}</div>
                  <p className={styles.cardHint}>{t("settings.profiles_blurb")}</p>
                  {profiles.length === 0 && (
                    <p className={styles.mutedText}>{t("settings.no_profiles")}</p>
                  )}
                  <ul className={styles.accountList} aria-label="Profiles">
                    {profiles.map((p) => (
                      <li key={p.id} className={styles.accountRow}>
                        <span>
                          <strong>@{p.handle}</strong> · {p.platform}
                          {p.has_voice_profile ? t("settings.voice_ready") : ""}
                        </span>
                        {p.id === activeProfileId ? (
                          <span className={styles.chipOn}>{t("settings.active")}</span>
                        ) : (
                          <button
                            type="button"
                            className={styles.textBtn}
                            onClick={() => onSelectProfile(p.id)}
                          >
                            {t("settings.use_this")}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                  <div className={styles.cardActions}>
                    <select
                      className={styles.select}
                      aria-label={t("settings.new_network")}
                      value={newPlatform}
                      onChange={(e) => setNewPlatform(e.target.value)}
                    >
                      {NETWORKS.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                    <input
                      className={styles.input}
                      aria-label={t("settings.new_handle")}
                      placeholder={t("settings.handle_placeholder")}
                      value={newHandle}
                      onChange={(e) => setNewHandle(e.target.value)}
                    />
                    <button
                      type="button"
                      className={styles.btn}
                      disabled={!newHandle.trim() || profileBusy}
                      onClick={() => void addProfile()}
                    >
                      {t("settings.add_profile")}
                    </button>
                  </div>
                  {profileError && (
                    <p role="alert" className={styles.errorText}>
                      {profileError}
                    </p>
                  )}
                  {active && (
                    <div className={styles.cardActions}>
                      <button type="button" className={styles.textBtn} onClick={() => void clearHistory()}>
                        {t("settings.clear_history", { handle: active.handle })}
                      </button>
                      {historyNote && <span className={styles.savedNote}>{historyNote}</span>}
                    </div>
                  )}
                </section>
              </>
            )}

            {section === "appearance" && (              <>
                <section className={styles.card}>
                  <div className={styles.cardTitle}>{t("settings.appearance")}</div>
                  <p className={styles.cardHint}>{t("settings.theme_hint")}</p>
                  <div className={styles.themeSeg} role="group" aria-label={t("settings.theme")}>
                  <button
                    type="button"
                    aria-pressed={!light}
                    className={!light ? styles.segBtnActive : styles.segBtn}
                    onClick={() => setLight(false)}
                  >
                    <IconMoon size={15} />
                    {t("settings.dark")}
                  </button>
                  <button
                    type="button"
                    aria-pressed={light}
                    className={light ? styles.segBtnActive : styles.segBtn}
                    onClick={() => setLight(true)}
                  >
                    <IconSun size={15} />
                    {t("settings.light")}
                  </button>
                </div>
                </section>

                <section className={styles.card}>
                  <div className={styles.cardTitle}>{t("settings.language")}</div>
                  <p className={styles.cardHint}>{t("settings.language_hint")}</p>
                  <LangToggle />
                </section>
              </>
            )}

            {section === "social" && (
              <ConnectionsPanel
                providers={["meta", "linkedin", "x", "pfm"]}
                profileId={activeProfileId}
                profile={active}
                returned={returned}
                onDismissReturn={onDismissReturn}
                onChanged={onConnectionsChanged}
              />
            )}

            {section === "connectors" && (
              <ConnectionsPanel
                providers={["google"]}
                profileId={activeProfileId}
                returned={returned}
                onDismissReturn={onDismissReturn}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
