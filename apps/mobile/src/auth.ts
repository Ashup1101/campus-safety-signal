import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import * as Linking from "expo-linking";
import { SERVER, type Session } from "./client";
import type { Account } from "./shared/api";

// AUTH_MODE=supabase: a Supabase magic link from the person's real inbox opens the app with a
// session; the server checks that session itself. Anything else: the demo's own sign-in.
export const AUTH_MODE = process.env.EXPO_PUBLIC_AUTH_MODE === "supabase" ? "supabase" : "demo";
const PROJECT_URL = process.env.EXPO_PUBLIC_SUPABASE_URL ?? "";
const ANON_KEY = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? ""; // public by design; RLS blocks it

let client: SupabaseClient | null = null;
export function supabase(): SupabaseClient {
  client ??= createClient(PROJECT_URL, ANON_KEY, {
    auth: { flowType: "implicit", persistSession: false, autoRefreshToken: true, detectSessionInUrl: false },
  });
  return client;
}

/** Where the email link returns: the app's own deep link (Expo Go uses exp://, a built app its scheme). */
export const REDIRECT = Linking.createURL("auth-callback");

export async function emailLink(email: string): Promise<string | null> {
  const { error } = await supabase().auth.signInWithOtp({
    email: email.trim(),
    options: { emailRedirectTo: REDIRECT },
  });
  return error ? "We could not send the link. Check the email and try again in a minute." : null;
}

/** The access token from an opened link (#access_token=...&refresh_token=...), or null. */
export async function tokenFromLink(url: string): Promise<string | null> {
  const fragment = new URLSearchParams(url.split("#")[1] ?? "");
  const access = fragment.get("access_token");
  const refresh = fragment.get("refresh_token");
  if (!access || !refresh) return null;
  const { data, error } = await supabase().auth.setSession({ access_token: access, refresh_token: refresh });
  return error ? null : (data.session?.access_token ?? null);
}

export type ServerState = { state: "choose_role" } | { state: "active"; account: Account };

export async function serverState(token: string): Promise<ServerState> {
  const response = await fetch(`${SERVER}/api/session`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error("This sign-in link has expired. Ask for a new one.");
  return (await response.json()) as ServerState;
}

export async function chooseRole(token: string, role: "student" | "parent", name: string): Promise<Session> {
  const response = await fetch(`${SERVER}/api/me/role`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ role, display_name: name.trim() }),
  });
  if (!response.ok) throw new Error("Add your name (1 to 40 characters) and choose one.");
  return { token, account: (await response.json()) as Account };
}

/** Supabase renews the access token about hourly; the app keeps using the newest one. */
export function onNewToken(update: (token: string | null) => void): () => void {
  if (AUTH_MODE !== "supabase") return () => {};
  const { data } = supabase().auth.onAuthStateChange((event, session) => {
    if (event === "TOKEN_REFRESHED" || event === "SIGNED_OUT") update(session?.access_token ?? null);
  });
  return () => data.subscription.unsubscribe();
}

export async function signOut(): Promise<void> {
  if (AUTH_MODE === "supabase") await supabase().auth.signOut();
}
