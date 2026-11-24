"use client";

import { useSyncExternalStore } from "react";
import { tokens } from "@/lib/client";
import { levelFor, type AlertThread, type Level, type Segments, type TimeWindow } from "@/shared/api";

// Two candidate looks the owner is comparing (v2): "gameday" (scoreboard, candy stripe on anything
// live) and "strava" (activity stat tiles). Same data, same rules; only presentation differs.
export type Look = "gameday" | "strava";
const LOOKS: { id: Look; label: string }[] = [
  { id: "gameday", label: "Game day" },
  { id: "strava", label: "Strava" },
];

const LOOK_EVENT = "look-change";

function readLook(): Look {
  const fromUrl = new URLSearchParams(window.location.search).get("look");
  let saved: string | null = null;
  try {
    saved = localStorage.getItem("look");
  } catch {}
  const chosen = fromUrl ?? saved;
  return chosen === "strava" ? "strava" : "gameday";
}

function subscribeLook(onChange: () => void) {
  window.addEventListener(LOOK_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(LOOK_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useLook(): [Look, (look: Look) => void] {
  const look = useSyncExternalStore(subscribeLook, readLook, () => "gameday" as Look);
  const choose = (next: Look) => {
    try {
      localStorage.setItem("look", next);
    } catch {}
    const url = new URL(window.location.href);
    url.searchParams.set("look", next);
    window.history.replaceState(null, "", url);
    window.dispatchEvent(new Event(LOOK_EVENT));
  };
  return [look, choose];
}

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

export function LookSwitch({ look, onChange }: { look: Look; onChange: (look: Look) => void }) {
  return (
    <div role="radiogroup" aria-label="Look" className="flex gap-1 rounded-full bg-muted p-1 text-sm">
      {LOOKS.map((option) => (
        <button
          key={option.id}
          role="radio"
          aria-checked={option.id === look}
          onClick={() => onChange(option.id)}
          className={`rounded-full px-3 py-1.5 transition-[background-color,color,transform] duration-100 active:scale-[0.97] ${
            option.id === look ? "bg-card font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

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

// Strava: activity tiles plus the top segment, like a segment leaderboard row.
export function ActivityTiles({ tonight, windowLabel, dark }: { tonight: Tonight; windowLabel: string; dark: boolean }) {
  const tiles = [
    { label: "High streets", value: tonight.high, level: "high" as const },
    { label: "Elevated streets", value: tonight.elevated, level: "elevated" as const },
    { label: "Live alerts", value: tonight.live, level: null },
  ];
  return (
    <section aria-label="Tonight" className="rounded-2xl border bg-card p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold">Tonight around campus</h2>
        <span className="text-xs text-muted-foreground">{windowLabel}</span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded-xl bg-muted px-3 py-3">
            <div className="numerals text-3xl font-semibold leading-none">{tile.value}</div>
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
              {tile.level && (
                <span
                  aria-hidden
                  className="h-1 w-4 rounded-full"
                  style={{ background: dark ? tokens.activity[tile.level].dark : tokens.activity[tile.level].light }}
                />
              )}
              {tile.label}
            </div>
          </div>
        ))}
      </div>
      {tonight.top && (
        <div className="mt-3 flex items-center gap-3 rounded-xl border px-3 py-2.5">
          <span
            aria-hidden
            className="h-8 w-1.5 shrink-0 rounded-full"
            style={{ background: dark ? tokens.activity[tonight.top.level].dark : tokens.activity[tonight.top.level].light }}
          />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">
              {tonight.top.name} · {tokens.activity[tonight.top.level].label}
            </div>
            <div className="truncate text-xs text-muted-foreground">{tonight.top.reason}</div>
          </div>
        </div>
      )}
    </section>
  );
}
