"use client";

import { Inbox, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, useSession } from "@/lib/client";

// The local mailbox: the demo's stand-in for email. Nothing here leaves the Mac.
interface Message {
  id: number;
  kind: "briefing" | "digest" | "alert" | "correction" | "all_clear";
  subject: string;
  body: string;
  thread_id: string | null;
  created_at: string;
}

const KIND: Record<Message["kind"], string> = {
  briefing: "Before the night",
  digest: "Digest",
  alert: "Alert",
  correction: "Correction",
  all_clear: "All clear",
};
const ACCOUNTS = [
  { id: "parent_mom", label: "Mom" },
  { id: "parent_dad", label: "Dad" },
  { id: "student_sam", label: "Sam" },
  { id: "student_alex", label: "Alex" },
];

export function MailboxView({ accountId, onSwitch }: { accountId: string; onSwitch: (id: string) => void }) {
  const { session, error } = useSession(accountId);
  const token = session?.token;
  const [messages, setMessages] = useState<Message[] | null>(null);

  useEffect(() => {
    if (!token) return;
    let live = true;
    api<Message[]>("/api/mailbox", token).then((found) => live && setMessages(found));
    return () => {
      live = false;
    };
  }, [token]);

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col gap-4 px-5 py-4">
      <header className="flex flex-wrap items-center gap-3">
        <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
          <Inbox className="size-5" aria-hidden />
        </span>
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-[-0.01em]">Mailbox</h1>
          <p className="text-xs text-muted-foreground">Local demo: briefings and digests land here instead of email.</p>
        </div>
        <div className="flex flex-wrap gap-1 rounded-full bg-muted p-1" role="group" aria-label="Demo account">
          {ACCOUNTS.map((a) => (
            <Button
              key={a.id}
              size="sm"
              variant={a.id === accountId ? "outline" : "ghost"}
              aria-pressed={a.id === accountId}
              onClick={() => onSwitch(a.id)}
            >
              <UserRound /> {a.label}
            </Button>
          ))}
        </div>
      </header>
      <Link href="/parent" className="text-sm underline underline-offset-4">
        Back to the parent view
      </Link>
      {error && <p className="rounded-xl bg-muted p-4 text-sm">{error}</p>}
      {messages && messages.length === 0 && (
        <p className="rounded-xl bg-muted p-4 text-sm text-muted-foreground">
          No messages yet. Briefings arrive the afternoon before an event night; digests at 7 am when there is
          something to report.
        </p>
      )}
      {(messages ?? []).map((m) => (
        <Card key={m.id}>
          <CardHeader>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{KIND[m.kind]}</Badge>
              <CardDescription className="tabular-nums">{new Date(m.created_at).toLocaleString()}</CardDescription>
            </div>
            <CardTitle className="text-balance">{m.subject}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-line break-words text-sm">{m.body}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
