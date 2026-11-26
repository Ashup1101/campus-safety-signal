// What the student keeps on this phone only (secure store): the demo signing key, the home area
// and the reassurance switches. None of it is sent to the server except a band word on request.
import * as SecureStore from "expo-secure-store";
import type { Area } from "./shared/api";

export interface Reassurance {
  bandAnswers: boolean; // a linked parent may ask "roughly where?"
  areYouOk: boolean;
  arrivedHome: boolean;
}

export const DEFAULTS: Reassurance = { bandAnswers: false, areYouOk: true, arrivedHome: false };

async function read<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await SecureStore.getItemAsync(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

async function write(key: string, value: unknown): Promise<void> {
  try {
    await SecureStore.setItemAsync(key, JSON.stringify(value));
  } catch {
    // no secure store (web preview): the value lasts for this session only
  }
}

export const signingKey = {
  get: () => read<{ key_id: string; secret: string } | null>("signing_key", null),
  set: (key: { key_id: string; secret: string }) => write("signing_key", key),
};

export const homeArea = {
  get: () => read<Area | null>("home_area", null),
  set: (area: Area) => write("home_area", area),
};

export const reassurance = {
  get: () => read<Reassurance>("reassurance", DEFAULTS),
  set: (value: Reassurance) => write("reassurance", value),
};
