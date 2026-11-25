import { useCallback, useEffect, useRef, useState } from "react";
import type { Account, ClientMessage, ServerMessage } from "./shared/api";

// The iPhone Simulator shares the Mac's network, so the local demo server is at localhost.
export const SERVER = process.env.EXPO_PUBLIC_DEMO_SERVER ?? "http://localhost:8100";

export interface Session {
  token: string;
  account: Account;
}

export async function login(accountId: string): Promise<Session> {
  const response = await fetch(`${SERVER}/api/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId }),
  });
  if (!response.ok) throw new Error(`login ${response.status}`);
  return (await response.json()) as Session;
}

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${SERVER}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Sign-up and sign-in send a one-time link to the account's mailbox; the link signs in once.
export async function signUp(email: string, role: "student" | "parent", name: string): Promise<string | null> {
  const response = await post("/api/signup", { email, role, display_name: name });
  if (response.status === 202) return null;
  if (response.status === 409) return "An account already uses this email. Ask for a sign-in link instead.";
  return "Check the email and the name (1 to 40 characters).";
}

export async function requestLink(email: string): Promise<string | null> {
  const response = await post("/api/signin", { email });
  return response.status === 429 ? "Too many links this hour. Try again later." : null;
}

export async function signInWithLink(link: string): Promise<Session> {
  const token = link.trim().split("/magic/").pop()?.split(/[\s?#]/)[0] ?? "";
  const response = await fetch(`${SERVER}/api/magic/${encodeURIComponent(token)}`);
  if (!response.ok) throw new Error("This sign-in link is not valid any more. Ask for a new one.");
  return (await response.json()) as Session;
}

export async function api<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${SERVER}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return (await response.json()) as T;
}

export async function apiSend(
  path: string,
  token: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<Response> {
  return fetch(`${SERVER}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

type Send = (message: ClientMessage) => void;

export function useSocket(token: string, onMessage: (message: ServerMessage, send: Send) => void) {
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
