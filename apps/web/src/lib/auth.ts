import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { SERVER, type Session } from "@/lib/client";
import type { Account } from "@/shared/api";

// AUTH_MODE=supabase: IUPD reviewers sign in with a Supabase email link; the server checks the
// session and the console allowlist. Anything else: the demo's own sign-in and test console.
export const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE === "supabase" ? "supabase" : "demo";

let client: SupabaseClient | null = null;
export function supabase(): SupabaseClient {
  client ??= createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "", // public by design; RLS blocks it
    { auth: { flowType: "implicit", persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
  );
  return client;
}

export async function emailLink(email: string): Promise<string | null> {
  const { error } = await supabase().auth.signInWithOtp({
    email: email.trim(),
    options: { emailRedirectTo: `${window.location.origin}/console`, shouldCreateUser: true },
  });
  return error ? "We could not send the link. Check the email and try again in a minute." : null;
}

export type Opened = { kind: "console"; session: Session } | { kind: "not_console" } | { kind: "none" };

/** After the link opens /console: the console session, or "not_console" for anyone else. */
export async function openedSession(): Promise<Opened> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) return { kind: "none" };
  const response = await fetch(`${SERVER}/api/session`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) return { kind: "none" };
  const body = (await response.json()) as { state: string; account?: Account };
  if (body.state === "active" && body.account?.role === "console") {
    return { kind: "console", session: { token, account: body.account } };
  }
  return { kind: "not_console" };
}

export function onNewToken(update: (token: string | null) => void): () => void {
  if (AUTH_MODE !== "supabase") return () => {};
  const { data } = supabase().auth.onAuthStateChange((event, session) => {
    if (event === "TOKEN_REFRESHED" || event === "SIGNED_OUT") update(session?.access_token ?? null);
  });
  return () => data.subscription.unsubscribe();
}
