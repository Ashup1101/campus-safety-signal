"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AUTH_MODE, emailLink, openedSession } from "@/lib/auth";
import { demoLogin, signInWithLink, type Session } from "@/lib/client";

const NOT_CONSOLE = "This website is the IUPD console. Students and parents use the Campus Safety Signal app.";

// The website is the IUPD console only. Students and parents use the app and are turned away here.
export function ConsoleSignIn({ onSession }: { onSession: (session: Session) => void }) {
  const [link, setLink] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const fail = (e: Error) => setNote(e.message);
  const supabase = AUTH_MODE === "supabase";

  useEffect(() => {
    if (!supabase) return;
    openedSession().then((opened) => {
      if (opened.kind === "console") onSession(opened.session);
      if (opened.kind === "not_console") setNote(NOT_CONSOLE);
    });
  }, [supabase, onSession]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-5">
      <Card>
        <CardHeader>
          <span className="mb-2 grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
            <ShieldCheck className="size-5" aria-hidden />
          </span>
          <CardTitle>IUPD console</CardTitle>
          <CardDescription>For IU police and emergency staff. Students and parents use the app.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {supabase ? (
            <>
              <label className="flex flex-col gap-1 text-sm">
                Work email
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="rounded-lg border bg-background px-3 py-2"
                  autoComplete="email"
                />
              </label>
              <Button
                onClick={() =>
                  emailLink(email).then(
                    (e) => setNote(e ?? "Check your inbox and open the link in this browser."),
                    () => setNote("We could not reach the sign-in service. Try again in a minute."),
                  )
                }
              >
                Email me a sign-in link
              </Button>
            </>
          ) : (
            <>
              <label className="flex flex-col gap-1 text-sm">
                Sign-in link
                <input
                  value={link}
                  onChange={(e) => setLink(e.target.value)}
                  className="rounded-lg border bg-background px-3 py-2"
                  autoComplete="off"
                />
              </label>
              <Button onClick={() => signInWithLink(link).then(onSession, fail)}>Sign in</Button>
              <Button variant="outline" onClick={() => demoLogin("console").then(onSession, fail)}>
                Demo console (test account)
              </Button>
            </>
          )}
          {note && <p className="text-sm text-muted-foreground">{note}</p>}
        </CardContent>
      </Card>
    </main>
  );
}
