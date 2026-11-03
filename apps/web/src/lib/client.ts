"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { Account, ClientMessage, ServerMessage } from "@/shared/api";
import tokens from "@/shared/tokens.json";

export const SERVER = process.env.NEXT_PUBLIC_DEMO_SERVER ?? "http://127.0.0.1:8000";

export interface Session {
  token: string;
  account: Account;
}

export async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${SERVER}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return (await response.json()) as T;
}

// Demo logins only: every demo account is a test account on the local server.
export function useSession(accountId: string): { session: Session | null; error: string | null } {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetch(`${SERVER}/api/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accountId }),
    })
      .then((r) => (r.ok ? (r.json() as Promise<Session>) : Promise.reject(new Error(`${r.status}`))))
      .then(
        (s) => live && setSession(s),
        () => live && setError("The demo server is not running. Start it with `make demo`."),
      );
    return () => {
      live = false;
    };
  }, [accountId]);
  return { session, error };
}

type Send = (message: ClientMessage) => void;

export function useSocket(
  token: string | undefined,
  onMessage: (message: ServerMessage, send: Send) => void,
) {
  const handler = useRef(onMessage);
  const socket = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const send = useCallback<Send>((message) => {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify(message));
  }, []);
  useEffect(() => {
    handler.current = onMessage;
  });
  useEffect(() => {
    if (!token) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const open = () => {
      const ws = new WebSocket(`${SERVER.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(token)}`);
      socket.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (event) => handler.current(JSON.parse(String(event.data)) as ServerMessage, send);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(open, 1500);
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [token, send]);
  return { send, connected };
}

const DARK = "(prefers-color-scheme: dark)";

function subscribeDark(change: () => void) {
  const query = window.matchMedia(DARK);
  query.addEventListener("change", change);
  return () => query.removeEventListener("change", change);
}

export function useDark(): boolean {
  return useSyncExternalStore(
    subscribeDark,
    () => window.matchMedia(DARK).matches,
    () => false,
  );
}

type Colored = { light: string; dark: string };

export function color(entry: Colored, dark: boolean): string {
  return dark ? entry.dark : entry.light;
}

export { tokens };
