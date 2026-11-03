// Shared contract with the demo server (apps/server). Identical copy in apps/mobile/src/shared/api.ts
// (pytest drift test). Production swaps the server behind these shapes, never the screens.

export type Role = "student" | "parent" | "console";
export type Sharing = "on" | "paused" | "off";
export type Level = "quiet" | "elevated" | "high";
export type TimeWindow = "late_night" | "event_night";
export type Verification = "official" | "drill" | "reconstruction";
export type Tone = "official" | "normal" | "drill" | "reconstruction";

export interface Account {
  id: string;
  role: Role;
  name: string;
}

export interface Alert {
  id: string;
  source: string;
  kind: string;
  status: string;
  verification: Verification;
  text: string;
  official_at: string | null;
  received_at: string;
  link: string | null;
}

export interface Clock {
  now: string;
  live: boolean;
  windows: TimeWindow[];
}

export interface Point {
  lat: number;
  lon: number;
  at: string;
}

export interface Student {
  id: string;
  name: string;
  sharing: Sharing;
  location: Point | null;
}

export interface Zone {
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
}

export interface SegmentLevel {
  level: Level;
  reason: string;
}

export interface SegmentFeature {
  type: "Feature";
  id: string;
  properties: { id: string; name: string; levels: Partial<Record<TimeWindow, SegmentLevel>> };
  geometry: { type: "MultiLineString"; coordinates: number[][][] };
}

export interface Segments {
  type: "FeatureCollection";
  features: SegmentFeature[];
  attribution: string;
  clock: Clock;
}

export type ServerMessage =
  | {
      type: "hello";
      account: Account;
      clock: Clock;
      viewers?: string[];
      sharing?: Sharing;
      students?: Student[];
    }
  | { type: "alert"; alert: Alert }
  | { type: "location"; student_id: string; lat: number; lon: number; at: string }
  | { type: "sharing"; student_id: string; state: Sharing }
  | { type: "viewers"; labels: string[] }
  | {
      type: "heads_up";
      student_id: string;
      student_name: string;
      segment_id: string;
      segment_name: string;
    }
  | { type: "clock"; clock: Clock }
  | { type: "latency" };

export type ClientMessage =
  | { type: "location"; lat: number; lon: number }
  | { type: "sharing"; state: Sharing }
  | { type: "ack"; alert_id: string; client: "web" | "ios" }
  | { type: "heads_up"; segment_id: string };

// Red is for live official alerts only; an official "Normal" status is an all-clear.
export function toneOf(alert: Alert): Tone {
  if (alert.verification === "drill") return "drill";
  if (alert.verification === "reconstruction") return "reconstruction";
  return alert.status.toLowerCase() === "normal" ? "normal" : "official";
}

export function levelFor(feature: SegmentFeature, window: TimeWindow): SegmentLevel {
  return feature.properties.levels[window] ?? { level: "quiet", reason: "No data for this window" };
}

export function clockTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
}
