import { HeartHandshake, LogOut, MapPin, Settings as SettingsIcon } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { ActivityMap } from "../components/ActivityMap";
import { AlertBanner, ThreadCard } from "../components/AlertCard";
import { AreaCheck } from "../components/AreaCheck";
import { Inbox, type MailboxMessage } from "../components/Inbox";
import { api, useSocket, type Session } from "../client";
import {
  checkInText,
  clockTime,
  hasTonight,
  threadsOf,
  type Alert,
  type CheckIn,
  type Clock,
  type IncidentPoints,
  type Segments,
  type Student,
  type TimeWindow,
} from "../shared/api";
import tokens from "../shared/tokens.json";

const CHIPS: Record<TimeWindow, string> = { late_night: "Late nights", event_night: "Event nights", tonight: "Tonight" };

function sharingText(s: Student): string {
  if (s.sharing === "on") {
    return s.location ? `Sharing live location · updated ${clockTime(s.location.at)}` : "Sharing on · waiting for a location";
  }
  return s.sharing === "paused" ? "Sharing paused" : "Not sharing right now";
}

// The parent's home: only the students this parent is linked to (the student accepted the link).
// The location shows only while this screen is open and is never stored. No switching between parents.
export function ParentHome({
  session,
  onLeave,
  onSettings,
}: {
  session: Session;
  onLeave: () => void;
  onSettings: () => void;
}) {
  const dark = useColorScheme() === "dark";
  const tone = dark ? "dark" : "light";
  const muted = dark ? "#c9bba9" : "#5c4f4a";
  const token = session.token;
  const [students, setStudents] = useState<Student[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [checkIns, setCheckIns] = useState<CheckIn[]>([]);
  const [banner, setBanner] = useState<Alert | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [segments, setSegments] = useState<Segments | null>(null);
  const [points, setPoints] = useState<IncidentPoints | null>(null);
  const [mail, setMail] = useState<MailboxMessage[]>([]);
  const [clock, setClock] = useState<Clock | null>(null);
  const [chosen, setChosen] = useState<TimeWindow | null>(null);
  const now = Date.now();

  useEffect(() => {
    let live = true;
    const quiet = () => {};
    api<Alert[]>("/api/alerts", token).then((a) => live && setAlerts(a), quiet);
    api<Segments>("/api/segments", token).then((m) => live && (setSegments(m), setClock(m.clock)), quiet);
    api<IncidentPoints>("/api/incidents?days=90", token).then((p) => live && setPoints(p), quiet);
    api<MailboxMessage[]>("/api/mailbox", token).then((m) => live && setMail(m), quiet);
    return () => {
      live = false;
    };
  }, [token]);

  const nameOf = (id: string) => students.find((s) => s.id === id)?.name ?? "Your student";
  const { send, connected } = useSocket(token, (message) => {
    switch (message.type) {
      case "hello":
        setStudents(message.students ?? []);
        setCheckIns(message.check_ins ?? []);
        setClock(message.clock);
        break;
      case "check_in":
        setCheckIns((list) => [
          ...list.filter((c) => !(c.thread_id === message.check_in.thread_id && c.student_id === message.check_in.student_id)),
          message.check_in,
        ]);
        break;
      case "check_in_cleared":
        setCheckIns((list) => list.filter((c) => c.thread_id !== message.thread_id));
        break;
      case "alert":
        setAlerts((list) => [message.alert, ...list]);
        setBanner(message.alert);
        send({ type: "ack", alert_id: message.alert.id, client: "ios" });
        break;
      case "location":
        setStudents((list) =>
          list.map((s) => (s.id === message.student_id ? { ...s, location: { lat: message.lat, lon: message.lon, at: message.at } } : s)),
        );
        break;
      case "sharing":
        setStudents((list) =>
          list.map((s) =>
            s.id === message.student_id ? { ...s, sharing: message.state, location: message.state === "on" ? s.location : null } : s,
          ),
        );
        if (message.state === "paused") setNotice(`${nameOf(message.student_id)}: Sharing paused.`);
        break;
      case "heads_up":
        setNotice(`Heads-up: ${message.student_name} is on ${message.segment_name}, which is busier at this time of night.`);
        break;
      case "clock":
        setClock(message.clock);
        break;
    }
  });

  const withTonight = hasTonight(segments);
  const picked = chosen === "tonight" && !withTonight ? null : chosen;
  const window: TimeWindow =
    picked ?? (clock?.windows.includes("event_night") ? "event_night" : (clock?.windows[0] ?? "late_night"));
  const threads = threadsOf(alerts, now);

  return (
    <SafeAreaView className="flex-1 bg-background dark:bg-background-dark" edges={["top"]}>
      <View className="flex-row items-center justify-between px-4 py-3">
        <View>
          <Text className="text-lg font-semibold text-foreground dark:text-foreground-dark">{session.account.name}</Text>
          <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
            Parent · {connected ? "connected" : "connecting…"} · Not an official IU service
          </Text>
        </View>
        <View className="flex-row">
          <Pressable accessibilityRole="button" accessibilityLabel="Settings" onPress={onSettings} className="min-h-11 min-w-11 items-center justify-center">
            <SettingsIcon size={18} color={muted} />
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Sign out" onPress={onLeave} className="min-h-11 min-w-11 items-center justify-center">
            <LogOut size={18} color={muted} />
          </Pressable>
        </View>
      </View>
      {banner && <AlertBanner alert={banner} dark={dark} onClose={() => setBanner(null)} />}
      <ScrollView contentContainerClassName="px-4 pb-10">
        {notice && (
          <Pressable onPress={() => setNotice(null)} className="mb-3 rounded-xl p-4" style={{ backgroundColor: dark ? tokens.warm.softDark : tokens.warm.softLight }}>
            <Text style={{ color: dark ? tokens.warm.dark : tokens.warm.light }}>{notice}</Text>
          </Pressable>
        )}
        {students.length === 0 ? (
          <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">
            No student linked yet. Invite your student from Settings; they decide whether to accept.
          </Text>
        ) : (
          students.map((s) => (
            <View key={s.id} className="mb-3 rounded-xl bg-card p-4 dark:bg-card-dark">
              <View className="flex-row items-center gap-2">
                <HeartHandshake size={18} color={muted} />
                <Text className="font-semibold text-foreground dark:text-foreground-dark">{s.name}</Text>
              </View>
              <View className="mt-1 flex-row items-center gap-1">
                {s.sharing === "on" && <MapPin size={14} color={tokens.student[tone]} />}
                <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">{sharingText(s)}</Text>
              </View>
              <Text className="mt-2 text-xs text-muted-foreground dark:text-muted-foreground-dark">
                {s.name} chooses when to share and can pause anytime. You see it only while this screen is open; it is never saved.
              </Text>
            </View>
          ))
        )}
        <View className="h-80 overflow-hidden rounded-xl">
          <ActivityMap segments={segments} window={window} dark={dark} onSelect={() => {}} points={points} students={students} />
        </View>
        <View className="mt-2 flex-row self-start rounded-full bg-muted p-1 dark:bg-muted-dark">
          {(["late_night", "event_night", ...(withTonight ? (["tonight"] as const) : [])] as const).map((w) => (
            <Pressable
              key={w}
              accessibilityRole="button"
              accessibilityState={{ selected: w === window }}
              onPress={() => setChosen(w)}
              className={`min-h-11 justify-center rounded-full px-4 ${w === window ? "bg-card dark:bg-card-dark" : ""}`}
            >
              <Text className="text-sm text-foreground dark:text-foreground-dark">{CHIPS[w]}</Text>
            </Pressable>
          ))}
        </View>
        <Text className="mb-1 mt-4 font-semibold text-foreground dark:text-foreground-dark">Alerts</Text>
        {threads.length === 0 ? (
          <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">
            No alerts. Official IU alerts appear here the moment they are sent.
          </Text>
        ) : (
          threads.map((thread) => (
            <ThreadCard key={thread.id} thread={thread} dark={dark} features={segments?.features}>
              {checkIns
                .filter((c) => c.thread_id === thread.id)
                .map((c) => (
                  <Text key={c.student_id} className="mt-2 font-medium text-foreground dark:text-foreground-dark">
                    {c.student_name}: {checkInText(c)}
                  </Text>
                ))}
            </ThreadCard>
          ))
        )}
        <AreaCheck token={token} window={window} />
        <Inbox messages={mail} muted={muted} />
      </ScrollView>
    </SafeAreaView>
  );
}
