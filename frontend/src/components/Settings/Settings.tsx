import { useEffect, useState, type FormEvent } from "react";
import { useLightMode } from "../../hooks/useLightMode";
import { IconArrowBoxLeft, IconMoon, IconSun } from "../Sidebar/Icons";
import {
  getProfiles,
  getConnectAuthUrl,
  getGoogleConnectorStatus,
  openGoogleConsent,
  type ProfileSummary,
  type GoogleConnectorStatus,
} from "../../api/agent";
import styles from "./Settings.module.css";

export type SettingsSection =
  | "profile"
  | "appearance"
  | "social"
  | "connectors"
  | "invitations"
  | "workspace"
  | "plan";

const SECTIONS: { key: SettingsSection; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "appearance", label: "Appearance" },
  { key: "social", label: "Connected Accounts" },
  { key: "connectors", label: "Connectors" },
  { key: "invitations", label: "Invitations" },
  { key: "workspace", label: "Workspace" },
  { key: "plan", label: "Plan" },
];

// Human labels for the Google scopes Lumi requests (space-separated string
// comes straight from the OAuth token row — values never leave the DB).
const GOOGLE_SCOPE_LABELS: Record<string, string> = {
  "https://www.googleapis.com/auth/drive.readonly": "Read Drive files & metadata",
  "https://www.googleapis.com/auth/drive.file": "Create & edit files this app makes",
  "https://www.googleapis.com/auth/documents": "Create & edit Google Docs",
};

const googleScopeLabels = (scopes: string | null | undefined): string[] =>
  (scopes || "")
    .split(/\s+/)
    .filter(Boolean)
    .map((scope) => GOOGLE_SCOPE_LABELS[scope] ?? scope);

const formatExpiry = (iso: string): string => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
};


