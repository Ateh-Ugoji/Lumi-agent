import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { selectHandle } from "../src/api/handles.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("selectHandle sends the handle and nothing the server could store as someone's photo or numbers", async () => {
  const seen: { url: string; body: unknown; method: string }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    seen.push({ url: String(url), body: JSON.parse(String(init.body)), method: String(init.method) });
    return new Response(JSON.stringify({ remembered: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  await selectHandle({
    handle: "karpathy",
    display_name: "Andrej",
    avatar_url: "https://img.example/a.png",
    followers: 1200,
    source: "live",
  });
  assert.equal(seen.length, 1);
  assert.equal(seen[0].method, "POST");
  assert.equal(new URL(seen[0].url).pathname.endsWith("/handles/select"), true);
  assert.deepEqual(seen[0].body, { handle: "karpathy" });
});

test("selectHandle never throws when the server is down", async () => {
  globalThis.fetch = (async () => {
    throw new Error("offline");
  }) as typeof fetch;
  await selectHandle({ handle: "karpathy" });
});
