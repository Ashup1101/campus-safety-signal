"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ConsoleAlertMetrics } from "@/components/console-alert-metrics";
import { ChartWithTable } from "@/components/console-charts";
import { ConsoleForecastMap } from "@/components/console-forecast-map";
import { ConsoleHealth } from "@/components/console-health";
import { ConsoleOutlook } from "@/components/console-outlook";
import { ConsoleTrends } from "@/components/console-trends";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, color, tokens } from "@/lib/client";
import {
  monthlyTotals,
  readRealOnly,
  saveRealOnly,
  type ArchiveYear,
  type CrossCheck,
  type Forecasts,
  type GapRow,
  type SourceHealth,
  type TrendWeek,
  type ZoneShapes,
} from "@/lib/console";

const TABS = ["Overview", "Forecasts", "Gaps", "Cross-check", "Archive", "Alerts", "Health"] as const;
type Tab = (typeof TABS)[number];

function useConsole<T>(path: string | null, token: string): T | null {
  const [found, setFound] = useState<T | null>(null);
  useEffect(() => {
    if (!path) return;
    let live = true;
    api<T>(path, token)
      .then((value) => live && setFound(value))
      .catch(() => live && setFound(null));
    return () => {
      live = false;
    };
  }, [path, token]);
  return found;
}

function Panel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