const SEAT_TOTAL = 10;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Member = { id: number; name: string; email: string; owner?: boolean };
type Invite = { id: number; email: string };

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
}: {
  section: SettingsSection;
  onSectionChange: (next: SettingsSection) => void;
  onBack: () => void;
}) {
  const { light, set: setLight } = useLightMode();
  const [name, setName] = useState("Lumi User");
  const [profileSaved, setProfileSaved] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [pending, setPending] = useState<Invite[]>([]);
  const [connectedProfiles, setConnectedProfiles] = useState<ProfileSummary[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);

  useEffect(() => {
    setLoadingProfiles(true);
    getProfiles()
      .then((data) => setConnectedProfiles(data))
      .catch((err) => console.error("Error loading profiles:", err))
      .finally(() => setLoadingProfiles(false));
  }, []);

  // Google MCP connector status (Settings → Connectors).
  const [google, setGoogle] = useState<GoogleConnectorStatus | null>(null);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [googleError, setGoogleError] = useState(false);

  const refreshGoogleStatus = () => {
    setGoogleLoading(true);
    setGoogleError(false);
    getGoogleConnectorStatus()
      .then(setGoogle)
      .catch(() => setGoogleError(true))
      .finally(() => setGoogleLoading(false));
  };

  // Re-check every time the section is opened (fresh state after returning
  // from the consent round-trip).
  useEffect(() => {
    if (section === "connectors") refreshGoogleStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  const [invite, setInvite] = useState("");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [wsName, setWsName] = useState("Lumi");
  const [wsMono, setWsMono] = useState("L");
  const [wsSaved, setWsSaved] = useState(false);
  const [billingNote, setBillingNote] = useState(false);

  const sendInvite = (event: FormEvent) => {
    event.preventDefault();
    const email = invite.trim();
    if (!EMAIL_RE.test(email)) {
      setInviteError("Enter a valid email address.");
      return;
    }
    if (
      pending.some((row) => row.email === email) ||
      members.some((member) => member.email === email)
    ) {
      setInviteError("That person is already invited or a member.");
      return;
    }
    setPending((prev) => [...prev, { id: Date.now(), email }]);
    setInvite("");
    setInviteError(null);
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
                className={`${styles.navBtn} ${
                  section === item.key ? styles.navBtnActive : ""
                }`}
              >
                <span>{item.label}</span>
                {item.key === "invitations" && pending.length > 0 && (
                  <span className={styles.navBadge}>{pending.length}</span>
                )}
              </button>
            ))}
          </nav>

          <div className={styles.panel}>
            {section === "profile" && (
              <section className={styles.card}>
                <div className={styles.cardTitle}>Profile</div>
                <p className={styles.cardHint}>
                  How you appear to teammates in this workspace.
                </p>
                <div className={styles.profileRow}>
                  <span className={styles.avatar}>{initialsOf(name)}</span>
                  <span className={styles.profileMeta}>
                    <span className={styles.profileName}>
                      {name.trim() || "Unnamed"}
                    </span>
                    <span className={styles.profileMail}>
                      alex@lumi.app
                    </span>
                  </span>
                </div>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Display name</span>
                  <input
                    className={styles.input}
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      setProfileSaved(false);
                    }}
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Email</span>
                  <input
                    className={`${styles.input} ${styles.inputStatic}`}
                    value="alex@lumi.app"
                    readOnly
                    tabIndex={-1}
                  />
                </label>
                <div className={styles.cardActions}>
                  <button
                    type="button"
                    className={styles.btn}
                    disabled={!name.trim()}
                    onClick={() => setProfileSaved(true)}
                  >
                    Save changes
                  </button>
                  {profileSaved && (
                    <span className={styles.savedNote}>Saved</span>
                  )}
                </div>
              </section>
            )}

            {section === "appearance" && (
              <section className={styles.card}>
                <div className={styles.cardTitle}>Appearance</div>
                <p className={styles.cardHint}>
                  The theme applies everywhere, including the chat.
                </p>
                <div
                  className={styles.themeSeg}
                  role="group"
                  aria-label="Theme"
                >
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
              <section className={styles.card}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div>
                    <div className={styles.cardTitle}>Connected Accounts</div>
                    <p className={styles.cardHint}>
                      Social accounts linked to Lumi via Post for Me.
                    </p>
                  </div>
                  <button
                    type="button"
                    className={styles.btn}
                    onClick={async () => {
                      const url = await getConnectAuthUrl("twitter");
                      if (url) window.location.href = url;
                    }}
                  >
                    + Connect Account
                  </button>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
                  {loadingProfiles && (
                    <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 12 }}>
                      Loading connected accounts...
                    </div>
                  )}
                  {!loadingProfiles && connectedProfiles.length === 0 && (
                    <div style={{ textAlign: "center", padding: "24px 16px", background: "rgba(255,255,255,0.02)", borderRadius: 8 }}>
                      <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 12 }}>
                        No social accounts connected yet.
                      </p>
                      <button
                        type="button"
                        className={styles.btn}
                        onClick={async () => {
                          const url = await getConnectAuthUrl("twitter");
                          if (url) window.location.href = url;
                        }}
                      >
                        Connect Social Account
                      </button>
                    </div>
                  )}
                  {!loadingProfiles &&
                    connectedProfiles.map((p) => (
                      <div
                        key={p.id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "12px 16px",
                          borderRadius: 8,
                          background: "rgba(255,255,255,0.04)",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <span style={{ fontWeight: 600, fontSize: 14, textTransform: "capitalize" }}>
                            {p.platform === "x" ? "X (Twitter)" : p.platform}
                          </span>
                          <span style={{ color: "#38bdf8", fontSize: 13 }}>
                            @{p.handle}
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {p.has_voice_profile && (
                            <span style={{ fontSize: 11, padding: "2px 6px", borderRadius: 4, background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8" }}>
                              Voice active
                            </span>
                          )}
                          <span style={{ color: "#4ade80", fontSize: 12, fontWeight: 500 }}>
                            ● Connected
                          </span>
                        </div>
                      </div>
                    ))}
                </div>
              </section>
            )}

            {section === "connectors" && (
              <section className={styles.card}>
                <div className={styles.cardTitle}>Connectors</div>
                <p className={styles.cardHint}>
                  External services the agent can reach through MCP connectors —
                  Google Drive &amp; Docs first. Once connected, ask in chat
                  (“make a doc about my week”) or type #doc in the composer.
                </p>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginTop: 8,
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>
                      Google Drive &amp; Docs
                    </div>
                    <p
                      className={styles.cardHint}
                      style={{ marginBottom: 0 }}
                    >
                      One Google consent covers Drive reads, files this app
                      creates, and Docs.
                    </p>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {googleLoading ? (
                      <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        Checking…
                      </span>
                    ) : googleError ? (
                      <span style={{ color: "var(--red)", fontSize: 12 }}>
                        Backend unreachable
                      </span>
                    ) : google?.connected ? (
                      <span
                        style={{
                          color: "#4ade80",
                          fontSize: 12,
                          fontWeight: 500,
                        }}
                      >
                        ● Connected
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        Not connected
                      </span>
                    )}
                  </div>
                </div>

                {!googleLoading &&
                  !googleError &&
                  google != null &&
                  google.configured === false && (
                    <p
                      style={{
                        color: "var(--text-muted)",
                        fontSize: 13,
                        marginTop: 12,
                      }}
                    >
                      Google OAuth isn’t configured on this server yet — set
                      GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET (see{" "}
                      <code>docs/mcp-connectors.md</code>, §3), then restart the
                      backend.
                    </p>
                  )}

                {google?.connected && (
                  <div
                    style={{
                      marginTop: 14,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                  >
                    <div
                      style={{ fontSize: 12.5, color: "var(--text-dim)" }}
                    >
                      Granted scopes
                    </div>
                    {googleScopeLabels(google.scopes).map((label) => (
                      <div
                        key={label}
                        style={{ fontSize: 13, color: "var(--text)" }}
                      >
                        · {label}
                      </div>
                    ))}
                    {google.expires_at && (
                      <div
                        style={{
                          fontSize: 12,
                          color: "var(--text-muted)",
                          marginTop: 2,
                        }}
                      >
                        Access token expires {formatExpiry(google.expires_at)} —
                        refresh is automatic.
                      </div>
                    )}
                  </div>
                )}

                <div className={styles.cardActions}>
                  <button
                    type="button"
                    className={styles.btn}
                    disabled={
                      googleLoading ||
                      googleError ||
                      google?.configured === false
                    }
                    onClick={openGoogleConsent}
                  >
                    {google?.connected
                      ? "Reconnect Google"
                      : "Connect Google"}
                  </button>
                  <button
                    type="button"
                    className={styles.textBtn}
                    onClick={refreshGoogleStatus}
                  >
                    Refresh
                  </button>
                </div>
              </section>
            )}

            {section === "invitations" && (

              <section className={styles.card}>
                <div className={styles.cardTitle}>Invitations</div>
                <p className={styles.cardHint}>
                  Invite teammates by email and manage who has access.
                </p>
                <div className={styles.seatsHead}>
                  <span className={styles.seatsLabel}>
                    {members.length} of {SEAT_TOTAL} seats used
                  </span>
                  <span className={styles.seatsLabel}>
                    {pending.length} pending
                  </span>
                </div>
                <div className={styles.seatBar}>
                  <span
                    className={styles.seatFill}
                    style={{
                      width: `${Math.min(
                        (members.length / SEAT_TOTAL) * 100,
                        100,
                      )}%`,
                    }}
                  />
                </div>
                <form className={styles.inviteForm} onSubmit={sendInvite}>
                  <input
                    className={styles.input}
                    value={invite}
                    placeholder="teammate@company.com"
                    aria-label="Invitee email"
                    onChange={(event) => {
                      setInvite(event.target.value);
                      setInviteError(null);
                    }}
                  />
                  <button type="submit" className={styles.btn}>
                    Send invite
                  </button>
                </form>
                {inviteError && <p className={styles.error}>{inviteError}</p>}
                {pending.length > 0 && (
                  <div className={styles.list}>
                    <div className={styles.listHead}>Pending invites</div>
                    {pending.map((row) => (
                      <div key={row.id} className={styles.listRow}>
                        <span className={styles.listName}>{row.email}</span>
                        <span className={styles.statusChip}>Pending</span>
                        <button
                          type="button"
                          className={styles.textBtn}
                          onClick={() =>
                            setPending((prev) =>
                              prev.filter((item) => item.id !== row.id),
                            )
                          }
                        >
                          Revoke
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className={styles.list}>
                  <div className={styles.listHead}>Members</div>
                  {members.map((member) => (
                    <div key={member.id} className={styles.listRow}>
                      <span className={styles.memberAvatar}>
                        {initialsOf(member.name)}
                      </span>
                      <span className={styles.listName}>{member.name}</span>
                      <span
                        className={
                          member.owner ? styles.roleChipOwner : styles.roleChip
                        }
                      >
                        {member.owner ? "Owner" : "Member"}
                      </span>
                      {!member.owner && (
                        <button
                          type="button"
                          className={`${styles.textBtn} ${styles.textBtnDanger}`}
                          onClick={() =>
                            setMembers((prev) =>
                              prev.filter((item) => item.id !== member.id),
                            )
                          }
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {section === "workspace" && (
              <section className={styles.card}>
                <div className={styles.cardTitle}>Workspace</div>
                <p className={styles.cardHint}>
                  Shared settings for everyone in this workspace.
                </p>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Workspace name</span>
                  <input
                    className={styles.input}
                    value={wsName}
                    onChange={(event) => {
                      setWsName(event.target.value);
                      setWsSaved(false);
                    }}
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Monogram</span>
                  <input
                    className={styles.input}
                    value={wsMono}
                    maxLength={2}
                    onChange={(event) => {
                      setWsMono(event.target.value);
                      setWsSaved(false);
                    }}
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Workspace URL</span>
                  <input
                    className={`${styles.input} ${styles.inputStatic}`}
                    value="lumi.app/lumi"
                    readOnly
                    tabIndex={-1}
                  />
                </label>
                <div className={styles.cardActions}>
                  <button
                    type="button"
                    className={styles.btn}
                    disabled={!wsName.trim() || !wsMono.trim()}
                    onClick={() => setWsSaved(true)}
                  >
                    Save changes
                  </button>
                  {wsSaved && <span className={styles.savedNote}>Saved</span>}
                </div>
              </section>
            )}

            {section === "plan" && (
              <section className={styles.card}>
                <div className={styles.cardTitle}>Plan</div>
                <p className={styles.cardHint}>
                  Your current subscription and seat usage.
                </p>
                <div className={styles.planRow}>
                  <span className={styles.planName}>Pro</span>
                  <span className={styles.planPrice}>
                    $12
                    <span className={styles.planUnit}> / seat / month</span>
                  </span>
                </div>
                <div className={styles.planMeta}>
                  <div className={styles.planMetaRow}>
                    <span>Seats</span>
                    <span>
                      {members.length} of {SEAT_TOTAL}
                    </span>
                  </div>
                  <div className={styles.planMetaRow}>
                    <span>Billing</span>
                    <span>Monthly · renews Nov 7, 2026</span>
                  </div>
                </div>
                <div className={styles.cardActions}>
                  <button
                    type="button"
                    className={styles.btn}
                    onClick={() => setBillingNote(true)}
                  >
                    Upgrade
                  </button>
                  {billingNote && (
                    <span className={styles.savedNote}>
                      We will email alex@lumi.app about billing.
                    </span>
                  )}
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
