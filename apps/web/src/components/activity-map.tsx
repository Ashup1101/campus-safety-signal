"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { layers, namedFlavor } from "@protomaps/basemaps";
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibre, StyleSpecification } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { SERVER, color, tokens } from "@/lib/client";
import {
  levelFor,
  pointText,
  type IncidentPoints,
  type Segments,
  type Student,
  type TimeWindow,
  type Zone,
} from "@/shared/api";

const CENTER: [number, number] = [-86.5245, 39.1678];
const BOUNDS: [number, number, number, number] = [-86.548, 39.15, -86.495, 39.188];

// The basemap steps back into the palette (cream paper by day, warm ink at night) so the activity
// lines carry the color, like a Strava heat map over a quiet map.
const CREAM = {
  background: "#efe8da",
  earth: "#f3ede1",
  water: "#cdd8d6",
  buildings: "#e6dece",
  park_a: "#e2e3cf",
  park_b: "#dadcc4",
  wood_a: "#dfe0ca",
  wood_b: "#d7d9c1",
};
const INK = {
  background: "#160f11",
  earth: "#1c1416",
  water: "#141c22",
  buildings: "#271d1f",
  park_a: "#1d211c",
  park_b: "#1b1f1a",
  wood_a: "#1c201b",
  wood_b: "#1a1e19",
};

