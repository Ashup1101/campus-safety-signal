import { HeartHandshake, LogOut } from "lucide-react-native";
import { useState } from "react";
import { Pressable, ScrollView, Text, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useSocket, type Session } from "../client";
import type { Student } from "../shared/api";

// The parent's screens: only what this parent is linked to. No switching between parents.
export function ParentHome({ session, onLeave }: { session: Session; onLeave: () => void }) {
  const dark = useColorScheme() === "dark";
  const muted = dark ? "#c9bba9" : "#5c4f4a";
  const [students, setStudents] = useState<Student[]>([]);
  const { connected } = useSocket(session.token, (message) => {
    if (message.type === "hello") setStudents(message.students ?? []);
  });
  return (
    <SafeAreaView className="flex-1 bg-background dark:bg-background-dark">
      <View className="flex-row items-center justify-between px-4 py-3">
        <View>
          <Text className="text-lg font-semibold text-foreground dark:text-foreground-dark">{session.account.name}</Text>
          <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
            Parent · {connected ? "connected" : "connecting…"}
          </Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="Sign out" onPress={onLeave} className="min-h-11 min-w-11 items-center justify-center">
          <LogOut size={18} color={muted} />
        </Pressable>
      </View>
      <ScrollView contentContainerClassName="px-4 pb-10">
        {students.length === 0 ? (
          <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">
            No student linked yet. Invite your student from Settings; they decide whether to accept.
          </Text>
        ) : (
          students.map((s) => (
            <View key={s.id} className="mt-3 flex-row items-center gap-2 rounded-xl bg-card p-4 dark:bg-card-dark">
              <HeartHandshake size={18} color={muted} />
              <Text className="font-semibold text-foreground dark:text-foreground-dark">{s.name}</Text>
              <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">
                {s.sharing === "on" ? "sharing now" : s.sharing === "paused" ? "sharing paused" : "not sharing"}
              </Text>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
