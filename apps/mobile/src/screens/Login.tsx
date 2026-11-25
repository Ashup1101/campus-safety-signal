import { Shield, UserRound } from "lucide-react-native";
import { useState } from "react";
import { Pressable, Text, TextInput, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { login, requestLink, signInWithLink, signUp, type Session } from "../client";

// Test accounts on the local demo server, behind the "Demo accounts" button only.
const DEMO = [
  { id: "student_sam", name: "Sam", note: "Student" },
  { id: "student_alex", name: "Alex", note: "Student" },
  { id: "parent_mom", name: "Sam's mom", note: "Parent" },
  { id: "parent_dad", name: "Alex's dad", note: "Parent" },
];
type Mode = "signin" | "signup" | "demo";

function Field(props: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <View className="mb-3">
      <Text className="mb-1 text-sm text-muted-foreground dark:text-muted-foreground-dark">{props.label}</Text>
      <TextInput
        accessibilityLabel={props.label}
        value={props.value}
        onChangeText={props.onChange}
        autoCapitalize="none"
        autoCorrect={false}
        className="rounded-xl border border-border bg-card px-4 py-3 text-foreground dark:border-border-dark dark:bg-card-dark dark:text-foreground-dark"
      />
    </View>
  );
}

function Button({ label, onPress, primary }: { label: string; onPress: () => void; primary?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      className={`mb-3 min-h-11 items-center justify-center rounded-full px-5 py-3 ${primary ? "bg-primary" : "bg-muted dark:bg-muted-dark"}`}
    >
      <Text className={primary ? "font-semibold text-white" : "font-medium text-foreground dark:text-foreground-dark"}>
        {label}
      </Text>
    </Pressable>
  );
}

export function Login({ onSession }: { onSession: (session: Session) => void }) {
  const dark = useColorScheme() === "dark";
  const primary = dark ? "#e8667a" : "#9b1c31";
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"student" | "parent">("student");
  const [link, setLink] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const offline = () => setNote("The demo server is not running. Start it with `make demo`.");
  const sent = "We sent a sign-in link to your mailbox. Paste it below.";

  return (
    <SafeAreaView className="flex-1 justify-center bg-background px-6 dark:bg-background-dark">
      <Shield size={32} color={primary} />
      <Text className="mt-3 text-2xl font-semibold text-foreground dark:text-foreground-dark">Campus Safety Signal</Text>
      <Text className="mb-6 mt-1 text-muted-foreground dark:text-muted-foreground-dark">
        For IU Bloomington students and their families. Not an official IU service.
      </Text>
      {mode === "signup" && (
        <>
          <Field label="Your name" value={name} onChange={setName} />
          <Field label="Email" value={email} onChange={setEmail} />
          <View className="mb-3 flex-row gap-2" accessibilityRole="radiogroup">
            {(["student", "parent"] as const).map((r) => (
              <Pressable
                key={r}
                accessibilityRole="radio"
                accessibilityState={{ checked: role === r }}
                onPress={() => setRole(r)}
                className={`min-h-11 flex-1 items-center justify-center rounded-full border px-4 ${role === r ? "border-primary" : "border-border dark:border-border-dark"}`}
              >
                <Text className="text-foreground dark:text-foreground-dark">{r === "student" ? "I'm a student" : "I'm a parent or guardian"}</Text>
              </Pressable>
            ))}
          </View>
          <Button primary label="Create my account" onPress={() => signUp(email, role, name).then((e) => setNote(e ?? sent), offline)} />
        </>
      )}
      {mode === "signin" && (
        <>
          <Field label="Email" value={email} onChange={setEmail} />
          <Button label="Send me a sign-in link" onPress={() => requestLink(email).then((e) => setNote(e ?? sent), offline)} />
        </>
      )}
      {mode !== "demo" && (
        <>
          <Field label="Sign-in link" value={link} onChange={setLink} />
          <Button primary label="Sign in" onPress={() => signInWithLink(link).then(onSession, (e: Error) => setNote(e.message))} />
        </>
      )}
      {mode === "demo" &&
        DEMO.map((account) => (
          <Pressable
            key={account.id}
            accessibilityRole="button"
            onPress={() => login(account.id).then(onSession, offline)}
            className="mb-3 min-h-11 flex-row items-center rounded-xl border border-border bg-card p-4 dark:border-border-dark dark:bg-card-dark"
          >
            <UserRound size={20} color={primary} />
            <View className="ml-3">
              <Text className="font-semibold text-foreground dark:text-foreground-dark">{account.name}</Text>
              <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{account.note} (test account)</Text>
            </View>
          </Pressable>
        ))}
      {note && <Text className="mb-3 text-sm text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
      <View className="mt-2 flex-row flex-wrap gap-4">
        {mode !== "signin" && <Text onPress={() => setMode("signin")} className="text-sm underline text-foreground dark:text-foreground-dark">I have an account</Text>}
        {mode !== "signup" && <Text onPress={() => setMode("signup")} className="text-sm underline text-foreground dark:text-foreground-dark">New here? Sign up</Text>}
        {mode !== "demo" && <Text onPress={() => setMode("demo")} className="text-sm underline text-foreground dark:text-foreground-dark">Demo accounts</Text>}
      </View>
    </SafeAreaView>
  );
}
