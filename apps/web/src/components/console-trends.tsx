"use client";

import { useState } from "react";
import { ChartWithTable } from "@/components/console-charts";
import { color, tokens } from "@/lib/client";
import { trendZones, type TrendWeek } from "@/lib/console";

/** Weekly calls for service in one police zone next to the same weeks a year earlier. */
export function ConsoleTrends({ rows, dark }: { rows: TrendWeek[] | null; dark: boolean }) {
  const zones = rows ? trendZones(rows) : [];
  const [picked, setPicked] = useState<string | null>(null);
  if (!rows) return <p className="text-sm text-muted-foreground">Loading weekly trends…</p>;
  if (zones.length === 0) return <p className="text-sm text-muted-foreground">No city call data in the warehouse yet.</p>;
  const zone = picked && zones.includes(picked) ? picked : zones[0];
  const weeks = rows.filter((r) => r.zonecode === zone);
  const most = Math.max(...weeks.flatMap((w) => [w.calls, w.calls_last_year]), 1);
  const bar = (value: number, tone: "quiet" | "elevated") => (
    <span
      className="block w-full rounded-t"
      style={{ height: `${Math.max((value / most) * 96, 2)}px`, background: color(tokens.activity[tone], dark) }}
    />
  );
  return (
    <div className="space-y-3">
      <label className="flex flex-wrap items-center gap-2 text-sm">
        Police zone
        <select
          value={zone}
          onChange={(e) => setPicked(e.target.value)}
          className="rounded-md border bg-background px-2 py-1"
        >
          {zones.map((z) => (
            <option key={z} value={z}>
              {z}
            </option>
          ))}
        </select>
        <span className="text-muted-foreground">Busiest zones first. Calls for service are not crimes.</span>
      </label>
      <ChartWithTable
        title={`Calls per week in ${zone}: this year (left bar) and the same week last year (right bar)`}
        chart={
          <ol className="flex h-28 items-end gap-1" aria-label={`Weekly calls in ${zone}`}>
            {weeks.map((w) => (
              <li key={w.week} className="flex flex-1 items-end gap-px" title={`${w.week}: ${w.calls} vs ${w.calls_last_year}`}>
                {bar(w.calls, "quiet")}
                {bar(w.calls_last_year, "elevated")}
              </li>
            ))}
          </ol>
        }
        table={
          <table className="numerals w-full text-left text-sm">
            <caption className="sr-only">Weekly calls in {zone}</caption>
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th scope="col" className="p-2 font-medium">Week of</th>
                <th scope="col" className="p-2 font-medium">Calls</th>
                <th scope="col" className="p-2 font-medium">Same week last year</th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((w) => (
                <tr key={w.week} className="border-b last:border-0">
                  <td className="p-2">{w.week}</td>
                  <td className="p-2 tabular-nums">{w.calls}</td>
                  <td className="p-2 tabular-nums">{w.calls_last_year}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
      />
    </div>
  );
}
