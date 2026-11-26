// The person's consent choices, kept on the server (with version and time).
import { api, apiSend } from "./client";

export type ConsentKind = "location_precise" | "sharing" | "notes" | "digests" | "briefings";
export type ConsentState = "not_asked" | "granted" | "declined" | "withdrawn";

export interface Consent {
  kind: ConsentKind;
  state: ConsentState;
  version: string;
}

export const CONSENT_TEXT: Record<ConsentKind, { title: string; body: string }> = {
  location_precise: {
    title: "Use your precise location?",
    body: "Your phone uses its location for heads-ups and to answer check-ins with one word. Your location is never saved. Without it you still get official alerts.",
  },
  sharing: {
    title: "Share your location with your family?",
    body: "Only when you turn sharing on, only with the family you linked, only while they are looking. Never saved. You can pause anytime.",
  },
  notes: {
    title: "Post community notes?",
    body: "Notes show without your name, only after other students nearby agree. No names, descriptions of people, links or contact details.",
  },
  digests: {
    title: "Get morning digests?",
    body: "A short summary for your watch zones at 7 am. We send a confirm link first, and every message has a one-click unsubscribe.",
  },
  briefings: {
    title: "Get event-night briefings?",
    body: "A heads-up the afternoon before an event night. We send a confirm link first, and every message has a one-click unsubscribe.",
  },
};

export const consentsApi = {
  list: (token: string) => api<Consent[]>("/api/consents", token),
  choose: (token: string, kind: ConsentKind, granted: boolean) =>
    apiSend(`/api/consents/${kind}`, token, "POST", { granted }),
};