function Table({ head, rows, caption }: { head: string[]; rows: (string | number)[][]; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="numerals w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            {head.map((h) => (
              <th key={h} scope="col" className="p-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="p-2 tabular-nums">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GapsTab({ token, realOnly }: { token: string; realOnly: boolean }) {
  const gaps = useConsole<GapRow[]>(`/api/console/gaps?real_only=${realOnly}`, token);
  if (!gaps) return <p className="text-sm text-muted-foreground">Loading gaps…</p>;
  if (gaps.length === 0) return <p className="text-sm text-muted-foreground">No gap report in the warehouse yet.</p>;
  const head = ["Gap", "Source", "From", "To", "Real days covered", "Why"];
  if (!realOnly) head.push("Synthetic rows (labeled)");
  return (
    <Table
      caption="Data gaps and why they exist"
      head={head}
      rows={gaps.map((g) => {
        const row: (string | number)[] = [
          g.gap_id,
          g.source,
          g.span_start ?? "",
          g.span_end ?? "",
          g.real_days_covered ?? 0,
          g.reason,
        ];
        if (!realOnly) row.push(g.synthetic_rows ?? 0);
        return row;
      })}
    />
  );
}

function CrossCheckTab({ token }: { token: string }) {
  const data = useConsole<CrossCheck>("/api/console/cross-check", token);
  if (!data) return <p className="text-sm text-muted-foreground">Loading the cross-check…</p>;
  const totals = monthlyTotals(data.rows);
  return (
    <>
      <p className="text-sm">{data.note}</p>
      {totals.length === 0 ? (
        <p className="text-sm text-muted-foreground">No overlapping months yet.</p>
      ) : (
        <Table
          caption="IU log entries and city police calls per month and category, last 12 months"
          head={["Month", "Category", "IU log entries", "City police calls"]}
          rows={totals.map((t) => [t.month.slice(0, 7), t.category, t.iu, t.bpd])}
        />
      )}
      {data.calibration.length > 0 && (
        <Table
          caption="City-reported calls vs the open-data feed"
          head={["Year", "Month", "City reported", "Feed rows", "Difference"]}
          rows={data.calibration.map((c) => [
            c.period_year,
            c.period_month,
            c.reported_calls,
            c.feed_calls,
            c.pct_difference === null ? "" : `${c.pct_difference}%`,
          ])}
        />
      )}
    </>
  );
}

function ArchiveTab({ token, dark }: { token: string; dark: boolean }) {
  const years = useConsole<ArchiveYear[]>("/api/console/archive", token);
  if (!years) return <p className="text-sm text-muted-foreground">Loading archive coverage…</p>;
  if (years.length === 0) return <p className="text-sm text-muted-foreground">No archive listings stored yet.</p>;
  const most = Math.max(...years.map((y) => y.listed), 1);
  return (
    <ChartWithTable
      title="Archived copies of the IU crime log per year"
      chart={
        <ol className="space-y-1 text-xs" aria-label="Parsed copies out of listed copies per year">
          {years.map((y) => (
            <li key={y.year} className="flex items-center gap-2">
              <span className="w-10 tabular-nums">{y.year}</span>
              <span className="relative h-3 flex-1 rounded bg-secondary">
                <span
                  className="absolute inset-y-0 left-0 rounded"
                  style={{
                    width: `${(y.parsed / most) * 100}%`,
                    background: color(tokens.activity.quiet, dark),
                  }}
                />
              </span>
              <span className="w-28 tabular-nums">
                {y.parsed} of {y.listed} read
              </span>
            </li>
          ))}
        </ol>
      }
      table={
        <Table
          caption="Archive coverage per year"
          head={["Year", "Listed", "Read", "Could not read", "Not fetched yet"]}
          rows={years.map((y) => [y.year, y.listed, y.parsed, y.failed, y.not_fetched])}
        />
      }
    />
  );
}

function ForecastsTab({ token, dark }: { token: string; dark: boolean }) {
  const forecasts = useConsole<Forecasts>("/api/console/forecasts", token);
  const shapes = useConsole<ZoneShapes>("/api/console/zones", token);
  const card = forecasts?.scorecard;
  const trends = useConsole<TrendWeek[]>("/api/console/trends", token);
  return (
    <>
      <ConsoleForecastMap shapes={shapes} forecasts={forecasts} dark={dark} />
      <ConsoleOutlook forecasts={forecasts} dark={dark} />
      <ConsoleTrends rows={trends} dark={dark} />
      {card && (
        <Table
          caption="How the forecast scored on past years it did not see"
          head={["Method", "Error (deviance, lower is better)", "Typical miss (calls)"]}
          rows={Object.entries(card.scores)
            .filter(([, s]) => s)
            .map(([name, s]) => [
              {
                model: "Forecast model",
                rule: "Simple rule",
                last_week: "Same night last week",
              }[name] ?? name,
              s!.deviance.toFixed(3),
              s!.mae.toFixed(2),
            ])}
        />
      )}
      {card && (
        <p className="text-xs text-muted-foreground">
          In use: {forecasts?.method_words}. Trained {new Date(card.trained_at).toLocaleDateString()}. The model is used
          only when it beats both simpler methods.
        </p>
      )}
    </>
  );
}

/** Console sections as tabs (arrow keys move between them) with a remembered real-only switch. */
export function ConsoleTabs({ token, dark, overview }: { token: string; dark: boolean; overview: ReactNode }) {
  const [tab, setTab] = useState<Tab>("Overview");
  // Rendered only after sign-in (client side), so the stored choice is readable at once.
  const [realOnly, setRealOnly] = useState(() => (typeof window === "undefined" ? true : readRealOnly()));
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const health = useConsole<SourceHealth[]>(tab === "Health" ? "/api/console/health" : null, token);

  const toggle = () => {
    setRealOnly((value) => {
      saveRealOnly(!value);
      return !value;
    });
  };

  const onKey = (event: KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const next = (index + step + TABS.length) % TABS.length;
    setTab(TABS[next]);
    buttons.current[next]?.focus();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Console sections" className="flex flex-wrap gap-1 rounded-lg border p-1">
          {TABS.map((name, i) => (
            <button
              key={name}
              ref={(el) => {
                buttons.current[i] = el;
              }}
              role="tab"
              id={`tab-${i}`}
              aria-selected={tab === name}
              aria-controls={`panel-${i}`}
              tabIndex={tab === name ? 0 : -1}
              onClick={() => setTab(name)}
              onKeyDown={(e) => onKey(e, i)}
              className="rounded-md px-3 py-1.5 text-sm aria-selected:bg-primary aria-selected:text-primary-foreground"
            >
              {name}
            </button>
          ))}
        </div>
        <label className="ml-auto inline-flex items-center gap-2 text-sm">
          <button
            type="button"
            role="switch"
            aria-label="Real data only"
            aria-checked={realOnly}
            onClick={toggle}
            className="relative h-6 w-10 rounded-full border bg-secondary aria-checked:bg-primary"
          >
            <span
              className="absolute top-0.5 size-4 rounded-full bg-background transition-[left]"
              style={{ left: realOnly ? "1.25rem" : "0.25rem" }}
            />
          </button>
          Real data only
        </label>
      </div>
      {TABS.map((name, i) => (
        <div key={name} role="tabpanel" id={`panel-${i}`} aria-labelledby={`tab-${i}`} hidden={tab !== name}>
          {tab === name && name === "Overview" && overview}
          {tab === name && name === "Forecasts" && (
            <Panel
              title="Forecasts"
              description="Expected late-night calls for service per police zone (calls are not crimes)."
            >
              <ForecastsTab token={token} dark={dark} />
            </Panel>
          )}
          {tab === name && name === "Gaps" && (
            <Panel
              title="Gap report"
              description={
                realOnly
                  ? "What public data is missing, and why. Real data only."
                  : "What public data is missing, and how many labeled synthetic rows patch each gap."
              }
            >
              <GapsTab token={token} realOnly={realOnly} />
            </Panel>
          )}
          {tab === name && name === "Cross-check" && (
            <Panel
              title="Cross-check"
              description="IU's crime log next to city police calls, per month (real data only)."
            >
              <CrossCheckTab token={token} />
            </Panel>
          )}
          {tab === name && name === "Archive" && (
            <Panel
              title="Archive coverage"
              description="Old copies of the IU crime log from the Wayback Machine (real data only)."
            >
              <ArchiveTab token={token} dark={dark} />
            </Panel>
          )}
          {tab === name && name === "Alerts" && (
            <Panel
              title="Alert numbers"
              description="How fast alerts reach screens, and how often they were corrected or repeated."
            >
              <ConsoleAlertMetrics token={token} />
            </Panel>
          )}
          {tab === name && name === "Health" && (
            <Panel title="Data health" description="How fresh each public source is (real data only).">
              <ConsoleHealth sources={health} />
            </Panel>
          )}
        </div>
      ))}
    </div>
  );
}
