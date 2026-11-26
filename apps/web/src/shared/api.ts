// Shared contract with the demo server (apps/server). Identical copy in apps/mobile/src/shared/api.ts
// (pytest drift test). Production swaps the server behind these shapes, never the screens.

export type Role = "student" | "parent" | "console";
export type Sharing = "on" | "paused" | "off";
export type Level = "quiet" | "elevated" | "high";
// tonight: the expected level for the current night (T1 or the simple rule), present only when a
// forecast covers it.
export type TimeWindow = "late_night" | "event_night" | "tonight";
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

// Map dots: recent placed incidents with category, day and precision only (never text or names).
export type Precision = "segment" | "address" | "block";
export const RECENT_DAYS = [30, 90, 365] as const;

export interface IncidentPoint {
  type: "Feature";
  properties: { category: string; day: string; precision: Precision };
  geometry: { type: "Point"; coordinates: [number, number] };
}

export interface IncidentPoints {
  type: "FeatureCollection";
  days: number;
  attribution: string;
  features: IncidentPoint[];
}

const PLACED: Record<Precision, string> = {
  address: "at this address",
  block: "somewhere on this block",
  segment: "somewhere on this street stretch",
};

export function daysLabel(days: number): string {
  return days === 365 ? "1 year" : `${days} days`;
}

// "Theft, Nov 3, 2026: somewhere on this block". The day is a calendar day, never shifted.
export function pointText(p: IncidentPoint["properties"]): string {
  const [y, m, d] = p.day.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
  const kind = p.category || "incident";
  return `${kind[0].toUpperCase()}${kind.slice(1)}, ${day}: ${PLACED[p.precision]}`;
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
      signing?: { key_id: string; secret: string; label: string }; // a student, once per key
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
  | { type: "check_in_cleared"; thread_id: string }
  | { type: "band_request"; request_id: string; from: string }
  | { type: "ok_request"; request_id: string; from: string }
  | { type: "ok_result"; request_id: string; student_id: string; state: OkState }
  | { type: "arrived_home"; student_id: string; student_name: string; at: string }
  | { type: "notes_changed"; thread_id: string }
  | {
      type: "band_result";
      request_id: string;
      student_id: string;
      state: BandState;
      band?: Band;
      answered_at?: string;
    };

export type ClientMessage =
  | { type: "location"; lat: number; lon: number }
  | { type: "sharing"; state: Sharing }
  | { type: "ack"; alert_id: string; client: "web" | "ios" }
  | { type: "heads_up"; segment_id: string }
  | { type: "check_in"; thread_id: string; state: CheckInState; place?: ShelterPlace }
  | { type: "band_answer"; request_id: string; band: Band; answered_at: string; signature: string }
  | { type: "band_answer"; request_id: string; declined: true }
  | { type: "ok_answer"; request_id: string; answer: "ok" | "call_me" | "off" }
  | { type: "arrived_home" };

// Red is for live official alerts only; an official "Normal" status is an all-clear.
export function toneOf(alert: Alert): Tone {
  if (alert.verification === "drill") return "drill";
  if (alert.verification === "reconstruction") return "reconstruction";
  return alert.status.toLowerCase() === "normal" ? "normal" : "official";
}

export function levelFor(feature: SegmentFeature, window: TimeWindow): SegmentLevel {
  return feature.properties.levels[window] ?? { level: "quiet", reason: "No data for this window" };
}

// The website is the IUPD console only; the app never opens it (the server also refuses).
export function canOpenConsole(role: Role): boolean {
  return role === "console";
}

export function hasTonight(segments: Pick<Segments, "features"> | null): boolean {
  return (segments?.features ?? []).some((f) => f.properties.levels.tonight !== undefined);
}

// Which method made tonight's levels, from the reason the server writes ("..., simple rule)").
/** Windows a heads-up checks right now: the clock's (late night, event night), plus Tonight's
 * forecast during late night when one covers today. */
export function activeWindows(clockWindows: string[], segments: Pick<Segments, "features"> | null): TimeWindow[] {
  const found = clockWindows.filter((w): w is TimeWindow => w === "late_night" || w === "event_night");
  return found.includes("late_night") && hasTonight(segments) ? [...found, "tonight"] : found;
}

export function tonightMethod(segments: Pick<Segments, "features"> | null): string | null {
  const reason = (segments?.features ?? []).find((f) => f.properties.levels.tonight)?.properties.levels.tonight?.reason;
  if (!reason) return null;
  return reason.includes("forecast model") ? "Forecast model" : "Simple rule";
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

export interface SketchPath {
  id: string;
  d: string; // SVG path in a width x height box
  inArea: boolean;
}

// A tiny street sketch for an alert card: nearby segments faint, the alert's area drawn last.
// No tiles, so it costs nothing per card. Empty when the alert names no mapped street.
const NEAR_DEG = 0.006; // about 600 m around the alert's streets

export function areaSketch(allFeatures: SegmentFeature[], area: string[], width: number, height: number, pad = 10): SketchPath[] {
  const own = allFeatures.filter((f) => area.includes(f.id)).flatMap((f) => f.geometry.coordinates.flat());
  if (own.length === 0) return [];
  const [x0, x1] = [Math.min(...own.map((p) => p[0])) - NEAR_DEG, Math.max(...own.map((p) => p[0])) + NEAR_DEG];
  const [y0, y1] = [Math.min(...own.map((p) => p[1])) - NEAR_DEG, Math.max(...own.map((p) => p[1])) + NEAR_DEG];
  const features = allFeatures.filter(
    (f) =>
      area.includes(f.id) ||
      f.geometry.coordinates.flat().some(([x, y]) => x >= x0 && x <= x1 && y >= y0 && y <= y1),
  );
  const points = features.flatMap((f) => f.geometry.coordinates.flat());
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const kx = Math.cos((((minY + maxY) / 2) * Math.PI) / 180); // keep streets at their real angles
  const spanX = (maxX - minX) * kx || 1e-9;
  const spanY = maxY - minY || 1e-9;
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const ox = (width - spanX * scale) / 2;
  const oy = (height - spanY * scale) / 2;
  const xy = ([lon, lat]: number[]) =>
    `${(ox + (lon - minX) * kx * scale).toFixed(1)},${(oy + (maxY - lat) * scale).toFixed(1)}`;
  return features
    .map((f) => ({
      id: f.id,
      inArea: area.includes(f.id),
      d: f.geometry.coordinates.map((line) => `M${line.map(xy).join("L")}`).join(" "),
    }))
    .sort((a, b) => Number(a.inArea) - Number(b.inArea));
}

// "E Kirkwood Ave" from "E Kirkwood Ave, 400 block (Grant to Dunn)": the street names in an area.
export function areaStreets(features: SegmentFeature[], area: string[]): string[] {
  const names = features.filter((f) => area.includes(f.id)).map((f) => f.properties.name.split(",")[0]);
  return [...new Set(names)];
}

// What the scoreboard shows: the busiest street in the window, live alerts, minutes since the last.
const RANK: Record<Level, number> = { quiet: 0, elevated: 1, high: 2 };

function minutesSince(iso: string | undefined, now: number): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((now - Date.parse(iso)) / 60_000));
}

