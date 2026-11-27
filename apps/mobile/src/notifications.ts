// "Are you OK?" as a notification with two buttons, so the student can answer without opening the
// app. Answers go back over the socket like the in-app card.
import * as Notifications from "expo-notifications";
import { SERVER } from "./client";

export const ARE_YOU_OK = "are_you_ok";
export type OkAnswer = "ok" | "call_me";

export function registerAreYouOk(): void {
  Notifications.setNotificationCategoryAsync(ARE_YOU_OK, [
    { identifier: "ok", buttonTitle: "I'm OK", options: { opensAppToForeground: false } },
    { identifier: "call_me", buttonTitle: "Call me", options: { opensAppToForeground: true } },
  ]).catch(() => {});
}

export function notifyAreYouOk(from: string, requestId: string): void {
  Notifications.scheduleNotificationAsync({
    content: {
      title: `${from} is asking: are you OK?`,
      body: "Answer here. They hear only if you don't answer within 10 minutes.",
      categoryIdentifier: ARE_YOU_OK,
      data: { request_id: requestId },
    },
    trigger: null,
  }).catch(() => {});
}

/** A pushed "Are you OK?" carries its own single-use answer token: the answer goes straight to
 * the server, so it works while the app is closed or the socket is down. */
async function answerByToken(requestId: string, token: string, answer: OkAnswer): Promise<boolean> {
  try {
    const response = await fetch(`${SERVER}/api/ok/${encodeURIComponent(requestId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, answer }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

function handle(response: Notifications.NotificationResponse, onAnswer: (requestId: string, answer: OkAnswer) => void): void {
  const action = response.actionIdentifier;
  const data = response.notification.request.content.data ?? {};
  const requestId = data.request_id;
  if (typeof requestId !== "string" || (action !== "ok" && action !== "call_me")) return;
  if (typeof data.answer_token === "string") {
    void answerByToken(requestId, data.answer_token, action).then((sent) => {
      if (!sent) onAnswer(requestId, action); // fall back to the socket when the app is open
    });
  } else {
    onAnswer(requestId, action); // the open app's own local notification
  }
}

/** Calls onAnswer for in-app answers; pushed answers go to the server by themselves. Also handles
 * the answer that launched the app from the lock screen. Returns the unsubscribe function. */
export function onAreYouOkAnswer(onAnswer: (requestId: string, answer: OkAnswer) => void): () => void {
  Notifications.getLastNotificationResponseAsync()
    .then((last) => last && handle(last, onAnswer))
    .catch(() => {});
  const subscription = Notifications.addNotificationResponseReceivedListener((response) => handle(response, onAnswer));
  return () => subscription.remove();
}
