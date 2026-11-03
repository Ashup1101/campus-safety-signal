import "./global.css";
import { StatusBar } from "expo-status-bar";
import { useState } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";
import type { Session } from "./src/client";
import { Login } from "./src/screens/Login";
import { StudentHome } from "./src/screens/StudentHome";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  return (
    <SafeAreaProvider>
      <StatusBar style="auto" />
      {session ? (
        <StudentHome key={session.account.id} session={session} onLeave={() => setSession(null)} />
      ) : (
        <Login onSession={setSession} />
      )}
    </SafeAreaProvider>
  );
}
