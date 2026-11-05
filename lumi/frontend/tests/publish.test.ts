import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { NETWORK_LIMITS, newIdempotencyKey, previewPublish, publishNow, remainingChars } from "../src/api/publish.ts";
import { blockedReason, cardsFromDrafts, editCard, manualCard, withKey } from "../src/components/Publish/draftState.ts";
import { publishErrorMessage } from "../src/components/Publish/errors.ts";
import { ApiError } from "../src/api/http.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function capture() {
  const calls: { headers: Record<string, string>; body: Record<string, unknown> }[] = [];
  globalThis.fetch = (async (_u: string, init: RequestInit) => {
    calls.push({
      headers: init.headers as Record<string, string>,
      body: JSON.parse(String(init.body)),
    });
    return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
  }) as typeof fetch;
  return calls;
}

test("remainingChars counts characters, not UTF-16 units", () => {
  assert.equal(remainingChars("x", "hola"), NETWORK_LIMITS.x - 4);
  assert.equal(remainingChars("x", "😀😀"), NETWORK_LIMITS.x - 2);
  assert.equal(remainingChars("x", "a".repeat(281)), -1);
});

test("a preview is a dry run with no confirmation and no idempotency key", async () => {
  const calls = capture();
  await previewPublish({ profileId: 3, platform: "x", text: "hi" });
  assert.equal(calls[0].body.dry_run, true);
  assert.equal(calls[0].body.confirm, false);
  assert.equal(calls[0].headers["Idempotency-Key"], undefined);
});

test("a real publish confirms and sends the idempotency key", async () => {
  const calls = capture();
  await publishNow({ profileId: 3, platform: "linkedin", text: "hi", attemptId: 9 }, "key-1");
  assert.equal(calls[0].body.dry_run, false);
  assert.equal(calls[0].body.confirm, true);
  assert.equal(calls[0].body.attempt_id, 9);
  assert.equal(calls[0].headers["Idempotency-Key"], "key-1");
});

test("idempotency keys are unique", () => {
  assert.notEqual(newIdempotencyKey(), newIdempotencyKey());
});

test("editing a card drops its preview and its key; retries keep the key", () => {
  let card = withKey(manualCard("x"));
  const key = card.idempotencyKey;
  assert.ok(key);
  assert.equal(withKey(card).idempotencyKey, key);
  card = { ...card, preview: { status: "dry_run" } as never };
  card = editCard(card, "new text");
  assert.equal(card.idempotencyKey, null);
  assert.equal(card.preview, null);
  assert.equal(card.edited, true);
});

test("blockedReason covers network, empty text, length and already published", () => {
  assert.match(blockedReason({ ...manualCard("instagram"), text: "a" }) ?? "", /isn.t available/);
  assert.match(blockedReason(manualCard("x")) ?? "", /Write the text/);
  assert.match(blockedReason({ ...manualCard("x"), text: "a".repeat(281) }) ?? "", /280/);
  assert.equal(blockedReason({ ...manualCard("x"), text: "ok" }), null);
  assert.match(
    blockedReason({ ...manualCard("x"), text: "ok", published: { status: "published" } as never }) ?? "",
    /Already published/,
  );
});

test("cardsFromDrafts splits good drafts from failures", () => {
  const { cards, failures } = cardsFromDrafts([
    { ok: true, platform: "x", output: "t", attempt_id: 4, evaluation: null, warnings: [] } as never,
    { ok: false, platform: "linkedin", error: { message: "boom" } } as never,
  ]);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].attemptId, 4);
  assert.deepEqual(failures, [{ platform: "linkedin", message: "boom" }]);
});

test("publishErrorMessage sends an unconnected account to Settings", () => {
  assert.match(publishErrorMessage(new ApiError(409, "publish.not_connected", "x")), /Settings/);
  assert.match(publishErrorMessage(new ApiError(409, "conflict", "x")), /key/);
});
