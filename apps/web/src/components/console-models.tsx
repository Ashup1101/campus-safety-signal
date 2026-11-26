"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/client";

interface ModelCard {
  name: string;
  what: string;
  words: string;
  run_id: string | null;
  trained_at: string | null;
  scores: Record<string, unknown>;
}

/** T1-T4 in words: which method is in use and why, with the newest run's scores. */
export function ConsoleModels({ token }: { token: string }) {
  const [cards, setCards] = useState<ModelCard[] | null>(null);
  useEffect(() => {
    let live = true;
    api<ModelCard[]>("/api/console/models", token).then(
      (found) => live && setCards(found),
      () => live && setCards([]),
    );
    return () => {
      live = false;
    };
  }, [token]);
  if (!cards) return <p className="text-sm text-muted-foreground">Loading model cards…</p>;
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {cards.map((c) => (
        <li key={c.name} className="rounded-lg border p-3 text-sm">
          <p className="font-medium">
            {c.name.toUpperCase()}: {c.what}
          </p>
          <p>{c.words}.</p>
          {c.run_id && (
            <p className="text-xs text-muted-foreground">
              Run {c.run_id}
              {c.trained_at ? `, trained ${c.trained_at.slice(0, 10)}` : ""}.
            </p>
          )}
          {Object.keys(c.scores).length > 0 && (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer">Scores</summary>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(c.scores, null, 2)}</pre>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}
