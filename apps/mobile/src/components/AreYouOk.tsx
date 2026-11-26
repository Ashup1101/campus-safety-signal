import { Pressable, Text, View } from "react-native";

/** A gentle "Are you OK?" from a linked parent: the student answers before anyone else hears. */
export function AreYouOk({ from, onAnswer }: { from: string; onAnswer: (answer: "ok" | "call_me") => void }) {
  return (
    <View
      accessibilityRole="alert"
      className="mt-3 rounded-xl border border-border bg-card p-4 dark:border-border-dark dark:bg-card-dark"
    >
      <Text className="font-semibold text-foreground dark:text-foreground-dark">{from} is asking: are you OK?</Text>
      <Text className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground-dark">
        {from} hears your answer. Only if you don&apos;t answer within 10 minutes are they told &quot;No answer yet&quot;.
      </Text>
      <View className="mt-3 flex-row gap-2">
        {(
          [
            ["ok", "I'm OK"],
            ["call_me", "Call me"],
          ] as const
        ).map(([answer, label]) => (
          <Pressable
            key={answer}
            accessibilityRole="button"
            onPress={() => onAnswer(answer)}
            className="min-h-12 flex-1 items-center justify-center rounded-full border border-border px-4 dark:border-border-dark"
          >
            <Text className="text-base text-foreground dark:text-foreground-dark">{label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
