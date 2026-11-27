// A background session (v15) as pure functions, so the rules are tested without a phone: where the
// phone is never leaves it; the result is only events (heads-up street, arrived home, ended).
export type SessionKind = "home" | "heads_up";
export type EndReason = "arrived" | "timeout" | "low_battery" | "turned_off";
export interface Point {
  lat: number;
  lon: number;
}
export interface Home extends Point {
  radius_m: number;
}
export interface SessionState {
  id: string;
  kind: SessionKind;
  startedAt: number;
  home: Home | null;
  headsUpSent: string[];
  ended: EndReason | null;
}
export type SessionEvent =
  | { kind: "heads_up"; segment_id: string }
  | { kind: "arrived_home" }
  | { kind: "ended"; reason: EndReason };

export const MAX_MS = 2 * 60 * 60 * 1000; // a session never runs longer than 2 hours
export const LOW_BATTERY = 0.2; // below 20 % the session stops to save the phone

export function start(id: string, kind: SessionKind, now: number, home: Home | null = null): SessionState {
  return { id, kind, startedAt: now, home, headsUpSent: [], ended: null };
}

function meters(a: Point, b: Point): number {
  const r = 6371000;
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

function end(state: SessionState, reason: EndReason, events: SessionEvent[]): { state: SessionState; events: SessionEvent[] } {
  return { state: { ...state, ended: reason }, events: [...events, { kind: "ended", reason }] };
}

/** One location update. busyAt says which busier street (if any) the point is on. battery: 0-1, or
 * -1 when unknown. */
export function onLocation(
  state: SessionState,
  point: Point,
  now: number,
  battery: number,
  busyAt: (point: Point) => string | null,
): { state: SessionState; events: SessionEvent[] } {
  if (state.ended) return { state, events: [] };
  if (now - state.startedAt >= MAX_MS) return end(state, "timeout", []);
  if (battery >= 0 && battery < LOW_BATTERY) return end(state, "low_battery", []);
  if (state.kind === "home" && state.home && meters(point, state.home) <= state.home.radius_m) {
    return end(state, "arrived", [{ kind: "arrived_home" }]);
  }
  const segment = busyAt(point);
  if (segment && !state.headsUpSent.includes(segment)) {
    return {
      state: { ...state, headsUpSent: [...state.headsUpSent, segment] },
      events: [{ kind: "heads_up", segment_id: segment }],
    };
  }
  return { state, events: [] };
}

export function stop(state: SessionState): { state: SessionState; events: SessionEvent[] } {
  return state.ended ? { state, events: [] } : end(state, "turned_off", []);
}
