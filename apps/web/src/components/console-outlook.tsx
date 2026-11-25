"use client";

import { useState } from "react";
import { color, tokens } from "@/lib/client";
import { nightLabel, type Forecasts } from "@/lib/console";

type Order = "zone" | "busiest";

/** Seven-night outlook: campus-wide bars (with their numbers) and a per-zone table. Event nights
 * are named; every cell says its level in words, so nothing depends on color alone. */
export function ConsoleOutlook({ forecasts, dark }: { forecasts: Forecasts | null; dark: boolean }) {
  const [order, setOrder] = useState<Order>("busiest");
  const nights = forecasts?.outlook.nights ?? [];
  if (!forecasts || nights.length === 0) {
    return <p className="text-sm text-muted-foreground">No forecast imported yet, so there is no outlook to show.</p>;
  }
  const most = Math.max(...nights.map((n) => n.campus_expected), 1);
  const total = (z: Forecasts["outlook"]["zones"][number]) => z.nights.reduce((sum, n) => sum + n.expected, 0);
  const zones = [...forecasts.outlook.zones].sort((a, b) =>
    order === "zone" ? a.zonecode.localeCompare(b.zonecode) : total(b) - total(a),
  );
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Expected late-night calls for service (10 pm to 4 am), not crimes. Made by: {forecasts.method_words}.
      </p>
      <ol className="flex h-32 items-end gap-2" aria-label="Expected calls across campus zones per night">
        {nights.map((n) => (
          <li key={n.night} className="flex flex-1 flex-col items-center gap-1 text-xs">
            <span>{n.campus_expected.toFixed(0)}</span>
            <span
              className="w-full rounded-t"
              style={{
                height: `${Math.max((n.campus_expected / most) * 80, 2)}px`,
                background: color(tokens.activity.quiet, dark),
              }}
            />
            <span className="text-muted-foreground">{nightLabel(n.night)}</span>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Sort zones:</span>
        {(["busiest", "zone"] as const).map((o) => (
          <button
            key={o}
            type="button"
            aria-pressed={order === o}
            onClick={() => setOrder(o)}
            className="rounded-md border px-2 py-1 aria-pressed:bg-secondary aria-pressed:font-medium"
          >
            {o === "busiest" ? "Busiest first" : "By zone code"}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Expected late-night calls per police zone for the next seven nights</caption>
          <thead>
            <tr className="border-b text-left">
              <th scope="col" className="p-2">Zone</th>
              {nights.map((n) => (
                <th key={n.night} scope="col" className="p-2 font-medium">
                  {nightLabel(n.night)}
                  {n.event && <span className="block text-xs font-normal text-muted-foreground">{n.event}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b bg-secondary/40">
              <th scope="row" className="p-2 text-left">All zones</th>
              {nights.map((n) => (
                <td key={n.night} className="p-2 tabular-nums">{n.campus_expected.toFixed(1)}</td>
              ))}
            </tr>
            {zones.map((z) => (
              <tr key={z.zonecode} className="border-b last:border-0">
                <th scope="row" className="p-2 text-left font-normal">{z.zonecode}</th>
                {nights.map((n) => {
                  const hit = z.nights.find((x) => x.night === n.night);
                  return (
                    <td key={n.night} className="p-2 tabular-nums">
                      {hit ? `${hit.expected.toFixed(1)} · ${tokens.activity[hit.level].label}` : "–"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