export interface Tonight {
  high: number;
  elevated: number;
  top: { name: string; level: Level; reason: string } | null;
  live: number;
  lastMinutes: number | null;
}

export function tonightOf(segments: Segments | null, window: TimeWindow, threads: AlertThread[], now: number): Tonight {
  const levels = (segments?.features ?? []).map((f) => ({ f, l: levelFor(f, window) }));
  const top = [...levels].sort((a, b) => RANK[b.l.level] - RANK[a.l.level])[0];
  return {
    high: levels.filter((x) => x.l.level === "high").length,
    elevated: levels.filter((x) => x.l.level === "elevated").length,
    top: top && top.l.level !== "quiet" ? { name: top.f.properties.name.split(" (")[0], level: top.l.level, reason: top.l.reason } : null,
    live: threads.filter((t) => t.live).length,
    lastMinutes: minutesSince(threads[0]?.latest.received_at, now),
  };
}

// Parent reassurance (v8): the phone turns one location reading into a coarse band; only the band
// word ever leaves the phone, never the point.
export type Band = "inside" | "nearby" | "away";
export type BandState = "answered" | "unverified" | "declined" | "unreachable";
export type OkState = "ok" | "call_me" | "off" | "no_answer";

export interface Area {
  lat: number;
  lon: number;
  radius_m: number;
}

// IU Bloomington's main campus as a circle around the Old Crescent and the stadium area (approximate,
// public map); "nearby" counts anywhere on campus.
export const CAMPUS: Area = { lat: 39.1702, lon: -86.5164, radius_m: 1400 };

