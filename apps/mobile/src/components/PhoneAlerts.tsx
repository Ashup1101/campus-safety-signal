import { useEffect, useState } from "react";
import { Switch, Text, View } from "react-native";
import { pushIsOn, turnOffPush, turnOnPush } from "../push";

/** "Alerts on this phone": on = consent + this phone registered; off = forgotten + withdrawn. */
export function PhoneAlerts({ token }: { token: string }) {
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    pushIsOn().then(setOn, () => {});
  }, []);
  const change = async (value: boolean) => {
    setBusy(true);
    if (value) {
      const result = await turnOnPush(token).catch(() => ({ on: false, note: "Could not turn alerts on. Try again." }));
      setOn(result.on);
      setNote(result.note);
    } else {
      await turnOffPush(token, true);
      setOn(false);
      setNote("Turned off. This phone gets alerts only while the app is open.");
    }
    setBusy(false);
  };
  return (
    <View className="gap-2">
      <View className="flex-row items-center gap-3">
        <Text className="flex-1 text-foreground dark:text-foreground-dark">Official alerts, updates and "Are you OK?" when the app is closed</Text>
        <Switch accessibilityLabel="Alerts on this phone" value={on} disabled={busy} onValueChange={change} />
      </View>
      {note && <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
    </View>
  );
}
