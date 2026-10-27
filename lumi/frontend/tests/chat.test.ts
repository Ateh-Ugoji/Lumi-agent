import assert from "node:assert/strict";
import { test } from "node:test";
import { analyticsFrom, connectLinksFrom, parseSseChunk } from "../src/api/chat.ts";

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
