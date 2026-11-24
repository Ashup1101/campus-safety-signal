// Shared contract with the demo server (apps/server). Identical copy in apps/mobile/src/shared/api.ts
// (pytest drift test). Production swaps the server behind these shapes, never the screens.

export type Role = "student" | "parent" | "console";
export type Sharing = "on" | "paused" | "off";
export type Level = "quiet" | "elevated" | "high";
export type TimeWindow = "late_night" | "event_night";
export type Verification = "official" | "drill" | "reconstruction";
export type Tone = "official" | "normal" | "drill" | "reconstruction";
export type CheckInState = "safe" | "sheltering";
// Fixed list (no free text): the server accepts only these. Same list in demo_server/hub.py.
export const SHELTER_PLACES = [
  "my room",
  "a campus building",
  "a friend's place",
  "the library",
  "off campus",
] as const;
export type ShelterPlace = (typeof SHELTER_PLACES)[number];

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
  thread_id: string; // one card per thread: updates and the all-clear join it
  closed?: boolean; // live messages only: this alert closed its thread (the all-clear)
  area: string[]; // segment ids the official text names; empty = no map
}

// A student's private check-in during a live alert: linked family only, never stored.
export interface CheckIn {
  thread_id: string;
  student_id: string;
  student_name: string;
  state: CheckInState;
  place: ShelterPlace | null;
  at: string;
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
      check_ins?: CheckIn[]; // live threads only: a screen opened mid-alert sees them
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
  | { type: "latency" }
  | { type: "check_in"; check_in: CheckIn }
  | { type: "check_in_cleared"; thread_id: string };

export type ClientMessage =
  | { type: "location"; lat: number; lon: number }
  | { type: "sharing"; state: Sharing }
  | { type: "ack"; alert_id: string; client: "web" | "ios" }
  | { type: "heads_up"; segment_id: string }
  | { type: "check_in"; thread_id: string; state: CheckInState; place?: ShelterPlace };

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

export interface AlertThread {
  id: string;
  alerts: Alert[]; // oldest first
  latest: Alert;
  closed: boolean; // the latest alert is the source's all-clear
  live: boolean; // open and updated within THREAD_GAP_MS (the server's rule); only live cards are red
  tone: Tone; // the first alert's tone; a closed card is calm (never red)
  area: string[];
}

function isAllClear(alert: Alert): boolean {
  return alert.closed === true || alert.status.toLowerCase() === "normal";
}

// Same as THREAD_GAP in demo_server/threads.py: after this long without an update a thread is no
// longer live. That is not an all-clear (only the source can send one), just "no recent updates".
export const THREAD_GAP_MS = 6 * 60 * 60 * 1000;

// One card per incident thread, newest first. Alerts without a thread stand alone.
export function threadsOf(alerts: Alert[], now: number = Date.now()): AlertThread[] {
  const groups = new Map<string, Alert[]>();
  for (const alert of alerts) {
    const key = alert.thread_id ?? alert.id;
    groups.set(key, [...(groups.get(key) ?? []), alert]);
  }
  return [...groups.entries()]
    .map(([id, group]) => {
      const ordered = [...group].sort((a, b) => a.received_at.localeCompare(b.received_at));
      const latest = ordered[ordered.length - 1];
      const closed = isAllClear(latest);
      return {
        id,
        alerts: ordered,
        latest,
        closed,
        live: !closed && now - Date.parse(latest.received_at) <= THREAD_GAP_MS,
        tone: toneOf(ordered[0]),
        area: [...new Set(ordered.flatMap((a) => a.area ?? []))].sort(),
      };
    })
    .sort((a, b) => b.latest.received_at.localeCompare(a.latest.received_at));
}

export function checkInText(checkIn: { state: CheckInState; place: ShelterPlace | null }): string {
  return checkIn.state === "safe" ? "I'm safe" : `Sheltering at ${checkIn.place ?? "a safe place"}`;
}
