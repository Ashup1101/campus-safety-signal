// Alerts on this phone (v14): after the "push" consent the app asks iOS for permission, gets the
// phone's Expo push address and gives it to the server, which deletes it when push is turned off
// or the account is deleted. The address is kept on the phone only to turn push off again.
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import { apiSend } from "./client";
import { consentsApi } from "./consents";

const KEY = "push_token";
const PROJECT_ID = process.env.EXPO_PUBLIC_EAS_PROJECT_ID; // set for a real phone (owner step)

export type PushResult = { on: boolean; note: string | null };

export async function turnOnPush(session: string): Promise<PushResult> {
  await consentsApi.choose(session, "push", true);
  const permission = await Notifications.requestPermissionsAsync();
  if (!permission.granted) {
    return { on: false, note: "Notifications are off for this app. Turn them on in iOS Settings." };
  }
  let address: string;
  try {
    address = (await Notifications.getExpoPushTokenAsync(PROJECT_ID ? { projectId: PROJECT_ID } : undefined)).data;
  } catch {
    return {
      on: false,
      note: "This phone cannot get alerts while the app is closed (the Simulator cannot). Alerts still arrive while the app is open.",
    };
  }
  const response = await apiSend("/api/devices", session, "POST", { expo_token: address, platform: "ios" });
  if (!response.ok) {
    return { on: false, note: response.status === 409 ? "Up to 5 phones. Turn alerts off on another phone first." : "Could not turn alerts on. Try again." };
  }
  await SecureStore.setItemAsync(KEY, address);
  return { on: true, note: "Alerts will reach this phone even when the app is closed." };
}

/** Forgets this phone on the server; withdraw=true also withdraws the consent (every phone). */
export async function turnOffPush(session: string, withdraw: boolean): Promise<void> {
  const address = await SecureStore.getItemAsync(KEY);
  if (address) await apiSend("/api/devices", session, "DELETE", { expo_token: address }).catch(() => null);
  await SecureStore.deleteItemAsync(KEY);
  if (withdraw) await consentsApi.choose(session, "push", false).catch(() => null);
}

export async function pushIsOn(): Promise<boolean> {
  return (await SecureStore.getItemAsync(KEY)) !== null;
}
