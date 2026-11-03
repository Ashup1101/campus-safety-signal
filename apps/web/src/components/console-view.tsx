"use client";

import { Clock3, History, Megaphone, MoonStar, PartyPopper, ShieldCheck, Sun } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, color, tokens, useDark, useSession, useSocket } from "@/lib/client";
import { clockTime, type Clock, type Tone } from "@/shared/api";

interface LatencyRow {
  id: string;
  kind: string;
  verification: "official" | "drill" | "reconstruction";
  status: string;
  official_at: string | null;
  received_at: string;
  web_at: string | null;
  ios_at: string | null;
}

interface Replay {
  id: string;
  title: string;
  summary: string;
  sources: string[];
  alerts: number;
  first: string;
}

interface Coverage {
  gaps: { gap_id: string; source: string; start: string | null; end: string | null; fields: string[]; reason: string }[];
  iu_crime_log: { kind: "covered" | "gap"; start: string; end: string; days: number }[];
  bpd_calls_per_year: { year: number; calls: number }[];
}

function seconds(from: string | null, to: string | null): string {
  if (!from || !to) return "";
  const delta = (Date.parse(to) - Date.parse(from)) / 1000;
  if (Math.abs(delta) < 60) return `+${delta.toFixed(1)} s`;
  return `+${Math.floor(delta / 60)} min ${Math.round(delta % 60)} s`;
}

function toneOfRow(row: LatencyRow): Tone {
  if (row.verification !== "official") return row.verification;
  return row.status.toLowerCase() === "normal" ? "normal" : "official";
}

