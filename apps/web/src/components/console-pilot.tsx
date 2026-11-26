"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/client";
import type { AlertMetrics } from "@/lib/console";

interface Pilot {
  days: number;
  alerts: AlertMetrics;
  reach: { family_accounts: number; reached: number };
  opt_in: Record<string, { granted: number; declined: number; withdrawn: number }>;
  surveys: Record<string, { answers: number; skipped: number; means: number[] }>;
}

const KIND_WORDS: Record<string, string> = {
  location_precise: "Precise location",
  sharing: "Sharing with family",
  notes: "Community notes",
  digests: "Morning digests",
  briefings: "Event-night briefings",
};
const SURVEY_WORDS: Record<string, string> = { signup: "After sign-up", after_alert: "A day after an alert" };

function seconds(value: number | null): string {
  return value === null ? "no deliveries" : `${value.toFixed(1)} s`;
}

/** The pilot on one page, in words and numbers. Counts and averages only, never a person. */
export function ConsolePilot({ token }: { token: string }) {
  const [found, setFound] = useState<Pilot | null>(null);
  useEffect(() => {
    let live = true;
    api<Pilot>("/api/console/pilot", token).then(
      (p) => live && setFound(p),
      () => live && setFound(null),
    );
    return () => {
      live = false;
    };
  }, [token]);
  if (!found) return <p className="text-sm text-muted-foreground">Loading pilot numbers…</p>;
  const surveys = Object.entries(found.surveys);
  return (
    <div className="space-y-5 text-sm">
      <section>
        <h3 className="font-medium">Alerts (last {found.days} days)</h3>
        <p>
          {found.alerts.alerts} alerts. Typical time to show: website {seconds(found.alerts.latency.web.median_s)},
          iPhone {seconds(found.alerts.latency.ios.median_s)}. Reached {found.reach.reached} of{" "}
          {found.reach.family_accounts} family accounts.
          {found.alerts.corrections_per_100 !== null &&
            ` Corrections: ${found.alerts.corrections_per_100} per 100 alerts.`}
        </p>
      </section>
      <section>
        <h3 className="font-medium">Choices people made</h3>
        <table className="numerals w-full text-left">
          <caption className="sr-only">Consent choices per feature</caption>
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="py-1">Feature</th>
              <th scope="col" className="py-1">Yes</th>
              <th scope="col" className="py-1">No</th>
              <th scope="col" className="py-1">Turned off later</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(found.opt_in).map(([kind, c]) => (
              <tr key={kind} className="border-t">
                <td className="py-1">{KIND_WORDS[kind] ?? kind}</td>
                <td className="py-1 tabular-nums">{c.granted}</td>
                <td className="py-1 tabular-nums">{c.declined}</td>
                <td className="py-1 tabular-nums">{c.withdrawn}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-muted-foreground">Counts recorded choices; built-in demo personas count as yes without a record.</p>
      </section>
      <section>
        <h3 className="font-medium">Surveys (1 = disagree, 5 = agree)</h3>
        {surveys.length === 0 ? (
          <p className="text-muted-foreground">No survey answers yet.</p>
        ) : (
          surveys.map(([kind, s]) => (
            <p key={kind}>
              {SURVEY_WORDS[kind] ?? kind}: {s.answers} answered, {s.skipped} skipped
              {s.means.length > 0 && `; averages ${s.means.join(", ")}`}.
            </p>
          ))
        )}
      </section>
    </div>
  );
}
