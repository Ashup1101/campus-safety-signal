// Shapes of the console API (web only: students and parents never reach the console).

import type { Geometry } from "geojson";

export type Level = "quiet" | "elevated" | "high";

export interface ForecastZone {
  zonecode: string;
  expected: number;
  level: Level;
  reason: string;
}

export interface OutlookNight {
  night: string;
  event: string | null;
  campus_expected: number;
}

export interface Forecasts {
  note: string;
  run_id: string | null;
  method: "model" | "rule" | null;
  method_words: string | null;
  tonight: { night: string | null; zones: ForecastZone[] };
  outlook: {
    nights: OutlookNight[];
    zones: { zonecode: string; nights: { night: string; expected: number; level: Level }[] }[];
  };
  scorecard: {
    method: string;
    model: string | null;
    trained_at: string;
    scores: Record<string, Record<string, number> | null>;
    split_rows: Record<string, number>;
  } | null;
}

export interface ZoneShapes {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: { zonecode: string }; geometry: Geometry }[];
}

/** The night the map shows: tonight when the forecast covers it, else its first night. */
export function mapNight(f: Forecasts): { night: string | null; tonight: boolean } {
  if (f.tonight.night) return { night: f.tonight.night, tonight: true };
  return { night: f.outlook.nights[0]?.night ?? null, tonight: false };
}

/** Level and expected calls per zone for one night of the outlook. */
export function zoneLevels(f: Forecasts, night: string | null): Map<string, { level: Level; expected: number }> {
  const found = new Map<string, { level: Level; expected: number }>();
  for (const zone of f.outlook.zones) {
    const hit = zone.nights.find((n) => n.night === night);
    if (hit) found.set(zone.zonecode, { level: hit.level, expected: hit.expected });
  }
  return found;
}

export function nightLabel(night: string): string {
  return new Date(`${night}T12:00:00`).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export interface SourceHealth {
  source: string;
  label: string;
  expected_hours: number;
  last_stored_at: string | null;
  copies: number;
  state: "fresh" | "stale" | "failing" | "never";
  error_kind: string | null;
}

export interface AlertMetrics {
  days: number;
  alerts: number;
  latency: Record<"web" | "ios", { median_s: number | null; p95_s: number | null; deliveries: number }>;
  corrections: number;
  corrections_per_100: number | null;
  duplicates: number;
  duplicates_per_100: number | null;
}

/** "every 36 hours", "every 3 days", "every 90 days", "every year". */
export function cadenceWords(hours: number): string {
  if (hours >= 8760) return "every year";
  if (hours > 48) return `every ${Math.round(hours / 24)} days`;
  return `every ${hours} hours`;
}

export function errorWords(kind: string | null): string | null {
  if (!kind) return null;
  if (kind === "parse_error") return "the newest copy could not be read";
  if (kind.startsWith("http_")) return `the site answered with error ${kind.slice(5)}`;
  return "the newest copy has a problem";
}
