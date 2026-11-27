import { LocateFixed } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Switch, Text, View } from "react-native";
import { sessionRunning, startSession, stopSession } from "../background";
import { CONSENT_TEXT, consentsApi } from "../consents";
import { HOME, HOME_RADIUS_M } from "../geo";
import type { SegmentFeature, TimeWindow } from "../shared/api";
import { ui } from "./ui";

/** Keep "Share until I'm home" and heads-ups working with the app closed (development build).
 * Turning it on is the background-location consent; it ends by itself within 2 hours. */
export function BackgroundSession({
  token,
  features,
  windows,
  color,
}: {
  token: string;
  features: SegmentFeature[];
  windows: TimeWindow[];
  color: string;
}) {
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    sessionRunning().then(setRunning, () => {});
  }, []);
  const change = async (on: boolean) => {
    if (!on) {
      await stopSession();
      await consentsApi.choose(token, "background_location", false).catch(() => null);
      setRunning(false);
      setNote("Stopped. Nothing was saved.");
      return;
    }
    await consentsApi.choose(token, "background_location", true).catch(() => null);
    const problem = await startSession(token, "home", { ...HOME, radius_m: HOME_RADIUS_M }, features, windows);
    setRunning(problem === null);
    setNote(problem ?? "Running for up to 2 hours. It stops when you get home.");
  };
  return (
    <View className={ui.card}>
      <View className="flex-row items-center gap-3">
        <Text className="flex-1 font-semibold text-foreground dark:text-foreground-dark">Keep working when the app is closed</Text>
        <Switch accessibilityLabel="Keep working when the app is closed" value={running} onValueChange={change} />
      </View>
      {running ? (
        <View className="mt-2 flex-row items-center" accessibilityLabel="Location in use">
          <LocateFixed size={14} color={color} />
          <Text className="ml-1.5 text-sm font-medium text-foreground dark:text-foreground-dark">Location in use</Text>
        </View>
      ) : (
        <Text className={`mt-2 ${ui.note}`}>{CONSENT_TEXT.background_location.body}</Text>
      )}
      {note && <Text className={`mt-1 ${ui.note}`}>{note}</Text>}
    </View>
  );
}
