import { useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import { SERVER } from "../client";

const WEB = process.env.EXPO_PUBLIC_DEMO_WEB ?? "http://localhost:3100";

/** On every screen: not IU, the draft policy and terms, and when the public data was last updated. */
export function AppFooter() {
  const [updated, setUpdated] = useState<string | null>(null);
  useEffect(() => {
    fetch(`${SERVER}/api/data-updated`)
      .then((r) => r.json())
      .then((d: { updated_at: string | null }) => setUpdated(d.updated_at))
      .catch(() => {});
  }, []);
  return (
    <View className="flex-row flex-wrap gap-x-3 bg-background px-4 py-2 dark:bg-background-dark">
      <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
        Not an official IU service. Data updated {updated ? new Date(updated).toLocaleDateString() : "unknown"}.
      </Text>
      {(
        [
          ["Privacy (draft)", "/privacy"],
          ["Terms (draft)", "/terms"],
        ] as const
      ).map(([label, path]) => (
        <Pressable key={path} accessibilityRole="link" onPress={() => Linking.openURL(`${WEB}${path}`)}>
          <Text className="text-xs underline text-muted-foreground dark:text-muted-foreground-dark">{label}</Text>
        </Pressable>
      ))}
    </View>
  );
}
