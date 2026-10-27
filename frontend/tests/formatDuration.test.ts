import { test } from "node:test";
import assert from "node:assert/strict";
import { formatDuration } from "../src/simulation/formatDuration.ts";

test("sub-minute durations", () => {
  assert.equal(formatDuration(0), "0 seconds");
  assert.equal(formatDuration(-500), "0 seconds");
  assert.equal(formatDuration(499), "0 seconds");
  assert.equal(formatDuration(999), "1 second");
  assert.equal(formatDuration(1000), "1 second");
  assert.equal(formatDuration(4000), "4 seconds");
  assert.equal(formatDuration(4400), "4 seconds");
  assert.equal(formatDuration(59499), "59 seconds");
});

test("minute boundaries", () => {
  assert.equal(formatDuration(59500), "1 minute");
  assert.equal(formatDuration(60000), "1 minute");
  assert.equal(formatDuration(61000), "1 minute 1 second");
  assert.equal(formatDuration(90000), "1 minute 30 seconds");
  assert.equal(formatDuration(120000), "2 minutes");
  assert.equal(formatDuration(121000), "2 minutes 1 second");
  assert.equal(formatDuration(3599000), "59 minutes 59 seconds");
});

test("hour boundaries", () => {
  assert.equal(formatDuration(3600000), "60 minutes");
  assert.equal(formatDuration(3661000), "61 minutes 1 second");
});
