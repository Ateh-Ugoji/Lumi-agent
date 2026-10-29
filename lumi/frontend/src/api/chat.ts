import { ApiError, openStream, request } from "./http.ts";
import type { ProfileAnalytics } from "./profiles.ts";

export type SamplePost = {
  author?: string;
  text?: string;
  likes?: number;
  url?: string;
  /** Picture for the author (handle DB); blank -> UI falls back to unavatar */
  avatar_url?: string;
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
  | { type: "error"; error: string; code?: string };

/** Text for the error codes the agent stream can send. */
const AGENT_ERROR_MESSAGES: Record<string, string> = {
  llm_unavailable:
    "The agent isn't available right now: the language models aren't responding. Try again in a moment.",
};

/** The line the chat shows for any failed turn; HTML and raw status codes never reach it. */
export function chatErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "network_error") {
      return "Couldn't reach the Lumi server. Check that it is running.";
    }
    if (err.code === "http_error") {
      if (err.status === 502 || err.status === 503 || err.status === 504) {
        return "The Lumi server isn't responding. Try again in a moment.";
      }
      if (err.status >= 500) return "The Lumi server ran into a problem. Try again in a moment.";
    }
    return err.message;
  }
  return err instanceof Error && err.message ? err.message : "Something went wrong. Try again.";
}

export function agentErrorMessage(code: string | undefined, fallback?: string): string {
  return (
    (code && AGENT_ERROR_MESSAGES[code]) ||
    fallback ||
    "The agent failed before it finished. Try again."
  );
}

/** No byte at all (the server pings every 15 s) for this long means the agent is gone. */
export const STREAM_IDLE_MS = 45_000;

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
  opts?: { signal?: AbortSignal; idleMs?: number },
): Promise<{ content: string; tool_executions: ToolExecution[] }> {
  const response = await openStream("/chat/stream", {
    method: "POST",
    body: { profile_id: profileId, message },
    signal: opts?.signal,
  });
  // A proxy or a wrong server can answer 200 with an HTML page; it is not the agent.
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/event-stream")) {
    void response.body?.cancel().catch(() => undefined);
    throw new ApiError(
      502,
      "bad_response",
      "The server answered with something that isn't the agent (a proxy or the wrong server?). Try again.",
    );
  }
  const idleMs = opts?.idleMs ?? STREAM_IDLE_MS;
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = { content: "", tool_executions: [] as ToolExecution[] };
  let sawEnd = false;

  const handle = (payload: string) => {
    let parsed: StreamEvent;
    try {
      parsed = JSON.parse(payload) as StreamEvent;
    } catch {
      return; // a malformed event is skipped, never fatal
    }
    onEvent(parsed);
    if (parsed.type === "done" || parsed.type === "error") sawEnd = true;
    if (parsed.type === "done") {
      finalResult = { content: parsed.content, tool_executions: parsed.tool_executions || [] };
    }
  };

  while (true) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const idle = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        reject(
          new ApiError(0, "agent_timeout", "The agent didn't respond in time. Try again."),
        );
        void reader.cancel().catch(() => undefined);
      }, idleMs);
    });
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await Promise.race([reader.read(), idle]);
    } finally {
      clearTimeout(timer);
    }
    const { done, value } = chunk;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { payloads, rest } = parseSseChunk(buffer);
    buffer = rest;
    payloads.forEach(handle);
  }
  if (buffer.trim()) parseSseChunk(`${buffer}\n`).payloads.forEach(handle);
  if (!sawEnd) {
    throw new ApiError(
      0,
      "stream_incomplete",
      "The agent's reply was cut off before it finished. Try again.",
    );
  }
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
