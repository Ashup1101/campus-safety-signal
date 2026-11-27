// Session rules without a phone (node --test; Node 24 runs the .ts module directly).
import assert from "node:assert/strict";
import { test } from "node:test";
import { LOW_BATTERY, MAX_MS, onLocation, start, stop } from "./session.ts";

const HOME = { lat: 39.1653, lon: -86.5264, radius_m: 150 };
const FAR = { lat: 39.1700, lon: -86.5200 };
const KIRKWOOD = { lat: 39.1666, lon: -86.5300 };
const busyAt = (p) => (p === KIRKWOOD ? "kirkwood_400" : null);

test("arrival ends a home session once, with the arrived event", () => {
  let s = start("s1", "home", 0, HOME);
  let r = onLocation(s, FAR, 1000, 0.9, busyAt);
  assert.deepEqual(r.events, []);
  r = onLocation(r.state, HOME, 2000, 0.9, busyAt);
  assert.deepEqual(r.events, [{ kind: "arrived_home" }, { kind: "ended", reason: "arrived" }]);
  assert.deepEqual(onLocation(r.state, HOME, 3000, 0.9, busyAt).events, []);
});

test("a busier street gives one heads-up per street per session", () => {
  let r = onLocation(start("s2", "heads_up", 0), KIRKWOOD, 1000, 0.9, busyAt);
  assert.deepEqual(r.events, [{ kind: "heads_up", segment_id: "kirkwood_400" }]);
  assert.deepEqual(onLocation(r.state, KIRKWOOD, 2000, 0.9, busyAt).events, []);
});

test("two hours, low battery and the off switch end the session", () => {
  assert.deepEqual(onLocation(start("a", "home", 0, HOME), FAR, MAX_MS, 0.9, busyAt).events, [
    { kind: "ended", reason: "timeout" },
  ]);
  assert.deepEqual(onLocation(start("b", "home", 0, HOME), FAR, 10, LOW_BATTERY - 0.01, busyAt).events, [
    { kind: "ended", reason: "low_battery" },
  ]);
  assert.deepEqual(onLocation(start("c", "home", 0, HOME), FAR, 10, -1, busyAt).events, []);
  const off = stop(start("d", "home", 0, HOME));
  assert.deepEqual(off.events, [{ kind: "ended", reason: "turned_off" }]);
  assert.deepEqual(stop(off.state).events, []);
});

test("events never carry coordinates", () => {
  const r = onLocation(start("e", "home", 0, HOME), HOME, 10, 0.9, busyAt);
  for (const event of r.events) assert.ok(!("lat" in event) && !("lon" in event));
});
