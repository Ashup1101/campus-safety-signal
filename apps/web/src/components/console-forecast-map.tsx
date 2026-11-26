"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibre, Popup } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { BOUNDS, CENTER, baseStyle } from "@/components/activity-map";
import { color, tokens } from "@/lib/client";
import { mapNight, nightLabel, zoneLevels, type Forecasts, type ZoneShapes } from "@/lib/console";

function shaded(shapes: ZoneShapes | null, forecasts: Forecasts | null) {
  const night = forecasts ? mapNight(forecasts).night : null;
  const levels = forecasts ? zoneLevels(forecasts, night) : new Map();
  const reasons = new Map((forecasts?.tonight.zones ?? []).map((z) => [z.zonecode, z.reason]));
  return {
    type: "FeatureCollection" as const,
    features: (shapes?.features ?? [])
      .filter((f) => levels.has(f.properties.zonecode))
      .map((f) => {
        const { level, expected } = levels.get(f.properties.zonecode)!;
        return {
          ...f,
          properties: {
            zonecode: f.properties.zonecode,
            level,
            text: `Zone ${f.properties.zonecode}: ${tokens.activity[level as "quiet"].label}, about ${expected.toFixed(1)} calls expected late at night.${reasons.get(f.properties.zonecode) ? ` ${reasons.get(f.properties.zonecode)}.` : ""}`,
          },
        };
      }),
  };
}

/** Police zones shaded by the forecast's expected late-night level; click a zone for its numbers. */
export function ConsoleForecastMap({
  shapes,
  forecasts,
  dark,
}: {
  shapes: ZoneShapes | null;
  forecasts: Forecasts | null;
  dark: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibre | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let instance: MapLibre | null = null;
    let popup: Popup | null = null;
    (async () => {
      const maplibre = await import("maplibre-gl");
      maplibre.setWorkerUrl("/maplibre-worker");
      const { Protocol } = await import("pmtiles");
      if (cancelled || !container.current) return;
      maplibre.addProtocol("pmtiles", new Protocol().tile);
      const created = new maplibre.Map({
        container: container.current,
        style: baseStyle(dark),
        center: CENTER,
        zoom: 13.4,
        maxBounds: BOUNDS,
        attributionControl: { compact: true },
      });
      instance = created;
      created.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
      created.on("load", () => {
        const tone = dark ? "dark" : "light";
        const fill: ExpressionSpecification = [
          "match",
          ["get", "level"],
          "high",
          tokens.activity.high[tone],
          "elevated",
          tokens.activity.elevated[tone],
          tokens.activity.quiet[tone],
        ];
        created.addSource("forecast", { type: "geojson", data: shaded(null, null) });
        created.addLayer({
          id: "forecast-fill",
          type: "fill",
          source: "forecast",
          paint: { "fill-color": fill, "fill-opacity": 0.32 },
        });
        created.addLayer({
          id: "forecast-edge",
          type: "line",
          source: "forecast",
          paint: { "line-color": fill, "line-width": 1.5 },
        });
        created.on("click", "forecast-fill", (e) => {
          const text = String(e.features?.[0]?.properties?.text ?? "");
          popup?.remove();
          // MapLibre popups are white in both themes: dark text keeps the words readable.
          const body = document.createElement("p");
          body.textContent = text;
          body.style.color = "#1c1416";
          popup = new maplibre.Popup({ closeButton: true, maxWidth: "260px" })
            .setLngLat(e.lngLat)
            .setDOMContent(body)
            .addTo(created);
        });
        created.on("mouseenter", "forecast-fill", () => (created.getCanvas().style.cursor = "pointer"));
        created.on("mouseleave", "forecast-fill", () => (created.getCanvas().style.cursor = ""));
        map.current = created;
        setReady(true);
      });
    })();
    return () => {
      cancelled = true;
      map.current = null;
      setReady(false);
      popup?.remove();
      instance?.remove();
    };
  }, [dark]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource("forecast") as GeoJSONSource | undefined)?.setData(shaded(shapes, forecasts));
  }, [ready, shapes, forecasts]);

  const shown = forecasts ? mapNight(forecasts) : { night: null, tonight: false };
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        {shown.night
          ? `${shown.tonight ? "Tonight" : "First forecast night"} (${nightLabel(shown.night)}), 10 pm to 4 am. Made by: ${forecasts?.method_words}. Calls for service, not crimes.`
          : "No forecast imported yet. Nothing is shown rather than a guess."}
      </p>
      <div ref={container} className="h-[420px] w-full overflow-hidden rounded-xl" />
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        {(["quiet", "elevated", "high"] as const).map((level) => (
          <span key={level} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-3 rounded-sm" style={{ background: color(tokens.activity[level], dark) }} />
            {tokens.activity[level].label}
          </span>
        ))}
        <span>Click a zone for its expected calls.</span>
      </div>
    </div>
  );
}
