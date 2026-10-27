import { ApiError, openStream, request } from "./http.ts";
import type { ProfileAnalytics } from "./profiles.ts";

export type SamplePost = {
  author?: string;
  text?: string;
  likes?: number;
  url?: string;
};

export type ToolExecution = {
  name: string;
  arguments: Record<string, unknown>;
  sample_posts: SamplePost[];
  result?: unknown;
};

export type AgentResponse = {
  role: string;
  content: string;
  tool_calls_made: string[];
  tool_executions: ToolExecution[];
};

export type StreamEvent =
  | { type: "tool_start"; tool: string; arguments: Record<string, unknown>; reason?: string }
  | { type: "tool_done"; tool: string; sample_posts: SamplePost[] }
  | { type: "done"; content: string; tool_executions: ToolExecution[] }
  | { type: "error"; error: string };

export function sendChatMessage(profileId: number, message: string): Promise<AgentResponse> {
  return request<AgentResponse>("/chat", {
    method: "POST",
    body: { profile_id: profileId, message },
  });
}

/** Split an SSE buffer into complete `data:` payloads and the unfinished tail. */
export function parseSseChunk(buffer: string): { payloads: string[]; rest: string } {
  const lines = buffer.split("\n");
  const rest = lines.pop() ?? "";
  const payloads: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue; // pings (": ping") and blanks
    const json = trimmed.slice(5).trim();
    if (json) payloads.push(json);
  }
  return { payloads, rest };
}

export async function streamChatMessage(
  profileId: number,
  message: string,
  onEvent: (event: StreamEvent) => void,
  opts?: { signal?: AbortSignal },
): Promise<{ content: string; tool_executions: ToolExecution[] }> {
  const response = await openStream("/chat/stream", {
    method: "POST",
    body: { profile_id: profileId, message },
    signal: opts?.signal,
  });
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = { content: "", tool_executions: [] as ToolExecution[] };

  const handle = (payload: string) => {
    let parsed: StreamEvent;
    try {
      parsed = JSON.parse(payload) as StreamEvent;
    } catch {
      return; // a malformed event is skipped, never fatal
    }
    onEvent(parsed);
    if (parsed.type === "done") {
      finalResult = { content: parsed.content, tool_executions: parsed.tool_executions || [] };
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { payloads, rest } = parseSseChunk(buffer);
    buffer = rest;
    payloads.forEach(handle);
  }
  if (buffer.trim()) parseSseChunk(`${buffer}\n`).payloads.forEach(handle);
  return finalResult;
}

export type ChatHistoryMessage = { id: number; role: string; content: string; created_at: string };

export async function getChatHistory(profileId: number): Promise<ChatHistoryMessage[]> {
  const data = await request<{ messages?: ChatHistoryMessage[] }>("/chat/history", {
    query: { profile_id: profileId },
  });
  return data.messages ?? [];
}

/** Deletes the server-side history of a profile. Only call it on an explicit user request. */
export async function deleteChatHistory(profileId: number): Promise<void> {
  await request<void>("/chat/history", { method: "DELETE", query: { profile_id: profileId } });
}

export async function generateChatTitle(message: string): Promise<string> {
  try {
    const data = await request<{ title?: string }>("/chat/title", {
      method: "POST",
      body: { message },
    });
    if (data.title) return data.title;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) throw err;
  }
  return message.trim().split(/\s+/).slice(0, 4).join(" ") || "New chat";
}

/**
 * Connect links the server produced in this turn. The `connect_account` tool returns a
 * `connect_url`; a markdown link is drawn as a connect card only when its URL is one of these.
 */
export function connectLinksFrom(executions: ToolExecution[] | undefined): ConnectLink[] {
  const out: ConnectLink[] = [];
  for (const exec of executions ?? []) {
    if (exec.name !== "connect_account") continue;
    const result = exec.result as { connect_url?: unknown; platform?: unknown } | undefined;
    if (result && typeof result.connect_url === "string" && result.connect_url) {
      out.push({
        url: result.connect_url,
        platform: typeof result.platform === "string" ? result.platform : "",
      });
    }
  }
  return out;
}

export type ConnectLink = { url: string; platform: string };

/** The analytics card data of a turn, when the agent called `get_analytics`. */
export function analyticsFrom(executions: ToolExecution[] | undefined): ProfileAnalytics | undefined {
  const exec = executions?.find((e) => e.name === "get_analytics" && e.result);
  return exec ? (exec.result as ProfileAnalytics) : undefined;
}
