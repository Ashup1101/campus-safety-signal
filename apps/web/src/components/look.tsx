"use client";

import { useSyncExternalStore } from "react";
import { tokens } from "@/lib/client";
import { type Tonight } from "@/shared/api";
export { tonightOf } from "@/shared/api";

// Game day look (owner's pick, 2026-11-23): a scoreboard strip, crimson and cream stripe on anything live.

// The current time, refreshed every 30 s, for "minutes ago" figures (no clock reads during render).
let nowValue = 0;
function subscribeNow(onChange: () => void) {
  nowValue = Date.now();
  const timer = setInterval(() => {
    nowValue = Date.now();
    onChange();
  }, 30_000);
  return () => clearInterval(timer);
}
export function useNow(): number {
  return useSyncExternalStore(subscribeNow, () => nowValue, () => 0);
}

function ago(minutes: number | null): string {
  if (minutes === null) return "None";
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h`;
  return `${Math.round(minutes / 1440)} d`;
}

// Game day: a scoreboard. Ink panel, cream numerals, the stripe only when something is live.
export function Scoreboard({ tonight, windowLabel }: { tonight: Tonight; windowLabel: string }) {
  const cells = [
    { label: `Busiest street, ${windowLabel.toLowerCase()}`, value: tonight.top ? tokens.activity[tonight.top.level].label : "Quiet", note: tonight.top?.name ?? "No busy streets in this window" },
    { label: "Live alerts", value: String(tonight.live), note: tonight.live ? "Official alert in progress" : "Nothing live right now" },
    { label: "Last alert", value: ago(tonight.lastMinutes), note: tonight.lastMinutes === null ? "No alerts yet" : "ago" },
  ];
  return (
    <section aria-label="Tonight" className="overflow-hidden rounded-2xl bg-foreground text-background">
      <div className={`h-2 ${tonight.live ? "stripe-live" : "bg-primary"}`} aria-hidden />
      <div className="grid grid-cols-1 divide-y divide-background/15 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {cells.map((cell) => (
          <div key={cell.label} className="px-5 py-4">
            <div className="text-xs text-background/70">{cell.label}</div>
            <div className="numerals mt-1 text-4xl font-semibold leading-none">{cell.value}</div>
            <div className="mt-2 truncate text-sm text-background/80">{cell.note}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
