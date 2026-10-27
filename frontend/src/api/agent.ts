const API_BASE = "http://localhost:8000";

export type AgentResponse = {
  role: string;
  content: string;
  tool_calls_made: string[];
};

export type SocialAccount = {
  id: string;
  username: string;
  platform: string;
  status: string;
};

export async function sendChatMessage(profileId: number, message: string): Promise<AgentResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_id: profileId, message }),
  });

  if (!res.ok) {
    throw new Error(`Agent error (${res.status}): ${await res.text()}`);
  }

  return res.json();
}

export {
  streamChatMessage,
  getProfiles,
  getConnectAuthUrl,
  getTrendMatches,
  scanNicheTrends,
  getProfileAnalytics,
  generateChatTitle,
  deleteChatHistory,
  getGoogleConnectorStatus,
  openGoogleConsent,
  type StreamEvent,
  type ProfileSummary,
  type TrendMatch,
  type ProfileAnalytics,
  type GoogleConnectorStatus,
} from "./client";



export async function getProfileAlerts(profileId: number): Promise<any[]> {
  const res = await fetch(`${API_BASE}/profiles/${profileId}/alerts/unread`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.alerts || [];
}
