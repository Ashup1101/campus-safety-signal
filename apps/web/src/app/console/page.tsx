"use client";

import { useEffect, useState } from "react";
import { ConsoleSignIn } from "@/components/console-sign-in";
import { ConsoleView } from "@/components/console-view";
import { onNewToken } from "@/lib/auth";
import type { Session } from "@/lib/client";
import { canOpenConsole } from "@/shared/api";

export default function ConsolePage() {
  const [session, setSession] = useState<Session | null>(null);
  // Supabase renews the sign-in about hourly; a sign-out ends the console session.
  useEffect(() => onNewToken((token) => setSession((s) => (s && token ? { ...s, token } : null))), []);
  if (!session) return <ConsoleSignIn onSession={setSession} />;
  if (!canOpenConsole(session.account.role)) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-3 px-5">
        <h1 className="text-xl font-semibold">This website is the IUPD console.</h1>
        <p className="text-sm text-muted-foreground">Students and parents use the Campus Safety Signal app instead.</p>
        <button className="self-start text-sm underline" onClick={() => setSession(null)}>
          Back
        </button>
      </main>
    );
  }
  return <ConsoleView session={session} />;
}
