"use client";

import { CircleAlert, CircleCheck, CircleDashed, Clock, Database } from "lucide-react";
import { cadenceWords, errorWords, type DatabaseInfo, type SourceHealth } from "@/lib/console";

const STATES = {
  fresh: { word: "Fresh", Icon: CircleCheck },
  stale: { word: "Stale", Icon: Clock },
  failing: { word: "Failing", Icon: CircleAlert },
  never: { word: "No copy yet", Icon: CircleDashed },
} as const;

function when(at: string | null): string {
  return at ? new Date(at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) : "never";
}

/** Which database holds family data, then each source's state in words with its expected
 * cadence; stale and failing say why. */
export function ConsoleHealth({
  sources,
  database = null,
}: {
  sources: SourceHealth[] | null;
  database?: DatabaseInfo | null;
}) {
  if (!sources) return <p className="text-sm text-muted-foreground">Loading source health…</p>;
  return (
    <div className="space-y-3">
      {database && (
        <p className="inline-flex items-center gap-1.5 text-sm">
          <Database className="size-4" aria-hidden />
          <span className="font-medium">Database:</span> {database.label}
        </p>
      )}
      <ul className="divide-y rounded-lg border">
        {sources.map((s) => {
          const { word, Icon } = STATES[s.state];
          const why =
            s.state === "stale"
              ? `No new copy within the expected time (${cadenceWords(s.expected_hours)}).`
              : errorWords(s.error_kind);
          return (
            <li key={s.source} className="flex flex-wrap items-start gap-x-4 gap-y-1 p-3 text-sm">
              <span className="inline-flex min-w-28 items-center gap-1.5 font-medium">
                <Icon className="size-4" aria-hidden />
                {word}
              </span>
              <span className="flex-1">
                <span className="font-medium">{s.label}</span>
                <span className="block text-muted-foreground">
                  Expected {cadenceWords(s.expected_hours)}. Newest copy: {when(s.last_stored_at)} ({s.copies}{" "}
                  stored).
                </span>
                {why && <span className="block">{why}</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
