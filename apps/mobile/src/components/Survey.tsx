import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api, apiSend } from "../client";

interface Due {
  prompt: string;
  questions: string[];
}

const SCALE = [1, 2, 3, 4, 5] as const;

/** One short survey at a time: three 1-5 answers or Skip. Only the numbers are sent. */
export function Survey({ token }: { token: string }) {
  const [due, setDue] = useState<Due | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([null, null, null]);
  const [thanks, setThanks] = useState(false);

  useEffect(() => {
    api<Due[]>("/api/surveys/due", token).then((found) => setDue(found[0] ?? null), () => {});
  }, [token]);

  if (thanks) {
    return <Text className="mt-3 text-sm text-muted-foreground dark:text-muted-foreground-dark">Thanks for the feedback.</Text>;
  }
  if (!due) return null;
  const send = async (skip: boolean) => {
    const body = skip ? { skip: true } : { answers };
    await apiSend(`/api/surveys/${encodeURIComponent(due.prompt)}`, token, "POST", body).catch(() => null);
    setDue(null);
    setThanks(!skip);
  };
  const complete = answers.every((a) => a !== null);
  return (
    <View className="mt-3 gap-3 rounded-xl border border-border bg-card p-4 dark:border-border-dark dark:bg-card-dark">
      <Text accessibilityRole="header" className="font-semibold text-foreground dark:text-foreground-dark">
        Three quick questions (optional)
      </Text>
      {due.questions.map((question, i) => (
        <View key={question} accessibilityRole="radiogroup" accessibilityLabel={question} className="gap-1">
          <Text className="text-sm text-foreground dark:text-foreground-dark">{question}</Text>
          <View className="flex-row gap-1">
            {SCALE.map((n) => (
              <Pressable
                key={n}
                accessibilityRole="radio"
                accessibilityState={{ checked: answers[i] === n }}
                accessibilityLabel={`${n} of 5${n === 1 ? ", disagree" : n === 5 ? ", agree" : ""}`}
                onPress={() => setAnswers((a) => a.map((v, j) => (j === i ? n : v)))}
                className={`min-h-11 flex-1 items-center justify-center rounded-lg border ${answers[i] === n ? "border-primary" : "border-border dark:border-border-dark"}`}
              >
                <Text className="text-foreground dark:text-foreground-dark">{n}</Text>
              </Pressable>
            ))}
          </View>
          <View className="flex-row justify-between">
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">Disagree</Text>
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">Agree</Text>
          </View>
        </View>
      ))}
      <View className="flex-row gap-2">
        <Pressable
          accessibilityRole="button"
          disabled={!complete}
          onPress={() => send(false)}
          className="min-h-11 flex-1 items-center justify-center rounded-full border border-border dark:border-border-dark"
        >
          <Text className="text-foreground dark:text-foreground-dark">Send</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          onPress={() => send(true)}
          className="min-h-11 flex-1 items-center justify-center rounded-full border border-border dark:border-border-dark"
        >
          <Text className="text-foreground dark:text-foreground-dark">Skip</Text>
        </Pressable>
      </View>
    </View>
  );
}
