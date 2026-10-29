import assert from "node:assert/strict";
import { test } from "node:test";
import { authErrorMessage } from "../src/auth/errors.ts";
import { ApiError } from "../src/api/http.ts";
import { pickActiveId } from "../src/hooks/activeProfile.ts";
import { ACTIVE_KEY, ACTIVE_PROFILE_KEY, CHATS_KEY, DRAFTS_KEY, clearLocalSession } from "../src/session.ts";

const profile = (id: number) => ({ id }) as never;

test("pickActiveId keeps the stored profile only while it exists", () => {
  assert.equal(pickActiveId([profile(1), profile(2)], 2), 2);
  assert.equal(pickActiveId([profile(1), profile(2)], 9), 1);
  assert.equal(pickActiveId([profile(1)], null), 1);
  assert.equal(pickActiveId([], 5), null);
});

test("clearLocalSession removes chats, drafts and the active profile, nothing else", () => {
  const removed: string[] = [];
  clearLocalSession({ removeItem: (k) => void removed.push(k) });
  assert.deepEqual(removed.sort(), [ACTIVE_KEY, ACTIVE_PROFILE_KEY, CHATS_KEY, DRAFTS_KEY].sort());
});

test("clearLocalSession tolerates blocked storage", () => {
  clearLocalSession({
    removeItem: () => {
      throw new Error("blocked");
    },
  });
});

test("authErrorMessage explains the three common failures", () => {
  assert.match(authErrorMessage(new ApiError(409, "conflict", "x"), "register"), /Ya existe/);
  assert.match(authErrorMessage(new ApiError(401, "unauthenticated", "x"), "login"), /incorrectos/);
  assert.match(authErrorMessage(new ApiError(429, "rate_limited", "x"), "login"), /Demasiados/);
  assert.match(authErrorMessage(new ApiError(0, "network_error", "sin red"), "login"), /sin red/);
});