function LatencyBoard({ rows, dark }: { rows: LatencyRow[]; dark: boolean }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">Send a drill or start a replay to see timings.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th className="py-2 pr-3 font-medium">Alert</th>
            <th className="py-2 pr-3 font-medium">IU / official time</th>
            <th className="py-2 pr-3 font-medium">Server got it</th>
            <th className="py-2 pr-3 font-medium">Parent screen</th>
            <th className="py-2 font-medium">iPhone</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const tone = toneOfRow(row);
            // A reconstruction keeps IU's original time; its delays count from our relay.
            const start = row.verification === "reconstruction" ? row.received_at : row.official_at;
            const official =
              row.verification === "reconstruction" && row.official_at
                ? new Date(row.official_at).toLocaleString([], {
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })
                : clockTime(row.official_at);
            return (
              <tr key={row.id} className="border-t border-border">
                <td className="py-2 pr-3">
                  <span className="font-medium" style={{ color: color(tokens.alert[tone], dark) }}>
                    {tokens.alert[tone].label}
                  </span>
                </td>
                <td className="py-2 pr-3">{official}</td>
                <td className="py-2 pr-3">
                  {clockTime(row.received_at)}{" "}
                  {row.verification !== "reconstruction" && (
                    <span className="text-muted-foreground">{seconds(row.official_at, row.received_at)}</span>
                  )}
                </td>
                <td className="py-2 pr-3">
                  {clockTime(row.web_at)} <span className="text-muted-foreground">{seconds(start, row.web_at)}</span>
                </td>
                <td className="py-2">
                  {clockTime(row.ios_at)} <span className="text-muted-foreground">{seconds(start, row.ios_at)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const FIRST_DAY = Date.parse("2011-09-01");

function CoveragePanel({ coverage, dark }: { coverage: Coverage | null; dark: boolean }) {
  if (!coverage) return null;
  const last = Math.max(FIRST_DAY + 1, ...coverage.iu_crime_log.map((span) => Date.parse(span.end)));
  const position = (iso: string) => ((Date.parse(iso) - FIRST_DAY) / (last - FIRST_DAY)) * 100;
  const years = Array.from({ length: new Date(last).getFullYear() - 2011 + 1 }, (_, i) => 2011 + i);
  const most = Math.max(1, ...coverage.bpd_calls_per_year.map((y) => y.calls));
  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="mb-1 flex justify-between text-xs text-muted-foreground">
          <span>IU crime log, incident by incident</span>
          <span>teal = days we have</span>
        </div>
        <div className="relative h-6 overflow-hidden rounded-full bg-muted">
          {coverage.iu_crime_log
            .filter((span) => span.kind === "covered")
            .map((span) => (
              <div
                key={span.start}
                className="absolute inset-y-0"
                style={{
                  left: `${position(span.start)}%`,
                  width: `${Math.max(0.25, position(span.end) - position(span.start))}%`,
                  background: color(tokens.activity.quiet, dark),
                }}
              />
            ))}
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
          {years
            .filter((y) => y % 2 === 1)
            .map((y) => (
              <span key={y}>{y}</span>
            ))}
        </div>
      </div>
      <ul className="flex flex-col gap-2 text-sm">
        {coverage.gaps.map((gap) => (
          <li key={gap.gap_id} className="rounded-lg bg-muted p-3">
            <div className="text-xs font-medium">
              {gap.start && gap.end ? `${gap.start} to ${gap.end}` : "All years"} ·{" "}
              {gap.source === "iu_crime_log" ? "IU crime log" : "BPD calls for service"}
            </div>
            <p className="text-xs text-muted-foreground">{gap.reason}</p>
          </li>
        ))}
      </ul>
      <div>
        <div className="mb-1 text-xs text-muted-foreground">
          BPD calls for service per year (district only, no street address)
        </div>
        <div className="flex h-16 items-end gap-1">
          {coverage.bpd_calls_per_year.map((y) => (
            <div key={y.year} className="flex flex-1 flex-col items-center gap-1">
              <div
                className="w-full rounded-t"
                style={{ height: `${(y.calls / most) * 48}px`, background: color(tokens.activity.quiet, dark) }}
                title={`${y.year}: ${y.calls.toLocaleString()} calls`}
              />
              <span className="text-[10px] text-muted-foreground">{String(y.year).slice(2)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ConsoleView() {
  const dark = useDark();
  const { session, error } = useSession("console");
  const token = session?.token;
  const [rows, setRows] = useState<LatencyRow[]>([]);
  const [replays, setReplays] = useState<Replay[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [clock, setClock] = useState<Clock | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (token) api<LatencyRow[]>("/api/latency", token).then(setRows);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    let live = true;
    Promise.all([
      api<LatencyRow[]>("/api/latency", token),
      api<Replay[]>("/api/replays", token),
      api<Coverage>("/api/coverage", token),
      api<Clock>("/api/clock", token),
    ]).then(([latency, list, data, current]) => {
      if (!live) return;
      setRows(latency);
      setReplays(list);
      setCoverage(data);
      setClock(current);
    });
    return () => {
      live = false;
    };
  }, [token]);

  const { connected } = useSocket(token, (message) => {
    if (message.type === "latency" || message.type === "alert") refresh();
    if (message.type === "clock") setClock(message.clock);
  });

  const post = (path: string, body: object, label: string) => {
    if (!token) return;
    api(path, token, { method: "POST", body: JSON.stringify(body) }).then(() => setSent(label));
  };

  return (
    <div className="min-h-screen px-5 py-4">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <ShieldCheck className="size-6 text-primary" />
        <div className="mr-auto">
          <h1 className="text-lg font-semibold">IUPD demo console</h1>
          <p className="text-xs text-muted-foreground">
            Drills and replays reach test accounts only. Every message says DRILL or RECONSTRUCTION.
          </p>
        </div>
        <Badge variant={connected ? "default" : "outline"}>{connected ? "Connected" : "Connecting…"}</Badge>
      </header>
      {error && <p className="mb-4 rounded-xl bg-muted p-4 text-sm">{error}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Drill</CardTitle>
            <CardDescription>&quot;DRILL: Shelter in place, avoid Kirkwood Avenue.&quot;</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={() => post("/api/drill", { action: "drill" }, "Drill sent")}>
              <Megaphone /> Send drill
            </Button>
            <Button variant="outline" onClick={() => post("/api/drill", { action: "all_clear" }, "All-clear sent")}>
              <ShieldCheck /> Send all-clear
            </Button>
            {sent && <p className="w-full text-xs text-muted-foreground">{sent}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Demo clock</CardTitle>
            <CardDescription>
              {clock ? `${clock.live ? "Live" : "Moved"}: ${new Date(clock.now).toLocaleString()}` : "…"}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => post("/api/clock", { preset: "live" }, "Clock: live")}>
              <Sun /> Live
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => post("/api/clock", { preset: "late_night" }, "Clock: late night")}
            >
              <MoonStar /> Late night, 11:45 pm
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => post("/api/clock", { preset: "event_night" }, "Clock: event night")}
            >
              <PartyPopper /> Event night, 11:45 pm
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Replays</CardTitle>
            <CardDescription>IU&apos;s real alert texts and times, one minute per second.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {replays.length === 0 && (
              <p className="text-sm text-muted-foreground">No replays (data/manual/demo_incidents.yaml missing).</p>
            )}
            {replays.map((replay) => (
              <div key={replay.id} className="flex items-start gap-3">
                <History className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{replay.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(replay.first).toLocaleDateString()} · {replay.alerts} IU alerts
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => post(`/api/replays/${replay.id}`, {}, `Replaying ${replay.title}`)}
                >
                  Replay
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock3 className="size-4" /> Latency board
            </CardTitle>
            <CardDescription>From the official time to the moment each screen showed the alert.</CardDescription>
          </CardHeader>
          <CardContent>
            <LatencyBoard rows={rows} dark={dark} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Data coverage</CardTitle>
            <CardDescription>What public data covers, and where it is missing.</CardDescription>
          </CardHeader>
          <CardContent>
            <CoveragePanel coverage={coverage} dark={dark} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
