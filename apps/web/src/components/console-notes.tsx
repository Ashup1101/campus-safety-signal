"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/client";
import type { QueuedNote } from "@/lib/console";

const WHY = { held: "Held: alarming or official-sounding words", hidden: "Hidden: reports or a moderator" };

/** Moderation for community notes: act on a note, never see who wrote it; IU's kill switch. */
export function ConsoleNotes({ token }: { token: string }) {
  const [queue, setQueue] = useState<QueuedNote[] | null>(null);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [confirmOff, setConfirmOff] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(() => {
    api<QueuedNote[]>("/api/console/notes/queue", token).then(setQueue, () => setQueue([]));
    api<{ enabled: boolean }>("/api/console/notes/switch", token).then((s) => setEnabled(s.enabled), () => {});
  }, [token]);

  useEffect(load, [load]);

  const act = (id: number, action: "hide" | "unhide" | "ban") =>
    api(`/api/console/notes/${id}/${action}`, token, { method: "POST" }).then(() => {
      setDone(action === "ban" ? "Posting paused for 7 days; that person's notes were removed." : `Note ${action === "hide" ? "hidden" : "shown again (needs agreement)"}.`);
      load();
    });

  const flip = (value: boolean) =>
    api<{ enabled: boolean }>("/api/console/notes/switch", token, {
      method: "POST",
      body: JSON.stringify({ enabled: value }),
    }).then((s) => {
      setEnabled(s.enabled);
      setConfirmOff(false);
    });

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <span className="font-medium">
          Community notes are {enabled === null ? "…" : enabled ? "on" : "off everywhere"}
        </span>
        {enabled && !confirmOff && (
          <Button variant="outline" onClick={() => setConfirmOff(true)}>
            Turn notes off
          </Button>
        )}
        {enabled && confirmOff && (
          <>
            <span>Hide every note and stop posting now?</span>
            <Button onClick={() => flip(false)}>Yes, turn off</Button>
            <Button variant="outline" onClick={() => setConfirmOff(false)}>
              Cancel
            </Button>
          </>
        )}
        {enabled === false && (
          <Button variant="outline" onClick={() => flip(true)}>
            Turn notes back on
          </Button>
        )}
      </div>
      {done && <p role="status">{done}</p>}
      {queue === null && <p className="text-muted-foreground">Loading the review queue…</p>}
      {queue?.length === 0 && <p className="text-muted-foreground">Nothing waiting for review.</p>}
      {queue && queue.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {queue.map((n) => (
            <li key={n.id} className="flex flex-wrap items-center gap-3 p-3">
              <span className="flex-1">
                <span className="font-medium">{n.tag}</span>
                {n.text && <span className="block">&quot;{n.text}&quot;</span>}
                <span className="block text-xs text-muted-foreground">
                  {WHY[n.state]}. Reports: {n.reports}. Note {n.id}, by an IU student (not shown).
                </span>
              </span>
              <Button variant="outline" onClick={() => act(n.id, "unhide")}>
                Allow
              </Button>
              {n.state === "held" && (
                <Button variant="outline" onClick={() => act(n.id, "hide")}>
                  Hide
                </Button>
              )}
              <Button variant="outline" onClick={() => act(n.id, "ban")}>
                Pause the writer
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
