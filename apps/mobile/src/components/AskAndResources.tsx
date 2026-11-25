import { useState } from "react";
import { Linking, Pressable, Text, TextInput, View } from "react-native";
import { apiSend } from "../client";

const RESOURCES = [
  { label: "IU Notify alerts and the Guardian app", url: "https://protect.iu.edu/emergency-continuity/emergency-alerts/guardian-app.html" },
  { label: "IU Bloomington emergency contacts and night escort", url: "https://protect.iu.edu/emergency-continuity/emergency-contacts/iub.html" },
  { label: "IU's live alert page", url: "https://emergency.iu.edu/rave/index.html" },
];

interface Answer {
  answer: string;
  citations: string[];
  ai: boolean;
  notice?: string;
}

// Questions about past incidents, answered only from the public data with numbered citations.
export function Ask({ token }: { token: string }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const ask = async () => {
    const response = await apiSend("/api/ask", token, "POST", { question });
    if (response.ok) {
      setNote(null);
      setAnswer((await response.json()) as Answer);
    } else {
      setNote(response.status === 429 ? "That's 20 questions today. Try again tomorrow." : "Questions are not available right now.");
    }
  };
  return (
    <View>
      <TextInput
        accessibilityLabel="Your question"
        placeholder="e.g. What happened near Kirkwood on Halloween?"
        value={question}
        onChangeText={setQuestion}
        className="rounded-xl border border-border px-4 py-3 text-foreground dark:border-border-dark dark:text-foreground-dark"
      />
      <Pressable accessibilityRole="button" onPress={ask} className="mt-2 min-h-11 items-center justify-center rounded-full bg-muted dark:bg-muted-dark">
        <Text className="font-medium text-foreground dark:text-foreground-dark">Ask</Text>
      </Pressable>
      {note && <Text className="mt-2 text-sm text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
      {answer && (
        <View className="mt-3">
          {answer.notice && <Text className="mb-1 text-xs text-muted-foreground dark:text-muted-foreground-dark">{answer.notice}</Text>}
          <Text className="text-sm text-foreground dark:text-foreground-dark">{answer.answer}</Text>
          {answer.citations.map((c, n) => (
            <Text key={c} className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground-dark">
              [{n + 1}] {c}
            </Text>
          ))}
        </View>
      )}
    </View>
  );
}

export function Resources() {
  return (
    <View>
      <Text className="mb-2 text-sm font-semibold text-foreground dark:text-foreground-dark">In an emergency, call 911.</Text>
      {RESOURCES.map((r) => (
        <Pressable key={r.url} accessibilityRole="link" onPress={() => Linking.openURL(r.url)} className="min-h-11 justify-center">
          <Text className="underline text-foreground dark:text-foreground-dark">{r.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}
