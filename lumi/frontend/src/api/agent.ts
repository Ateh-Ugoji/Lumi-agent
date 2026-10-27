const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export type SocialAccount = {
  id: string;
  username: string;
  platform: string;
  status: string;
};

export {
  sendChatMessage,
  streamChatMessage,
  getProfiles,
  getConnectAuthUrl,
  getTrendMatches,
  scanNicheTrends,
  getProfileAnalytics,
  generateChatTitle,
  deleteChatHistory,
  searchHandles,
  getSavedHandles,
  selectHandle,
  getGoogleConnectorStatus,
  openGoogleConsent,
  type AgentResponse,
  type StreamEvent,
  type ProfileSummary,
  type TrendMatch,
  type ProfileAnalytics,
  type ToolExecution,
  type HandleRow,
  type HandleSearchResponse,
  type GoogleConnectorStatus,
} from "./client";



export async function getProfileAlerts(profileId: number): Promise<any[]> {
  const res = await fetch(`${API_BASE}/profiles/${profileId}/alerts/unread`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.alerts || [];
}
