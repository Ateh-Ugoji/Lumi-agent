import { useEffect, useState, type FormEvent } from "react";
import { useLightMode } from "../../hooks/useLightMode";
import { IconArrowBoxLeft, IconMoon, IconSun } from "../Sidebar/Icons";
import { getProfiles, getConnectAuthUrl, type ProfileSummary } from "../../api/agent";
import styles from "./Settings.module.css";

export type SettingsSection =
  | "profile"
  | "appearance"
  | "social"
  | "invitations"
  | "workspace"
  | "plan";

const SECTIONS: { key: SettingsSection; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "appearance", label: "Appearance" },
  { key: "social", label: "Connected Accounts" },
  { key: "invitations", label: "Invitations" },
  { key: "workspace", label: "Workspace" },
  { key: "plan", label: "Plan" },
];


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
  const [name, setName] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [pending, setPending] = useState<Invite[]>([]);
  const [connectedProfiles, setConnectedProfiles] = useState<ProfileSummary[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [avatarFailed, setAvatarFailed] = useState(false);

  useEffect(() => {
    setLoadingProfiles(true);
    getProfiles()
      .then((data) => {
        setConnectedProfiles(data);
        if (data.length > 0 && !name) setName(data[0].name);
      })
      .catch((err) => console.error("Error loading profiles:", err))
      .finally(() => setLoadingProfiles(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeProfile = connectedProfiles.length > 0 ? connectedProfiles[0] : null;

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
                  <span className={styles.avatar}>
                    {activeProfile && !avatarFailed ? (
                      <img
                        src={`https://unavatar.io/x/${activeProfile.handle}`}
                        alt={activeProfile.name}
                        onError={() => setAvatarFailed(true)}
                        style={{
                          width: "100%",
                          height: "100%",
                          borderRadius: "50%",
                          objectFit: "cover",
                          display: "block",
                        }}
                      />
                    ) : (
                      initialsOf(name || "Lumi")
                    )}
                  </span>
                  <span className={styles.profileMeta}>
                    <span className={styles.profileName}>
                      {name.trim() || "Unnamed"}
                    </span>
                    <span className={styles.profileMail}>
                      {activeProfile ? `@${activeProfile.handle}` : "No account connected"}
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
                  <span className={styles.fieldLabel}>X handle</span>
                  <input
                    className={`${styles.input} ${styles.inputStatic}`}
                    value={activeProfile ? `@${activeProfile.handle}` : ""}
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
