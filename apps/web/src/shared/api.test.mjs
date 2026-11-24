// Shared card logic used by the web and iPhone apps (api.ts is identical in both). Node's built-in
// runner loads the TypeScript file directly (type stripping, Node 24). Made-up alerts and streets.
import assert from "node:assert/strict";
import { test } from "node:test";
import { THREAD_GAP_MS, areaSketch, areaStreets, checkInText, daysLabel, pointText, threadsOf } from "./api.ts";

const NOW = Date.parse("2026-11-01T06:00:00Z");
const at = (minutesAgo) => new Date(NOW - minutesAgo * 60_000).toISOString();

function alert(id, thread, minutesAgo, extra = {}) {
  return {
    id,
    thread_id: thread,
    source: "feed",
    kind: "web_page",
    status: "Severe",
    verification: "official",
    text: `Made-up ${id}.`,
    official_at: at(minutesAgo),
    received_at: at(minutesAgo),
    link: null,
    area: [],
    ...extra,
  };
}

test("alerts group into one card per thread, newest card first, oldest update first", () => {
  const threads = threadsOf(
    [alert("b2", "B", 5), alert("a1", "A", 30), alert("b1", "B", 20), alert("a2", "A", 25)],
    NOW,
  );
  assert.deepEqual(
    threads.map((t) => [t.id, t.alerts.map((a) => a.id)]),
    [
      ["B", ["b1", "b2"]],
      ["A", ["a1", "a2"]],
    ],
  );
  assert.equal(threads[0].latest.id, "b2");
});

test("the source's all-clear closes the card; tone comes from the first alert", () => {
  const drill = { verification: "drill", kind: "drill", source: "drill" };
  const [thread] = threadsOf(
    [alert("d1", "D", 10, drill), alert("d2", "D", 2, { ...drill, status: "Normal" })],
    NOW,
  );
  assert.equal(thread.closed, true);
  assert.equal(thread.live, false);
  assert.equal(thread.tone, "drill");
  const [live] = threadsOf([alert("x", "X", 1, { closed: false })], NOW);
  assert.equal(live.closed, false);
  assert.equal(live.live, true);
  const [byFlag] = threadsOf([alert("y", "Y", 1, { closed: true })], NOW);
  assert.equal(byFlag.closed, true);
});

test("a thread quiet for longer than the gap is no longer live, and never called closed", () => {
  const gapMinutes = THREAD_GAP_MS / 60_000;
  const [quiet] = threadsOf([alert("q", "Q", gapMinutes + 1)], NOW);
  const [recent] = threadsOf([alert("r", "R", gapMinutes - 1)], NOW);
  assert.deepEqual([quiet.live, quiet.closed], [false, false]);
  assert.equal(recent.live, true);
});

test("alerts without a thread stand alone; areas are merged and sorted", () => {
  const threads = threadsOf(
    [
      alert("solo", undefined, 3),
      alert("k1", "K", 9, { area: ["seg_b"] }),
      alert("k2", "K", 8, { area: ["seg_a", "seg_b"] }),
    ],
    NOW,
  );
  assert.deepEqual(threads.map((t) => t.id), ["solo", "K"]);
  assert.deepEqual(threads[1].area, ["seg_a", "seg_b"]);
});

const FEATURES = [
  {
    type: "Feature",
    id: "kirk",
    properties: { id: "kirk", name: "E Kirkwood Ave, 400 block (Grant to Dunn)", levels: {} },
    geometry: { type: "MultiLineString", coordinates: [[[-86.53, 39.166], [-86.529, 39.166]]] },
  },
  {
    type: "Feature",
    id: "third",
    properties: { id: "third", name: "E 3rd St, Indiana Ave to Eagleson Ave", levels: {} },
    geometry: { type: "MultiLineString", coordinates: [[[-86.527, 39.163], [-86.52, 39.163]]] },
  },
];

test("the sketch draws every street, the alert's streets last, inside the box", () => {
  const paths = areaSketch(FEATURES, ["kirk"], 240, 120);
  assert.deepEqual(paths.map((p) => [p.id, p.inArea]), [
    ["third", false],
    ["kirk", true],
  ]);
  for (const p of paths) {
    for (const [x, y] of p.d.replace(/^M/, "").split(/[LM ]+/).filter(Boolean).map((pt) => pt.split(",").map(Number))) {
      assert.ok(x >= 0 && x <= 240 && y >= 0 && y <= 120, `${x},${y} outside the box`);
    }
  }
  assert.deepEqual(areaSketch(FEATURES, [], 240, 120), []);
  assert.deepEqual(areaSketch(FEATURES, ["unknown"], 240, 120), []);
  assert.deepEqual(areaStreets(FEATURES, ["kirk", "third"]), ["E Kirkwood Ave", "E 3rd St"]);
});

test("check-in text says only what the student chose", () => {
  assert.equal(checkInText({ state: "safe", place: null }), "I'm safe");
  assert.equal(checkInText({ state: "sheltering", place: "the library" }), "Sheltering at the library");
});

test("a dot says what, when and how precisely it is placed", () => {
  assert.equal(pointText({ category: "theft", day: "2026-11-03", precision: "block" }), "Theft, Nov 3, 2026: somewhere on this block");
  assert.equal(pointText({ category: "traffic incident", day: "2026-01-31", precision: "segment" }), "Traffic incident, Jan 31, 2026: somewhere on this street stretch");
  assert.equal(pointText({ category: "", day: "2025-12-01", precision: "address" }), "Incident, Dec 1, 2025: at this address");
  assert.deepEqual([30, 90, 365].map(daysLabel), ["30 days", "90 days", "1 year"]);
});

test("the sketch keeps to streets near the alert's area", () => {
  const far = {
    type: "Feature",
    id: "far",
    properties: { id: "far", name: "N Far Rd, 9000 block (A to B)", levels: {} },
    geometry: { type: "MultiLineString", coordinates: [[[-86.4, 39.3], [-86.39, 39.3]]] },
  };
  assert.deepEqual(areaSketch([...FEATURES, far], ["kirk"], 240, 120).map((p) => p.id), ["third", "kirk"]);
});
