import "./global.css";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { Pressable, Text } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { onNewToken, signOut } from "./src/auth";
import { turnOffPush } from "./src/push";
import type { Session } from "./src/client";
import { AppFooter } from "./src/components/AppFooter";
import { Login } from "./src/screens/Login";
import { ParentHome } from "./src/screens/ParentHome";
import { Settings } from "./src/screens/Settings";
import { StudentHome } from "./src/screens/StudentHome";

// One app; the signed-in role decides the screens. Students never see parent screens and parents
// never see student screens. The IUPD console is a separate website and never opens here.
function Screens({ session, onLeave }: { session: Session; onLeave: () => void }) {
  const [settings, setSettings] = useState(false);
  if (session.account.role !== "console" && settings) {
    return <Settings session={session} onBack={() => setSettings(false)} onDeleted={onLeave} />;
  }
  if (session.account.role === "student") {
    return <StudentHome key={session.account.id} session={session} onLeave={onLeave} onSettings={() => setSettings(true)} />;
  }
  if (session.account.role === "parent") {
    return <ParentHome key={session.account.id} session={session} onLeave={onLeave} onSettings={() => setSettings(true)} />;
  }
  return (
    <SafeAreaView className="flex-1 justify-center bg-background px-6 dark:bg-background-dark">
      <Text className="text-lg font-semibold text-foreground dark:text-foreground-dark">The IUPD console is on the website.</Text>
      <Pressable accessibilityRole="button" onPress={onLeave} className="mt-4 min-h-11 justify-center">
        <Text className="underline text-foreground dark:text-foreground-dark">Back</Text>
      </Pressable>
    </SafeAreaView>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  // Supabase renews the sign-in about hourly; a sign-out elsewhere ends the session here too.
  useEffect(() => onNewToken((token) => setSession((s) => (s && token ? { ...s, token } : null))), []);
  const leave = () => {
    // Signing out stops alerts to this phone for this account (the consent itself stays).
    if (session) void turnOffPush(session.token, false);
    setSession(null);
    void signOut();
  };
  return (
    <SafeAreaProvider>
      <StatusBar style="auto" />
      {session ? <Screens session={session} onLeave={leave} /> : <Login onSession={setSession} />}
      <AppFooter />
    </SafeAreaProvider>
  );
}
