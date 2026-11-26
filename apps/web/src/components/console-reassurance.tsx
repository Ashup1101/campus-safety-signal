"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/client";
import { outcomeWords, type ReassuranceCounts } from "@/lib/console";

/** Family check-in outcomes since the demo server started: counts only, never who or where. */
export function ConsoleReassurance({ token }: { token: string }) {
  const [counts, setCounts] = useState<ReassuranceCounts | null>(null);
  useEffect(() => {
    let live = true;
    api<ReassuranceCounts>("/api/console/reassurance", token)
      .then((c) => live && setCounts(c))
      .catch(() => live && setCounts(null));
    return () => {
      live = false;
    };
  }, [token]);
  if (!counts) return null;
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
      <div>
        <dt className="text-muted-foreground">Parent check-ins</dt>
        <dd>{outcomeWords(counts.check_ins)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">&quot;Are you OK?&quot;</dt>
        <dd>{outcomeWords(counts.are_you_ok)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Arrived home (event nights)</dt>
        <dd className="tabular-nums">{counts.arrived_home.sent}</dd>
      </div>
    </dl>
  );
}
