"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/client";
import type { AlertMetrics } from "@/lib/console";

const PERIODS = [7, 30, 90] as const;

function seconds(value: number | null): string {
  if (value === null) return "no deliveries";
  return value < 120 ? `${value.toFixed(1)} seconds` : `${(value / 60).toFixed(1)} minutes`;
}

function rate(count: number, per100: number | null): string {
  return per100 === null ? "no alerts yet" : `${per100} per 100 alerts (${count} in all)`;
}

/** Delivery time per device type, corrections and repeats, for a chosen period. */
export function ConsoleAlertMetrics({ token }: { token: string }) {
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const [found, setFound] = useState<AlertMetrics | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let live = true;
    api<AlertMetrics>(`/api/console/alert-metrics?days=${days}`, token)
      .then((m) => live && (setFound(m), setError(false)))
      .catch(() => live && setError(true));
    return () => {
      live = false;
    };
  }, [days, token]);

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Period">
        <span className="text-muted-foreground">Last</span>
        {PERIODS.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={days === d}
            onClick={() => setDays(d)}
            className="rounded-md border px-2 py-1 aria-pressed:bg-secondary aria-pressed:font-medium"
          >
            {d} days
          </button>
        ))}
      </div>
      {error && <p>Alert numbers could not be loaded. Is the demo server running?</p>}
      {found && found.alerts === 0 && <p className="text-muted-foreground">No alerts in the last {days} days.</p>}
      {found && found.alerts > 0 && (
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Alerts</dt>
            <dd className="font-medium tabular-nums">{found.alerts}</dd>
          </div>
          {(["web", "ios"] as const).map((client) => (
            <div key={client}>
              <dt className="text-muted-foreground">
                Time to show on {client === "web" ? "the website" : "iPhone"} (from the server receiving it)
              </dt>
              <dd className="tabular-nums">
                Typical {seconds(found.latency[client].median_s)}; slowest 5% {seconds(found.latency[client].p95_s)}{" "}
                ({found.latency[client].deliveries} deliveries)
              </dd>
            </div>
          ))}
          <div>
            <dt className="text-muted-foreground">Corrections</dt>
            <dd className="tabular-nums">{rate(found.corrections, found.corrections_per_100)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Repeats (same alert shown twice to one person)</dt>
            <dd className="tabular-nums">{rate(found.duplicates, found.duplicates_per_100)}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
