import assert from "node:assert/strict";
import { test } from "node:test";
import {
  agentErrorMessage,
  analyticsFrom,
  connectLinksFrom,
  parseSseChunk,
  streamChatMessage,
  type StreamEvent,
} from "../src/api/chat.ts";
import { ApiError } from "../src/api/http.ts";

test("parseSseChunk returns whole data lines and keeps the unfinished tail", () => {
  const out = parseSseChunk('data: {"a":1}\n: ping\n\ndata: {"b":2}\ndata: {"c"');
  assert.deepEqual(out.payloads, ['{"a":1}', '{"b":2}']);
  assert.equal(out.rest, 'data: {"c"');
});

test("parseSseChunk ignores empty data lines", () => {
  assert.deepEqual(parseSseChunk("data:\n").payloads, []);
});

test("connectLinksFrom keeps only connect_account results with a url", () => {
  const links = connectLinksFrom([
    { name: "get_analytics", args: {}, result: { connect_url: "https://nope" } },
    { name: "connect_account", args: {}, result: { already_connected: true, platform: "x" } },
    { name: "connect_account", args: {}, result: { connect_url: "https://auth/x", platform: "x" } },
    { name: "connect_account", args: {}, result: { connect_url: "https://auth/li", platform: "linkedin" } },
  ]);
  assert.deepEqual(links, [
    { url: "https://auth/x", platform: "x" },
    { url: "https://auth/li", platform: "linkedin" },
  ]);
  assert.deepEqual(connectLinksFrom(undefined), []);
});

test("analyticsFrom picks the get_analytics result", () => {
  assert.equal(analyticsFrom(undefined), undefined);
  const result = { followers: 3 };
  assert.equal(analyticsFrom([{ name: "get_analytics", args: {}, result }]), result);
});


function mockFetch(make: () => Response): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => make()) as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

function sse(...events: unknown[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}

`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    assert.ok(err instanceof ApiError, `expected ApiError, got ${String(err)}`);
    return err;
  }
  assert.fail("expected the stream to reject");
}

test("agentErrorMessage translates known codes and falls back to the server text", () => {
  assert.match(agentErrorMessage("llm_unavailable", "The language models are unavailable"), /no está disponible/);
  assert.equal(agentErrorMessage("other", "server text"), "server text");
  assert.match(agentErrorMessage(undefined), /falló/);
});

test("streamChatMessage hands the agent error event to the caller", async () => {
  const restore = mockFetch(() => sse({ type: "error", code: "llm_unavailable", error: "down" }));
  try {
    const seen: StreamEvent[] = [];
    await streamChatMessage(1, "hola", (e) => seen.push(e));
    assert.deepEqual(seen, [{ type: "error", code: "llm_unavailable", error: "down" }]);
  } finally {
    restore();
  }
});

test("streamChatMessage refuses a 200 that is an HTML page, not the agent", async () => {
  const restore = mockFetch(
    () => new Response("<html><h1>Bad Gateway</h1></html>", { status: 200, headers: { "Content-Type": "text/html" } }),
  );
  try {
    const err = await rejection(streamChatMessage(1, "hola", () => {}));
    assert.equal(err.code, "bad_response");
    assert.ok(!err.message.includes("<"));
  } finally {
    restore();
  }
});

test("streamChatMessage reports a stream that ends without a final event", async () => {
  const restore = mockFetch(() => sse({ type: "tool_start", tool: "get_posts", arguments: {} }));
  try {
    const err = await rejection(streamChatMessage(1, "hola", () => {}));
    assert.equal(err.code, "stream_incomplete");
  } finally {
    restore();
  }
});

test("streamChatMessage gives up when the agent goes silent", async () => {
  const restore = mockFetch(
    () => new Response(new ReadableStream({ start() {} }), { status: 200, headers: { "Content-Type": "text/event-stream" } }),
  );
  try {
    const err = await rejection(streamChatMessage(1, "hola", () => {}, { idleMs: 30 }));
    assert.equal(err.code, "agent_timeout");
  } finally {
    restore();
  }
});

test("streamChatMessage returns the result of a finished turn", async () => {
  const restore = mockFetch(() => sse({ type: "done", content: "Hola!", tool_executions: [] }));
  try {
    const out = await streamChatMessage(1, "hola", () => {});
    assert.equal(out.content, "Hola!");
  } finally {
    restore();
  }
});
