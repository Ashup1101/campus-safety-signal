import { ArrowLeft } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, apiSend, type Session } from "../client";
import { Ask, Resources } from "../components/AskAndResources";
import { ZonesEditor } from "../components/ZonesEditor";
import tokens from "../shared/tokens.json";

interface Invite {
  id: number;
  from: string;
  student_email: string;
  status: "pending" | "accepted" | "declined";
  relationship: string;
}
interface Link {
  id: string;
  name: string;
}
const RELATIONSHIPS = [
  { value: "mother", label: "Mother" },
  { value: "father", label: "Father" },
  { value: "guardian", label: "Guardian" },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View className="mt-4 rounded-xl bg-card p-4 dark:bg-card-dark">
      <Text className="mb-2 font-semibold text-foreground dark:text-foreground-dark">{title}</Text>
      {children}
    </View>
  );
}

function Choice({ label, onPress, selected }: { label: string; onPress: () => void; selected?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      onPress={onPress}
      className={`min-h-11 flex-1 items-center justify-center rounded-full border px-4 ${selected ? "border-primary" : "border-border dark:border-border-dark"}`}
    >
      <Text className="text-foreground dark:text-foreground-dark">{label}</Text>
    </Pressable>
  );
}

// Settings for the signed-in person: linking (parents invite, students decide), and more below.
export function Settings({ session, onBack }: { session: Session; onBack: () => void }) {
  const dark = useColorScheme() === "dark";
  const muted = dark ? "#c9bba9" : "#5c4f4a";
  const token = session.token;
  const parent = session.account.role === "parent";
  const [links, setLinks] = useState<Link[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [email, setEmail] = useState("");
  const [relationship, setRelationship] = useState("mother");
  const [own, setOwn] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api<Link[]>("/api/links", token).then(setLinks, () => {});
    api<Invite[]>("/api/invites", token).then(setInvites, () => {});
  }, [token]);
  useEffect(refresh, [refresh]);

  const invite = async () => {
    const chosen = relationship === "own" ? own : relationship;
    const response = await apiSend("/api/invites", token, "POST", { student_email: email, relationship: chosen });
    setNote(
      response.ok
        ? "Invite sent. Your student decides whether to accept."
        : response.status === 409
          ? "An invite to this student is already waiting."
          : "Check the email, and use mother, father, guardian or a few plain words.",
    );
    refresh();
  };
  const answer = async (id: number, choice: "accept" | "decline") => {
    await apiSend(`/api/invites/${id}/${choice}`, token, "POST");
    refresh();
  };
  const unlink = async (id: string) => {
    await apiSend(`/api/links/${id}`, token, "DELETE");
    refresh();
  };

  return (
    <SafeAreaView className="flex-1 bg-background dark:bg-background-dark" edges={["top"]}>
      <View className="flex-row items-center px-2 py-2">
        <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack} className="min-h-11 min-w-11 items-center justify-center">
          <ArrowLeft size={20} color={muted} />
        </Pressable>
        <Text className="text-lg font-semibold text-foreground dark:text-foreground-dark">Settings</Text>
      </View>
      <ScrollView contentContainerClassName="px-4 pb-10">
        {parent ? (
          <Section title="Link with your student">
            <TextInput
              accessibilityLabel="Your student's email"
              placeholder="Your student's email"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              className="mb-3 rounded-xl border border-border px-4 py-3 text-foreground dark:border-border-dark dark:text-foreground-dark"
            />
            <Text className="mb-2 text-sm text-muted-foreground dark:text-muted-foreground-dark">I am their</Text>
            <View className="mb-2 flex-row gap-2">
              {RELATIONSHIPS.map((r) => (
                <Choice key={r.value} label={r.label} selected={relationship === r.value} onPress={() => setRelationship(r.value)} />
              ))}
            </View>
            <Choice label="In my own words" selected={relationship === "own"} onPress={() => setRelationship("own")} />
            {relationship === "own" && (
              <TextInput
                accessibilityLabel="Relationship in your own words"
                placeholder="e.g. Aunt Maria"
                value={own}
                onChangeText={setOwn}
                className="mt-2 rounded-xl border border-border px-4 py-3 text-foreground dark:border-border-dark dark:text-foreground-dark"
              />
            )}
            <Text className="mt-2 text-xs text-muted-foreground dark:text-muted-foreground-dark">
              Your student sees this name whenever you look at their location.
            </Text>
            <View className="mt-3">
              <Choice label="Send invite" onPress={invite} />
            </View>
            {invites.map((i) => (
              <Text key={i.id} className="mt-2 text-sm text-muted-foreground dark:text-muted-foreground-dark">
                {i.student_email}: {i.status}
              </Text>
            ))}
          </Section>
        ) : (
          invites
            .filter((i) => i.status === "pending")
            .map((i) => (
              <Section key={i.id} title={`${i.from} wants to link with you`}>
                <Text className="mb-3 text-sm text-foreground dark:text-foreground-dark">
                  You will see them as "{i.relationship}". They can see your location only when you choose to share,
                  and only while their screen is open. You can unlink anytime.
                </Text>
                <View className="flex-row gap-2">
                  <Choice label="Accept" onPress={() => answer(i.id, "accept")} />
                  <Choice label="Decline" onPress={() => answer(i.id, "decline")} />
                </View>
              </Section>
            ))
        )}
        <Section title={parent ? "Linked students" : "Linked family"}>
          {links.length === 0 ? (
            <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">Nobody linked.</Text>
          ) : (
            links.map((l) => (
              <View key={l.id} className="mt-1 flex-row items-center justify-between">
                <Text className="text-foreground dark:text-foreground-dark">{l.name}</Text>
                <Pressable accessibilityRole="button" onPress={() => unlink(l.id)} className="min-h-11 justify-center px-2">
                  <Text className="underline text-foreground dark:text-foreground-dark">Unlink</Text>
                </Pressable>
              </View>
            ))
          )}
        </Section>
        <Section title="Ask about past incidents">
          <Ask token={token} />
        </Section>
        <Section title="Resources">
          <Resources />
        </Section>
        <Section title="Watch zones">
          <ZonesEditor token={token} zoneColor={tokens.zone[dark ? "dark" : "light"]} />
        </Section>
        {note && <Text className="mt-3 text-sm text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}