export function metersBetween(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

/** inside: within the home radius; nearby: within twice the radius or on campus; away: otherwise. */
export function bandOf(here: { lat: number; lon: number }, home: Area, campus: Area = CAMPUS): Band {
  const fromHome = metersBetween(here, home);
  if (fromHome <= home.radius_m) return "inside";
  if (fromHome <= 2 * home.radius_m || metersBetween(here, campus) <= campus.radius_m) return "nearby";
  return "away";
}

/** "Arrived home": on an event night, the reading is inside the student's home area. */
export function reachedHomeOnEventNight(
  here: { lat: number; lon: number },
  home: Area | null,
  windows: string[],
): boolean {
  return !!home && windows.includes("event_night") && bandOf(here, home) === "inside";
}

export const BAND_WORDS: Record<Band, string> = {
  inside: "in their home area",
  nearby: "near home or on campus",
  away: "away from home and campus",
};

// HMAC-SHA256 in plain TypeScript (the phone has no crypto module in Expo Go); checked against
// Node's crypto in the shared tests. Inputs are small (one band answer), so speed does not matter.
const K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
  0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
  0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
  0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
  0xc67178f2,
];

function sha256(bytes: Uint8Array): Uint8Array {
  const length = bytes.length;
  const padded = new Uint8Array(Math.ceil((length + 9) / 64) * 64);
  padded.set(bytes);
  padded[length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor((length * 8) / 2 ** 32));
  view.setUint32(padded.length - 4, (length * 8) >>> 0);
  const h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  const w = new Array<number>(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      [hh, g, f, e, d, c, b, a] = [g, f, e, (d + t1) | 0, c, b, a, (t1 + t2) | 0];
    }
    h[0] = (h[0] + a) | 0;
    h[1] = (h[1] + b) | 0;
    h[2] = (h[2] + c) | 0;
    h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0;
    h[5] = (h[5] + f) | 0;
    h[6] = (h[6] + g) | 0;
    h[7] = (h[7] + hh) | 0;
  }
  const out = new Uint8Array(32);
  const outView = new DataView(out.buffer);
  h.forEach((x, i) => outView.setUint32(i * 4, x >>> 0));
  return out;
}

function utf8(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function fromHex(hex: string): Uint8Array {
  return new Uint8Array((hex.match(/../g) ?? []).map((pair) => parseInt(pair, 16)));
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function hmacSha256Hex(secretHex: string, message: string): string {
  let key = fromHex(secretHex);
  if (key.length > 64) key = sha256(key);
  const block = new Uint8Array(64);
  block.set(key);
  const inner = new Uint8Array(64 + utf8(message).length);
  const outer = new Uint8Array(64 + 32);
  for (let i = 0; i < 64; i++) {
    inner[i] = block[i] ^ 0x36;
    outer[i] = block[i] ^ 0x5c;
  }
  inner.set(utf8(message), 64);
  outer.set(sha256(inner), 64);
  return toHex(sha256(outer));
}

/** The signature the server checks: HMAC over "request_id|band|answered_at" (demo signing). */
export function signBand(secretHex: string, requestId: string, band: Band, answeredAt: string): string {
  return hmacSha256Hex(secretHex, `${requestId}|${band}|${answeredAt}`);
}

/** What a parent reads after a check-in. Only a verified answer names a band. */
export function bandResultText(
  name: string,
  result: { state: BandState; band?: Band; answered_at?: string },
  now: number = Date.now(),
): string {
  switch (result.state) {
    case "answered": {
      const minutes = result.answered_at ? Math.max(0, Math.round((now - Date.parse(result.answered_at)) / 60_000)) : 0;
      const when = minutes === 0 ? "just now" : `${minutes} min ago`;
      return `${name} is ${result.band ? BAND_WORDS[result.band] : "checked in"} (${when}).`;
    }
    case "unverified":
      return `Couldn't verify the answer from ${name}'s phone.`;
    case "declined":
      return `${name} hasn't turned on check-ins.`;
    case "unreachable":
      return `Couldn't reach ${name}'s phone.`;
  }
}

export function okResultText(name: string, state: OkState): string {
  switch (state) {
    case "ok":
      return `${name} says they're OK.`;
    case "call_me":
      return `${name} asked you to call.`;
    case "off":
      return `${name} has turned off "Are you OK?" nudges.`;
    case "no_answer":
      return `No answer yet from ${name}.`;
  }
}

// Community notes (v9): only confirmed tags, never who posted; the reader's own note in any state.
export interface ThreadNotes {
  label: string;
  notes: { tag: string; people: number; texts: string[]; by: string }[];
  mine: { tag: string; text: string | null; state: "held" | "pending" | "visible" | "hidden" } | null;
  enabled: boolean;
}