function baseStyle(dark: boolean): StyleSpecification {
  const flavor = dark ? "dark" : "light";
  return {
    version: 8,
    glyphs: `${SERVER}/tiles/fonts/{fontstack}/{range}.pbf`,
    sprite: `${SERVER}/tiles/sprites/v4/${flavor}`,
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${SERVER}/tiles/bloomington.pmtiles`,
        attribution:
          '© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="https://protomaps.com">Protomaps</a>',
      },
    },
    layers: layers("protomaps", { ...namedFlavor(flavor), ...(dark ? INK : CREAM) }, { lang: "en" }),
  };
}

function circle(zone: Zone): number[][] {
  const points = [];
  for (let i = 0; i <= 48; i++) {
    const angle = (i / 48) * 2 * Math.PI;
    const dLat = (zone.radius_m / 111_320) * Math.sin(angle);
    const dLon = (zone.radius_m / (111_320 * Math.cos((zone.lat * Math.PI) / 180))) * Math.cos(angle);
    points.push([zone.lon + dLon, zone.lat + dLat]);
  }
  return points;
}

function segmentData(segments: Segments | null, window: TimeWindow) {
  return {
    type: "FeatureCollection" as const,
    features: (segments?.features ?? []).map((f) => {
      const { level, reason } = levelFor(f, window);
      return {
        ...f,
        properties: { name: f.properties.name, level, reason, label: tokens.activity[level].label },
      };
    }),
  };
}

// Dots: filled = at an address; ring = somewhere on a block or street stretch (less precise).
const DOT = { light: "#3a2326", dark: "#f3ede1" };

function pointData(points: IncidentPoints | null) {
  return {
    type: "FeatureCollection" as const,
    features: (points?.features ?? []).map((p) => ({
      ...p,
      properties: { text: pointText(p.properties), exact: p.properties.precision === "address" },
    })),
  };
}

function studentData(students: Student[]) {
  return {
    type: "FeatureCollection" as const,
    features: students
      .filter((s) => s.sharing === "on" && s.location)
      .map((s) => ({
        type: "Feature" as const,
        properties: { name: s.name },
        geometry: { type: "Point" as const, coordinates: [s.location!.lon, s.location!.lat] },
      })),
  };
}

function zoneData(zones: Zone[]) {
  return {
    type: "FeatureCollection" as const,
    features: zones.map((z) => ({
      type: "Feature" as const,
      properties: { name: z.name },
      geometry: { type: "Polygon" as const, coordinates: [circle(z)] },
    })),
  };
}

export function ActivityMap({
  segments,
  window,
  points = null,
  students = [],
  zones = [],
  dark,
}: {
  segments: Segments | null;
  window: TimeWindow;
  points?: IncidentPoints | null;
  students?: Student[];
  zones?: Zone[];
  dark: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibre | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let instance: MapLibre | null = null;
    (async () => {
      const maplibre = await import("maplibre-gl");
      maplibre.setWorkerUrl("/maplibre-worker"); // see app/maplibre-worker/route.ts
      const { Protocol } = await import("pmtiles");
      if (cancelled || !container.current) return;
      const protocol = new Protocol();
      maplibre.addProtocol("pmtiles", protocol.tile);
      const created = new maplibre.Map({
        container: container.current,
        style: baseStyle(dark),
        center: CENTER,
        zoom: 14.6,
        maxBounds: BOUNDS,
        attributionControl: { compact: true },
      });
      instance = created;
      created.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
      created.on("load", () => {
        const m = created;
        const level = (key: "light" | "dark"): ExpressionSpecification => [
          "match",
          ["get", "level"],
          "high",
          tokens.activity.high[key],
          "elevated",
          tokens.activity.elevated[key],
          tokens.activity.quiet[key],
        ];
        const tone = dark ? "dark" : "light";
        m.addSource("zones", { type: "geojson", data: zoneData([]) });
        m.addSource("segments", { type: "geojson", data: segmentData(null, "late_night") });
        m.addSource("points", { type: "geojson", data: pointData(null) });
        m.addSource("students", { type: "geojson", data: studentData([]) });
        m.addLayer({
          id: "zones-fill",
          type: "fill",
          source: "zones",
          paint: { "fill-color": color(tokens.zone, dark), "fill-opacity": 0.07 },
        });
        m.addLayer({
          id: "zones-line",
          type: "line",
          source: "zones",
          paint: { "line-color": color(tokens.zone, dark), "line-width": 1.5, "line-dasharray": [2, 2] },
        });
        m.addLayer({
          id: "segments-casing",
          type: "line",
          source: "segments",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": dark ? "#160f11" : "#fbf8f1",
            "line-width": [
              "match",
              ["get", "level"],
              "high",
              tokens.activity.high.width + 4,
              "elevated",
              tokens.activity.elevated.width + 3,
              tokens.activity.quiet.width + 2,
            ],
          },
        });
        m.addLayer({
          id: "segments-line",
          type: "line",
          source: "segments",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": level(tone),
            "line-width": [
              "match",
              ["get", "level"],
              "high",
              tokens.activity.high.width,
              "elevated",
              tokens.activity.elevated.width,
              tokens.activity.quiet.width,
            ],
            "line-opacity": 1,
          },
        });
        m.addLayer({
          id: "segments-label",
          type: "symbol",
          source: "segments",
          filter: ["==", ["get", "level"], "high"],
          layout: {
            "symbol-placement": "line",
            "text-field": ["get", "label"],
            "text-font": ["Noto Sans Medium"],
            "text-size": 12,
            "text-offset": [0, -1.1],
          },
          paint: {
            "text-color": tokens.activity.high[tone],
            "text-halo-color": dark ? "#111827" : "#ffffff",
            "text-halo-width": 1.6,
          },
        });
        m.addLayer({
          id: "points",
          type: "circle",
          source: "points",
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 2.5, 16, 5],
            "circle-color": ["case", ["get", "exact"], DOT[tone], "rgba(0,0,0,0)"],
            "circle-stroke-color": DOT[tone],
            "circle-stroke-width": 1.5,
          },
        });
        m.addLayer({
          id: "students",
          type: "circle",
          source: "students",
          paint: {
            "circle-radius": 8,
            "circle-color": color(tokens.student, dark),
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 3,
          },
        });
        m.addLayer({
          id: "students-label",
          type: "symbol",
          source: "students",
          layout: {
            "text-field": ["get", "name"],
            "text-font": ["Noto Sans Medium"],
            "text-size": 12,
            "text-offset": [0, 1.4],
          },
          paint: {
            "text-color": color(tokens.student, dark),
            "text-halo-color": dark ? "#111827" : "#ffffff",
            "text-halo-width": 1.6,
          },
        });
        m.on("click", "segments-line", (event) => {
          const props = event.features?.[0]?.properties;
          if (!props) return;
          const popup = document.createElement("div");
          const title = document.createElement("strong");
          title.textContent = String(props.name);
          const body = document.createElement("div");
          body.textContent = `${props.label}: ${props.reason}`;
          popup.append(title, body);
          new maplibre.Popup({ closeButton: false }).setLngLat(event.lngLat).setDOMContent(popup).addTo(m);
        });
        m.on("click", "points", (event) => {
          const text = event.features?.[0]?.properties?.text;
          if (!text) return;
          const popup = document.createElement("div");
          popup.textContent = String(text);
          new maplibre.Popup({ closeButton: false }).setLngLat(event.lngLat).setDOMContent(popup).addTo(m);
        });
        for (const layer of ["segments-line", "points"]) {
          m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
          m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
        }
        map.current = m;
        setReady(true);
      });
    })();
    return () => {
      cancelled = true;
      map.current = null;
      setReady(false);
      instance?.remove();
    };
  }, [dark]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource("segments") as GeoJSONSource | undefined)?.setData(segmentData(segments, window));
  }, [ready, segments, window]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource("points") as GeoJSONSource | undefined)?.setData(pointData(points));
  }, [ready, points]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource("students") as GeoJSONSource | undefined)?.setData(studentData(students));
  }, [ready, students]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource("zones") as GeoJSONSource | undefined)?.setData(zoneData(zones));
  }, [ready, zones]);

  return <div ref={container} className="h-full min-h-[420px] w-full overflow-hidden rounded-xl" />;
}

export function Legend({ dark, window, dots = false }: { dark: boolean; window: TimeWindow; dots?: boolean }) {
  const levels = ["quiet", "elevated", "high"] as const;
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      <span>{tokens.windows[window]}:</span>
      {levels.map((level) => (
        <span key={level} className="inline-flex items-center gap-1.5">
          <span
            className="inline-block rounded-full"
            style={{
              width: 22,
              height: tokens.activity[level].width,
              background: color(tokens.activity[level], dark),
              boxShadow: level === "high" ? `0 0 8px ${color(tokens.activity.high, dark)}` : undefined,
            }}
          />
          {tokens.activity[level].label}
        </span>
      ))}
      {dots && (
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full" style={{ background: DOT[dark ? "dark" : "light"] }} />
          address
          <span
            className="ml-1 inline-block size-2.5 rounded-full border-[1.5px]"
            style={{ borderColor: DOT[dark ? "dark" : "light"] }}
          />
          block or street stretch
        </span>
      )}
      <span>From past incidents only, never anyone&apos;s movements.</span>
    </div>
  );
}
