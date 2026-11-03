// On-phone geometry: the heads-up and "Share until I'm home" are computed here, never on the server.
import { levelFor, type SegmentFeature, type TimeWindow } from "./shared/api";

export interface LatLon {
  lat: number;
  lon: number;
}

// Demo home point. It stays on the phone; the server never learns it.
export const HOME: LatLon = { lat: 39.16862, lon: -86.51745 };
export const HOME_RADIUS_M = 60;
export const NEAR_SEGMENT_M = 25;

const METERS_PER_DEGREE = 111_320;

function toXY(point: LatLon, origin: LatLon): [number, number] {
  return [
    (point.lon - origin.lon) * METERS_PER_DEGREE * Math.cos((origin.lat * Math.PI) / 180),
    (point.lat - origin.lat) * METERS_PER_DEGREE,
  ];
}

export function distance(a: LatLon, b: LatLon): number {
  const [x, y] = toXY(b, a);
  return Math.hypot(x, y);
}

function toSegment(point: LatLon, a: number[], b: number[]): number {
  const [ax, ay] = toXY({ lon: a[0], lat: a[1] }, point);
  const [bx, by] = toXY({ lon: b[0], lat: b[1] }, point);
  const dx = bx - ax;
  const dy = by - ay;
  const length = dx * dx + dy * dy;
  const t = length === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

export function distanceToFeature(point: LatLon, feature: SegmentFeature): number {
  let best = Infinity;
  for (const line of feature.geometry.coordinates) {
    for (let i = 1; i < line.length; i++) best = Math.min(best, toSegment(point, line[i - 1], line[i]));
  }
  return best;
}

// The High segment the student is on during one of its active windows, if any.
export function highSegmentHere(
  point: LatLon,
  features: SegmentFeature[],
  windows: TimeWindow[],
): { feature: SegmentFeature; window: TimeWindow } | null {
  for (const window of windows) {
    for (const feature of features) {
      if (levelFor(feature, window).level === "high" && distanceToFeature(point, feature) <= NEAR_SEGMENT_M) {
        return { feature, window };
      }
    }
  }
  return null;
}
