// "Are you OK?" as a notification with two buttons, so the student can answer without opening the
// app. Answers go back over the socket like the in-app card.
import * as Notifications from "expo-notifications";

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

/** Calls onAnswer when a notification button is tapped; returns the unsubscribe function. */
export function onAreYouOkAnswer(onAnswer: (requestId: string, answer: OkAnswer) => void): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
    const action = response.actionIdentifier;
    const requestId = response.notification.request.content.data?.request_id;
    if (typeof requestId === "string" && (action === "ok" || action === "call_me")) onAnswer(requestId, action);
  });
  return () => subscription.remove();
}
