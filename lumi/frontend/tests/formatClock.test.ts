import test from "node:test";
import assert from "node:assert/strict";
import { formatClock } from "../src/components/AgentThinking/formatClock.ts";

test("sub-minute readouts are plain seconds", () => {
  assert.equal(formatClock(0), "0s");
  assert.equal(formatClock(999), "0s"); // floors to whole seconds
  assert.equal(formatClock(1_000), "1s");
  assert.equal(formatClock(47_000), "47s");
  assert.equal(formatClock(59_999), "59s");
});

test("minute boundaries pad the seconds field", () => {
  assert.equal(formatClock(60_000), "1m 00s");
  assert.equal(formatClock(61_000), "1m 01s");
  assert.equal(formatClock(75_000), "1m 15s");
  assert.equal(formatClock(67_000), "1m 07s");
  assert.equal(formatClock(125_000), "2m 05s");
});

test("negative or absurd input never renders a backwards clock", () => {
  assert.equal(formatClock(-1), "0s");
  assert.equal(formatClock(-60_000), "0s");
  assert.equal(formatClock(3_600_000), "60m 00s");
});
