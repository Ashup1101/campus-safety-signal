// The background location task (v15, development build only): while a session runs, iOS wakes the
// app with location updates; the session rules (session.ts) run here on the phone and only events
// go to the server. Balanced accuracy, 50 m distance filter, deferred updates; it stops by itself.
import * as Battery from "expo-battery";
import * as Location from "expo-location";
import * as SecureStore from "expo-secure-store";
import * as TaskManager from "expo-task-manager";
import { SERVER } from "./client";
import { highSegmentHere } from "./geo";
import { onLocation, start, stop, type Home, type SessionEvent, type SessionKind, type SessionState } from "./session";
import type { SegmentFeature, TimeWindow } from "./shared/api";

export const TASK = "campus-safety-session";
const STATE = "session_state"; // on this phone only (keychain); deleted when the session ends
const TOKEN = "session_token";

// Busier streets for heads-ups, kept in memory while the app process lives.
let busy: { features: SegmentFeature[]; windows: TimeWindow[] } = { features: [], windows: [] };

async function send(token: string, sessionId: string, event: SessionEvent | { kind: "started" }): Promise<void> {
  await fetch(`${SERVER}/api/sessions/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ session_id: sessionId, ...event }),
  }).catch(() => null);
}

async function finish(): Promise<void> {
  if (await Location.hasStartedLocationUpdatesAsync(TASK).catch(() => false)) {
    await Location.stopLocationUpdatesAsync(TASK).catch(() => null);
  }
  await SecureStore.deleteItemAsync(STATE);
}

TaskManager.defineTask<{ locations: Location.LocationObject[] }>(TASK, async ({ data, error }) => {
  if (error || !data) return;
  const raw = await SecureStore.getItemAsync(STATE);
  const token = await SecureStore.getItemAsync(TOKEN);
  if (!raw || !token) return finish();
  let state = JSON.parse(raw) as SessionState;
  const battery = await Battery.getBatteryLevelAsync().catch(() => -1);
  const busyAt = (p: { lat: number; lon: number }) =>
    highSegmentHere(p, busy.features, busy.windows)?.feature.properties.id ?? null;
  for (const location of data.locations) {
    const point = { lat: location.coords.latitude, lon: location.coords.longitude };
    const result = onLocation(state, point, location.timestamp, battery, busyAt);
    state = result.state;
    for (const event of result.events) await send(token, state.id, event);
    if (state.ended) break;
  }
  if (state.ended) await finish();
  else await SecureStore.setItemAsync(STATE, JSON.stringify(state));
});

function newId(): string {
  return Array.from({ length: 16 }, () => "abcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 36)]).join("");
}

/** Starts a session; returns a plain note when it cannot run in the background (null = running). */
export async function startSession(
  sessionToken: string,
  kind: SessionKind,
  home: Home | null,
  features: SegmentFeature[],
  windows: TimeWindow[],
): Promise<string | null> {
  if (!(await TaskManager.isAvailableAsync())) {
    return "Expo Go cannot do this with the app closed; it keeps working while the app is open.";
  }
  if (!(await Location.requestForegroundPermissionsAsync()).granted) return "Location is off for this app.";
  if (!(await Location.requestBackgroundPermissionsAsync()).granted) {
    return 'Without "Always" location this works only while the app is open.';
  }
  busy = { features, windows };
  const state = start(newId(), kind, Date.now(), home);
  await SecureStore.setItemAsync(TOKEN, sessionToken);
  await SecureStore.setItemAsync(STATE, JSON.stringify(state));
  await send(sessionToken, state.id, { kind: "started" });
  await Location.startLocationUpdatesAsync(TASK, {
    accuracy: Location.Accuracy.Balanced,
    distanceInterval: 50,
    deferredUpdatesDistance: 100,
    deferredUpdatesInterval: 60_000,
    pausesUpdatesAutomatically: true,
    activityType: Location.ActivityType.Fitness,
    showsBackgroundLocationIndicator: true, // iOS shows the blue location pill
  });
  return null;
}

export async function stopSession(): Promise<void> {
  const raw = await SecureStore.getItemAsync(STATE);
  const token = await SecureStore.getItemAsync(TOKEN);
  if (raw && token) {
    const { state, events } = stop(JSON.parse(raw) as SessionState);
    for (const event of events) await send(token, state.id, event);
  }
  await finish();
}

export async function sessionRunning(): Promise<boolean> {
  return (await SecureStore.getItemAsync(STATE)) !== null;
}

/** Supabase renews the sign-in about hourly: a running session keeps using the newest token. */
export async function updateSessionToken(token: string): Promise<void> {
  if (await sessionRunning()) await SecureStore.setItemAsync(TOKEN, token);
}

/** Sign-out: the session ends and its token leaves the keychain. */
export async function forgetSession(): Promise<void> {
  await stopSession();
  await SecureStore.deleteItemAsync(TOKEN);
}
