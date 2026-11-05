import { request } from "./http";

export type IMessageStatusResponse = {
  ok: boolean;
  native_macos_available: boolean;
  channel: string;
  setup_guide: {
    step_1: string;
    step_2: string;
    step_3: string;
  };
};

export type IMessageSendResponse = {
  ok: boolean;
  channel: string;
  recipient: string;
  error?: string | null;
};

export type SignalTestResponse = {
  ok: boolean;
  test_result: {
    signal: string;
    dispatched_channels: string[];
    imessage?: {
      success: boolean;
      recipient: string;
      error?: string | null;
    };
  };
};

export async function getIMessageStatus(profileId?: number | null): Promise<IMessageStatusResponse> {
  return request<IMessageStatusResponse>("/channels/imessage/status", {
    query: profileId ? { profile_id: profileId } : undefined,
  });
}

export async function sendTestIMessage(
  recipient: string,
  message: string,
  profileId?: number | null,
): Promise<IMessageSendResponse> {
  return request<IMessageSendResponse>("/channels/imessage/send", {
    method: "POST",
    query: profileId ? { profile_id: profileId } : undefined,
    body: { recipient, message },
  });
}

export async function sendTestSignal(
  eventType: string,
  recipient: string,
  profileId?: number | null,
): Promise<SignalTestResponse> {
  return request<SignalTestResponse>("/signals/test", {
    method: "POST",
    query: profileId ? { profile_id: profileId } : undefined,
    body: { event_type: eventType, imessage_recipient: recipient },
  });
}
