"use client";

import { CircleAlert, CircleCheck, CircleDashed, Clock, Database } from "lucide-react";
import { cadenceWords, errorWords, type DatabaseInfo, type PushCounts, type SourceHealth } from "@/lib/console";

const STATES = {
  fresh: { word: "Fresh", Icon: CircleCheck },
  stale: { word: "Stale", Icon: Clock },
  failing: { word: "Failing", Icon: CircleAlert },
  never: { word: "No copy yet", Icon: CircleDashed },
} as const;

function mailWords(counts: Record<string, number>): string {
  const parts = (["sent", "queued", "failed"] as const)
    .filter((k) => counts[k])
    .map((k) => `${counts[k]} ${k === "queued" ? "waiting" : k}`);
  return parts.length ? ` (${parts.join(", ")})` : "";
}

function pushWords(p: PushCounts): string {
  const failed = Object.entries(p.failed)
    .map(([kind, n]) => `${n} ${kind}`)
    .join(", ");
  const phones = `${p.devices} ${p.devices === 1 ? "phone" : "phones"}`;
  return `${phones}; ${p.sent} sent, ${p.delivered} delivered, ${p.waiting_for_receipt} waiting${failed ? `; failed: ${failed}` : ""}`;
}

function when(at: string | null): string {
  return at ? new Date(at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) : "never";
}

/** Which database holds family data, then each source's state in words with its expected
 * cadence; stale and failing say why. */
export function ConsoleHealth({
  sources,
  database = null,
  pushes = null,
}: {
  sources: SourceHealth[] | null;
  database?: DatabaseInfo | null;
  pushes?: PushCounts | null;
}) {
  if (!sources) return <p className="text-sm text-muted-foreground">Loading source health…</p>;
  return (
    <div className="space-y-3">
      {database && (
        <dl className="grid gap-1 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-3">
          <dt className="inline-flex items-center gap-1.5 font-medium">
            <Database className="size-4" aria-hidden />
            Database:
          </dt>
          <dd>{database.label}</dd>
          <dt className="font-medium">Sign-in:</dt>
          <dd>{database.sign_in}</dd>
          <dt className="font-medium">Email:</dt>
          <dd>
            {database.email}
            {mailWords(database.emails)}
          </dd>
          {pushes && (
            <>
              <dt className="font-medium">Push:</dt>
              <dd>{pushWords(pushes)}</dd>
            </>
          )}
          {database.auth_deletions_waiting > 0 && (
            <>
              <dt className="font-medium">Waiting:</dt>
              <dd>{database.auth_deletions_waiting} sign-in identities still to delete (retried)</dd>
            </>
          )}
        </dl>
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
