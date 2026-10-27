import { useState } from "react";
import { useLightMode } from "../../hooks/useLightMode";
import { IconArrowBoxLeft, IconMoon, IconSun } from "../Sidebar/Icons";
import { errorMessage, type ConnectReturn, type ProfileSummary, type User } from "../../api";
import ConnectionsPanel from "./ConnectionsPanel";
import styles from "./Settings.module.css";

export type SettingsSection = "profile" | "appearance" | "social" | "connectors";

const SECTIONS: { key: SettingsSection; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "appearance", label: "Appearance" },
  { key: "social", label: "Connected Accounts" },
  { key: "connectors", label: "Connectors" },
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
      setProfileError(errorMessage(err, "No se pudo crear el perfil."));
    } finally {
      setProfileBusy(false);
    }
  };

  const clearHistory = async () => {
    if (!active) return;
    if (!window.confirm(`¿Borrar del servidor el historial de chat de @${active.handle}?`)) return;
    try {
      await onClearHistory(active.id);
      setHistoryNote("Historial borrado.");
    } catch (err) {
      setHistoryNote(errorMessage(err, "No se pudo borrar el historial."));
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
            <h1 className={styles.title}>Settings</h1>
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
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          <div className={styles.panel}>
            {section === "profile" && (
              <>
                <section className={styles.card}>
                  <div className={styles.cardTitle}>Account</div>
                  <div className={styles.profileRow}>
                    <span className={styles.avatar}>{initialsOf(shownName)}</span>
                    <span className={styles.profileMeta}>
                      <span className={styles.profileName}>{shownName}</span>
                      <span className={styles.profileMail}>{user.email}</span>
                    </span>
                  </div>
                  <div className={styles.cardActions}>
                    <button type="button" className={styles.btn} onClick={onLogout}>
                      Log out
                    </button>
                  </div>
                </section>

                <section className={styles.card}>
                  <div className={styles.cardTitle}>Profiles</div>
                  <p className={styles.cardHint}>
                    Cada perfil es una cuenta social que Lumi analiza. El perfil activo guía el chat, las
                    tendencias y la publicación.
                  </p>
                  {profiles.length === 0 && (
                    <p className={styles.mutedText}>Aún no tienes perfiles. Añade el primero abajo.</p>
                  )}
                  <ul className={styles.accountList} aria-label="Profiles">
                    {profiles.map((p) => (
                      <li key={p.id} className={styles.accountRow}>
                        <span>
                          <strong>@{p.handle}</strong> · {p.platform}
                          {p.has_voice_profile ? " · voz lista" : ""}
                        </span>
                        {p.id === activeProfileId ? (
                          <span className={styles.chipOn}>Activo</span>
                        ) : (
                          <button
                            type="button"
                            className={styles.textBtn}
                            onClick={() => onSelectProfile(p.id)}
                          >
                            Usar este
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                  <div className={styles.cardActions}>
                    <select
                      className={styles.select}
                      aria-label="Red del nuevo perfil"
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
                      aria-label="Usuario del nuevo perfil"
                      placeholder="@usuario"
                      value={newHandle}
                      onChange={(e) => setNewHandle(e.target.value)}
                    />
                    <button
                      type="button"
                      className={styles.btn}
                      disabled={!newHandle.trim() || profileBusy}
                      onClick={() => void addProfile()}
                    >
                      Añadir perfil
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
                        Borrar historial de chat de @{active.handle}
                      </button>
                      {historyNote && <span className={styles.savedNote}>{historyNote}</span>}
                    </div>
                  )}
                </section>
              </>
            )}

            {section === "appearance" && (
              <section className={styles.card}>
                <div className={styles.cardTitle}>Appearance</div>
                <p className={styles.cardHint}>The theme applies everywhere, including the chat.</p>
                <div className={styles.themeSeg} role="group" aria-label="Theme">
                  <button
                    type="button"
                    aria-pressed={!light}
                    className={!light ? styles.segBtnActive : styles.segBtn}
                    onClick={() => setLight(false)}
                  >
                    <IconMoon size={15} />
                    Dark
                  </button>
                  <button
                    type="button"
                    aria-pressed={light}
                    className={light ? styles.segBtnActive : styles.segBtn}
                    onClick={() => setLight(true)}
                  >
                    <IconSun size={15} />
                    Light
                  </button>
                </div>
              </section>
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
