import { useEffect, useState } from "react";
import { Switch, Text, View } from "react-native";
import { CONSENT_TEXT, consentsApi, type Consent, type ConsentKind } from "../consents";

const BY_ROLE: Record<"student" | "parent", ConsentKind[]> = {
  student: ["location_precise", "sharing", "notes", "digests", "briefings"],
  parent: ["digests", "briefings"],
};

/** Every consent with a switch: turning one off withdraws it and stops the feature at once. */
export function YourChoices({ token, role }: { token: string; role: "student" | "parent" }) {
  const [found, setFound] = useState<Consent[]>([]);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    consentsApi.list(token).then(setFound, () => {});
  }, [token]);
  const change = async (kind: ConsentKind, granted: boolean) => {
    await consentsApi.choose(token, kind, granted).catch(() => null);
    setFound(await consentsApi.list(token).catch(() => found));
    setNote(
      granted && (kind === "digests" || kind === "briefings")
        ? "Check your inbox for a confirm link."
        : granted
          ? null
          : "Turned off. It stops right away.",
    );
  };
  return (
    <View className="gap-3">
      {BY_ROLE[role].map((kind) => {
        const state = found.find((c) => c.kind === kind)?.state ?? "not_asked";
        return (
          <View key={kind} className="flex-row items-center gap-3">
            <Text className="flex-1 text-foreground dark:text-foreground-dark">
              {CONSENT_TEXT[kind].title.replace("?", "")}
            </Text>
            <Switch
              accessibilityLabel={CONSENT_TEXT[kind].title}
              value={state === "granted"}
              onValueChange={(value) => change(kind, value)}
            />
          </View>
        );
      })}
      {note && <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
    </View>
  );
}
