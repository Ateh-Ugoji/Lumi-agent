import { useEffect, useState } from "react";
import {
  getIMessageStatus,
  sendTestIMessage,
  sendTestSignal,
  type IMessageStatusResponse,
} from "../../api";
import styles from "./Settings.module.css";

interface ChannelsPanelProps {
  profileId: number | null;
}

export default function ChannelsPanel({ profileId }: ChannelsPanelProps) {
  const [status, setStatus] = useState<IMessageStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [recipient, setRecipient] = useState<string>(() => {
    return localStorage.getItem("lumi_imessage_recipient") || "";
  });
  const [testSending, setTestSending] = useState(false);
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [selectedSignal, setSelectedSignal] = useState<string>("spike.velocity");
  const [signalTesting, setSignalTesting] = useState(false);
  const [signalStatus, setSignalStatus] = useState<string | null>(null);
  const [showGuide, setShowGuide] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await getIMessageStatus(profileId);
        setStatus(res);
      } catch (err) {
        console.error("Failed to load iMessage status", err);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [profileId]);

  const handleSaveRecipient = (val: string) => {
    setRecipient(val);
    localStorage.setItem("lumi_imessage_recipient", val);
  };

  const handleSendTestMessage = async () => {
    if (!recipient.trim()) {
      setTestStatus("Please enter an Apple ID email or phone number first.");
      return;
    }
    setTestSending(true);
    setTestStatus(null);
    try {
      const res = await sendTestIMessage(
        recipient.trim(),
        "Hello from Lumi! Your native iMessage channel is connected. You can now receive real-time viral signals and text Lumi directly from iPhone.",
        profileId,
      );
      if (res.ok) {
        setTestStatus("✓ Test message sent successfully via " + res.channel);
      } else {
        setTestStatus("Failed to send: " + (res.error || "Unknown error"));
      }
    } catch (err) {
      setTestStatus(err instanceof Error ? err.message : "Network error");
    } finally {
      setTestSending(false);
    }
  };

  const handleTestSignal = async () => {
    if (!recipient.trim()) {
      setSignalStatus("Please set your iMessage recipient above first.");
      return;
    }
    setSignalTesting(true);
    setSignalStatus(null);
    try {
      const res = await sendTestSignal(selectedSignal, recipient.trim(), profileId);
      if (res.ok) {
        setSignalStatus(`✓ ${selectedSignal} alert dispatched to ${recipient}!`);
      } else {
        setSignalStatus("Failed to dispatch signal alert.");
      }
    } catch (err) {
      setSignalStatus(err instanceof Error ? err.message : "Error triggering signal");
    } finally {
      setSignalTesting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Top Banner */}
      <div className={styles.sectionHeader} style={{ marginBottom: 0 }}>
        <h2 className={styles.sectionTitle}>iMessage & Messaging Channels</h2>
        <p className={styles.sectionSubtitle}>
          Connect native Apple iMessage to receive real-time viral velocity alerts, Golden-Hour reply reminders,
          and chat with Lumi directly from your iPhone.
        </p>
      </div>

      {/* iMessage Status Card */}
      <div
        style={{
          background: "var(--card-bg, #16181c)",
          border: "1px solid var(--border-subtle, #2f3336)",
          borderRadius: 16,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: "linear-gradient(135deg, #007aff, #0056b3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#ffffff",
                fontWeight: 800,
                fontSize: 16,
              }}
            >
              💬
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#e7e9ea" }}>Apple iMessage Bridge</div>
              <div style={{ fontSize: 12, color: "#71767b" }}>
                {loading
                  ? "Checking system bridge..."
                  : status?.native_macos_available
                    ? "macOS Native Messages Bridge Active"
                    : "Remote BlueBubbles Gateway Mode"}
              </div>
            </div>
          </div>

          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              fontWeight: 600,
              padding: "4px 10px",
              borderRadius: 20,
              background: status?.native_macos_available ? "rgba(0, 186, 124, 0.12)" : "rgba(255, 170, 0, 0.12)",
              color: status?.native_macos_available ? "#00ba7c" : "#ffaa00",
              border: `1px solid ${status?.native_macos_available ? "rgba(0, 186, 124, 0.25)" : "rgba(255, 170, 0, 0.25)"}`,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: status?.native_macos_available ? "#00ba7c" : "#ffaa00",
              }}
            />
            <span>{status?.native_macos_available ? "Connected" : "Remote"}</span>
          </div>
        </div>

        {/* Recipient Configuration */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: "#cfd9de" }}>
            Your iPhone Number or Apple ID Email
          </label>
          <div style={{ display: "flex", gap: 10 }}>
            <input
              type="text"
              placeholder="+1234567890 or creator@icloud.com"
              value={recipient}
              onChange={(e) => handleSaveRecipient(e.target.value)}
              style={{
                flex: 1,
                padding: "10px 14px",
                fontSize: 13.5,
                background: "#0f1013",
                border: "1px solid #2f3336",
                borderRadius: 8,
                color: "#e7e9ea",
                outline: "none",
              }}
            />
            <button
              type="button"
              onClick={handleSendTestMessage}
              disabled={testSending || !recipient.trim()}
              style={{
                padding: "10px 18px",
                background: "#1d9bf0",
                color: "#ffffff",
                border: "none",
                borderRadius: 8,
                fontWeight: 700,
                fontSize: 13,
                cursor: testSending ? "not-allowed" : "pointer",
                opacity: testSending || !recipient.trim() ? 0.6 : 1,
              }}
            >
              {testSending ? "Sending..." : "Send Test iMessage"}
            </button>
          </div>
          {testStatus && (
            <div
              style={{
                fontSize: 12.5,
                color: testStatus.startsWith("✓") ? "#00ba7c" : "#f4212e",
                marginTop: 2,
              }}
            >
              {testStatus}
            </div>
          )}
        </div>

        {/* How to Register Guide */}
        <div
          style={{
            background: "#0f1013",
            border: "1px solid #24272b",
            borderRadius: 10,
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              cursor: "pointer",
            }}
            onClick={() => setShowGuide(!showGuide)}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: "#1d9bf0" }}>
              📖 How to register an account or number to text Lumi from iPhone
            </div>
            <span style={{ fontSize: 12, color: "#71767b" }}>{showGuide ? "▲ Hide" : "▼ Expand"}</span>
          </div>

          {showGuide && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 12.5, color: "#8b98a5", lineHeight: 1.5 }}>
              <div>
                <strong>Option A: Dedicated Apple ID (Free & Instant)</strong>
                <br />
                1. Create a free Apple ID (e.g. <code>lumi.agent@gmail.com</code>).
                <br />
                2. On this Mac, open Messages app → Settings → iMessage → sign in with that Apple ID.
                <br />
                3. On your iPhone, text that email address. It appears as a blue bubble, and Lumi replies automatically!
              </div>
              <div>
                <strong>Option B: Dedicated Phone Number (eSIM / SIM)</strong>
                <br />
                1. Add an eSIM or second number to an iPhone or iPad logged into the Lumi Apple ID.
                <br />
                2. Save that number in your iPhone contacts as "Lumi AI".
                <br />
                3. Text the contact to receive instant AI turns, viral audits, and caption repurposing directly in iMessage.
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Signal Alerts Section */}
      <div
        style={{
          background: "var(--card-bg, #16181c)",
          border: "1px solid var(--border-subtle, #2f3336)",
          borderRadius: 16,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#e7e9ea" }}>Algorithmic Post Signal Alerts</div>
          <div style={{ fontSize: 12, color: "#71767b" }}>
            Lumi monitors your posts and niche peers. Test-fire real algorithmic alert notifications to your iMessage:
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <select
            value={selectedSignal}
            onChange={(e) => setSelectedSignal(e.target.value)}
            style={{
              flex: 1,
              padding: "10px 14px",
              fontSize: 13,
              background: "#0f1013",
              border: "1px solid #2f3336",
              borderRadius: 8,
              color: "#e7e9ea",
              outline: "none",
            }}
          >
            <option value="spike.velocity">⚡ Engagement Velocity Spike (3.5x+ velocity)</option>
            <option value="author.golden_hour">⏳ Golden Hour Sprint (+75x Author Multiplier)</option>
            <option value="competitor.breakout">🎯 Competitor Breakout Hook Alert</option>
            <option value="tweepcred.degraded">⚠️ TweepCred Ratio Warning (DivFactor &gt; 0.60)</option>
          </select>

          <button
            type="button"
            onClick={handleTestSignal}
            disabled={signalTesting || !recipient.trim()}
            style={{
              padding: "10px 18px",
              background: "#202327",
              color: "#e7e9ea",
              border: "1px solid #38444d",
              borderRadius: 8,
              fontWeight: 700,
              fontSize: 13,
              cursor: signalTesting ? "not-allowed" : "pointer",
            }}
          >
            {signalTesting ? "Testing..." : "Test Signal Alert"}
          </button>
        </div>

        {signalStatus && (
          <div
            style={{
              fontSize: 12.5,
              color: signalStatus.startsWith("✓") ? "#00ba7c" : "#f4212e",
            }}
          >
            {signalStatus}
          </div>
        )}
      </div>
    </div>
  );
}
