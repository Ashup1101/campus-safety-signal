import { Pressable, Text, View } from "react-native";
import { CONSENT_TEXT, type ConsentKind } from "../consents";

/** Asked the first time a feature is used. Yes and No look the same: no nudging. */
export function ConsentSheet({ kind, onChoose }: { kind: ConsentKind; onChoose: (granted: boolean) => void }) {
  const { title, body } = CONSENT_TEXT[kind];
  return (
    <View accessibilityViewIsModal className="mt-3 rounded-xl border border-border bg-card p-4 dark:border-border-dark dark:bg-card-dark">
      <Text accessibilityRole="header" className="text-base font-semibold text-foreground dark:text-foreground-dark">
        {title}
      </Text>
      <Text className="mt-1 text-sm text-foreground dark:text-foreground-dark">{body}</Text>
      <Text className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground-dark">
        You can change this anytime in Settings. Draft policy: needs legal review.
      </Text>
      <View className="mt-3 flex-row gap-2">
        {(
          [
            [true, "Yes"],
            [false, "No"],
          ] as const
        ).map(([granted, label]) => (
          <Pressable
            key={label}
            accessibilityRole="button"
            onPress={() => onChoose(granted)}
            className="min-h-12 flex-1 items-center justify-center rounded-full border border-border px-4 dark:border-border-dark"
          >
            <Text className="text-base text-foreground dark:text-foreground-dark">{label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
