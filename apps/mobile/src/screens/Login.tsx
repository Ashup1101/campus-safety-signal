import { Shield, UserRound } from "lucide-react-native";
import { useState } from "react";
import { Pressable, Text, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { login, type Session } from "../client";

const STUDENTS = [
  { id: "student_sam", name: "Sam", note: "Linked to Mom" },
  { id: "student_alex", name: "Alex", note: "Linked to Dad" },
];

// Demo logins only: test accounts on the local demo server.
export function Login({ onSession }: { onSession: (session: Session) => void }) {
  const dark = useColorScheme() === "dark";
  const [error, setError] = useState<string | null>(null);
  const primary = dark ? "#6cc6b8" : "#3f9a8e";
  const choose = (id: string) =>
    login(id).then(onSession, () => setError("The demo server is not running. Start it with `make demo`."));
  return (
    <SafeAreaView className="flex-1 justify-center bg-background px-6 dark:bg-background-dark">
      <Shield size={32} color={primary} />
      <Text className="mt-3 text-2xl font-semibold text-foreground dark:text-foreground-dark">
        Campus Safety Signal
      </Text>
      <Text className="mb-6 mt-1 text-muted-foreground dark:text-muted-foreground-dark">
        Demo with test accounts. Pick a student.
      </Text>
      {STUDENTS.map((student) => (
        <Pressable
          key={student.id}
          onPress={() => choose(student.id)}
          className="mb-3 flex-row items-center rounded-xl border border-border bg-card p-4 dark:border-border-dark dark:bg-card-dark"
        >
          <UserRound size={20} color={primary} />
          <View className="ml-3">
            <Text className="font-semibold text-foreground dark:text-foreground-dark">{student.name}</Text>
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{student.note}</Text>
          </View>
        </Pressable>
      ))}
      {error && <Text className="mt-2 text-sm text-muted-foreground dark:text-muted-foreground-dark">{error}</Text>}
    </SafeAreaView>
  );
}
