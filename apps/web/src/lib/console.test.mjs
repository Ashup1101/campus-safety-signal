// Console page helpers (web only). Node runs the TypeScript file directly. Made-up numbers.
import assert from "node:assert/strict";
import { test } from "node:test";
import { cadenceWords, errorWords, mapNight, monthlyTotals, outcomeWords, trendZones, zoneLevels } from "./console.ts";

const forecast = (tonight) => ({
  tonight: { night: tonight, zones: [] },
  outlook: {
    nights: [{ night: "2026-10-24" }, { night: "2026-10-25" }],
    zones: [{ zonecode: "LB101", nights: [{ night: "2026-10-25", expected: 3, level: "elevated" }] }],
  },
});

test("the map shows tonight when covered, else the first forecast night", () => {
  assert.deepEqual(mapNight(forecast("2026-10-25")), { night: "2026-10-25", tonight: true });
  assert.deepEqual(mapNight(forecast(null)), { night: "2026-10-24", tonight: false });
  assert.deepEqual([...zoneLevels(forecast(null), "2026-10-25")], [["LB101", { level: "elevated", expected: 3 }]]);
  assert.equal(zoneLevels(forecast(null), "2026-10-24").size, 0);
});

test("cross-check totals sum zones per month and category, newest months first", () => {
  const rows = [
    { month: "2026-09-01", zonecode: "A", category: "theft", iu_count: 1, bpd_count: 2 },
    { month: "2026-09-01", zonecode: "B", category: "theft", iu_count: 2, bpd_count: 5 },
    { month: "2026-10-01", zonecode: "A", category: "assault", iu_count: 0, bpd_count: 1 },
    { month: "2025-01-01", zonecode: "A", category: "theft", iu_count: 9, bpd_count: 9 },
  ];
  assert.deepEqual(monthlyTotals(rows, 2), [
    { month: "2026-10-01", category: "assault", iu: 0, bpd: 1 },
    { month: "2026-09-01", category: "theft", iu: 3, bpd: 7 },
  ]);
});

test("cadence and error kinds read as plain words", () => {
  assert.equal(cadenceWords(36), "every 36 hours");
  assert.equal(cadenceWords(72), "every 3 days");
  assert.equal(cadenceWords(8760), "every year");
  assert.equal(errorWords("parse_error"), "the newest copy could not be read");
  assert.equal(errorWords("http_503"), "the site answered with error 503");
  assert.equal(errorWords(null), null);
});

test("trend zones are busiest first", () => {
  const rows = [
    { week: "w1", zonecode: "B", calls: 1, calls_last_year: 0 },
    { week: "w1", zonecode: "A", calls: 5, calls_last_year: 0 },
    { week: "w2", zonecode: "B", calls: 2, calls_last_year: 0 },
  ];
  assert.deepEqual(trendZones(rows), ["A", "B"]);
});

test("family check-in outcomes read as counts in words", () => {
  assert.equal(outcomeWords({ answered: 3, unreachable: 1 }), "3 answered, 1 phone not reached");
  assert.equal(outcomeWords({}), "none yet");
});
