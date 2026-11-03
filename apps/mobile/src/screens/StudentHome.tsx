import * as Location from "expo-location";
import * as Notifications from "expo-notifications";
import { House, LogOut, MapPin, PauseCircle, Shield } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Text, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { ActivityMap } from "../components/ActivityMap";
import { AlertBanner, AlertCard } from "../components/AlertCard";
import { CheckingInBadge } from "../components/CheckingInBadge";
import { api, useSocket, type Session } from "../client";
import { HOME, HOME_RADIUS_M, distance, highSegmentHere, type LatLon } from "../geo";
import {
  levelFor,
  toneOf,
  type Alert,
  type Clock,
  type SegmentFeature,
  type Segments,
  type Sharing,
  type TimeWindow,
} from "../shared/api";
import tokens from "../shared/tokens.json";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

function notify(title: string, body: string) {
  Notifications.scheduleNotificationAsync({ content: { title, body }, trigger: null }).catch(() => {});
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      className={`rounded-full px-3 py-1.5 ${active ? "bg-card dark:bg-card-dark" : ""}`}
    >
      <Text className="text-xs text-foreground dark:text-foreground-dark">{label}</Text>
    </Pressable>
  );
}

export function StudentHome({ session, onLeave }: { session: Session; onLeave: () => void }) {
  const dark = useColorScheme() === "dark";
  const token = session.token;
  const [viewers, setViewers] = useState<string[]>([]);
  const [sharing, setSharing] = useState<Sharing>("off");
  const [untilHome, setUntilHome] = useState(false);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [banner, setBanner] = useState<Alert | null>(null);
  const [clock, setClock] = useState<Clock | null>(null);
  const [segments, setSegments] = useState<Segments | null>(null);
  const [chosen, setChosen] = useState<TimeWindow | null>(null);
  const [selected, setSelected] = useState<SegmentFeature | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const here = useRef<LatLon | null>(null);
  const lastHeadsUp = useRef<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([api<Segments>("/api/segments", token), api<Alert[]>("/api/alerts", token)]).then(
      ([map, history]) => {
        if (!live) return;
        setSegments(map);
        setClock(map.clock);
        setAlerts(history);
      },
      () => {},
    );
    Notifications.requestPermissionsAsync().catch(() => {});
    return () => {
      live = false;
    };
  }, [token]);

  const { send, connected } = useSocket(token, (message, reply) => {
    switch (message.type) {
      case "hello":
        setViewers(message.viewers ?? []);
        setSharing(message.sharing ?? "off");
        setClock(message.clock);
        break;
      case "viewers":
        setViewers(message.labels);
        break;
      case "alert":
        setAlerts((list) => [message.alert, ...list]);
        setBanner(message.alert);
        notify(tokens.alert[toneOf(message.alert)].label, message.alert.text);
        requestAnimationFrame(() => reply({ type: "ack", alert_id: message.alert.id, client: "ios" }));
        break;
      case "clock":
        setClock(message.clock);
        break;
    }
  });

  const changeSharing = useCallback(
    (state: Sharing, home = false) => {
      setSharing(state);
      setUntilHome(state === "on" && home);
      send({ type: "sharing", state });
    },
    [send],
  );

  // The location loop reads the newest state through a ref, so it never restarts.
  const latest = useRef({ sharing, untilHome, viewers, segments, clock });
  useEffect(() => {
    latest.current = { sharing, untilHome, viewers, segments, clock };
  });

  // A parent just opened their screen while sharing is on: send where we are once.
  useEffect(() => {
    if (sharing === "on" && viewers.length > 0 && here.current) {
      send({ type: "location", ...here.current });
    }
  }, [sharing, viewers, send]);

  useEffect(() => {
    let subscription: Location.LocationSubscription | null = null;
    let stopped = false;
    (async () => {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted || stopped) return;
      subscription = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, distanceInterval: 5 },
        ({ coords }) => {
          const point = { lat: coords.latitude, lon: coords.longitude };
          here.current = point;
          const now = latest.current;
          if (now.sharing === "on" && now.untilHome && distance(point, HOME) <= HOME_RADIUS_M) {
            changeSharing("off");
            setNote("You're home. Sharing turned off.");
          } else if (now.sharing === "on" && now.viewers.length > 0) {
            send({ type: "location", ...point });
          }
          const hit = highSegmentHere(point, now.segments?.features ?? [], now.clock?.windows ?? []);
          if (hit && lastHeadsUp.current !== hit.feature.id) {
            lastHeadsUp.current = hit.feature.id;
            const { reason } = levelFor(hit.feature, hit.window);
            const text = `${hit.feature.properties.name} is busier at this hour. ${reason}.`;
            setNote(`Heads-up: ${text}`);
            notify("Heads-up", text);
            send({ type: "heads_up", segment_id: hit.feature.id });
          } else if (!hit) {
            lastHeadsUp.current = null;
          }
        },
      );
      if (stopped) subscription.remove();
    })();
    return () => {
      stopped = true;
      subscription?.remove();
    };
  }, [changeSharing, send]);

  const window: TimeWindow =
    chosen ?? (clock?.windows.includes("event_night") ? "event_night" : (clock?.windows[0] ?? "late_night"));
  const primary = dark ? "#6cc6b8" : "#3f9a8e";
  const muted = dark ? "#a9b4c2" : "#66717f";

  return (
    <SafeAreaView className="flex-1 bg-background dark:bg-background-dark" edges={["top"]}>
      <View className="flex-row items-center px-4 pb-2 pt-1">
        <Shield size={22} color={primary} />
        <View className="ml-2 flex-1">
          <Text className="text-lg font-semibold text-foreground dark:text-foreground-dark">
            Hi {session.account.name}
          </Text>
          <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
            {connected ? "Connected · demo" : "Connecting…"}
          </Text>
        </View>
        <Pressable onPress={onLeave} accessibilityLabel="Switch student" className="p-2">
          <LogOut size={18} color={muted} />
        </Pressable>
      </View>
      {banner && <AlertBanner alert={banner} dark={dark} onClose={() => setBanner(null)} />}
      <ScrollView contentContainerClassName="px-4 pb-10">
        <CheckingInBadge viewers={viewers} dark={dark} onPause={() => changeSharing("paused")} />
        <View className="mt-3 h-80 overflow-hidden rounded-xl">
          <ActivityMap segments={segments} window={window} dark={dark} onSelect={setSelected} />
        </View>
        <View className="mt-2 flex-row self-start rounded-full bg-muted p-1 dark:bg-muted-dark">
          <Chip label="Late nights" active={window === "late_night"} onPress={() => setChosen("late_night")} />
          <Chip label="Event nights" active={window === "event_night"} onPress={() => setChosen("event_night")} />
        </View>
        {selected && (
          <Pressable onPress={() => setSelected(null)} className="mt-3 rounded-xl bg-card p-4 dark:bg-card-dark">
            <Text className="font-semibold text-foreground dark:text-foreground-dark">
              {selected.properties.name}
            </Text>
            <Text className="mt-1 text-sm text-muted-foreground dark:text-muted-foreground-dark">
              {tokens.activity[levelFor(selected, window).level].label}: {levelFor(selected, window).reason}
            </Text>
          </Pressable>
        )}
        {note && (
          <Pressable
            onPress={() => setNote(null)}
            className="mt-3 rounded-xl p-4"
            style={{ backgroundColor: dark ? tokens.warm.softDark : tokens.warm.softLight }}
          >
            <Text style={{ color: dark ? tokens.warm.dark : tokens.warm.light }}>{note}</Text>
          </Pressable>
        )}
        <View className="mt-3 rounded-xl bg-card p-4 dark:bg-card-dark">
          <Text className="font-semibold text-foreground dark:text-foreground-dark">Location sharing</Text>
          <Text className="mb-3 mt-1 text-sm text-muted-foreground dark:text-muted-foreground-dark">
            {sharing === "on"
              ? untilHome
                ? "On until you get home. Your parent sees it only while their screen is open."
                : "On. Your parent sees it only while their screen is open. Never saved."
              : sharing === "paused"
                ? "Paused. Your parent sees “Sharing paused.”"
                : "Off. Your location stays on this phone."}
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {sharing !== "on" ? (
              <>
                <Pressable onPress={() => changeSharing("on")} className="flex-row items-center rounded-full bg-primary px-4 py-2 dark:bg-primary-dark">
                  <MapPin size={14} color="#ffffff" />
                  <Text className="ml-1.5 text-sm font-medium text-white">Share</Text>
                </Pressable>
                <Pressable onPress={() => changeSharing("on", true)} className="flex-row items-center rounded-full border border-border px-4 py-2 dark:border-border-dark">
                  <House size={14} color={primary} />
                  <Text className="ml-1.5 text-sm text-foreground dark:text-foreground-dark">Share until I&apos;m home</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Pressable onPress={() => changeSharing("paused")} className="flex-row items-center rounded-full border border-border px-4 py-2 dark:border-border-dark">
                  <PauseCircle size={14} color={primary} />
                  <Text className="ml-1.5 text-sm text-foreground dark:text-foreground-dark">Pause</Text>
                </Pressable>
                <Pressable onPress={() => changeSharing("off")} className="rounded-full px-4 py-2">
                  <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">Stop sharing</Text>
                </Pressable>
              </>
            )}
          </View>
        </View>
        <Text className="mb-2 mt-5 font-semibold text-foreground dark:text-foreground-dark">Alerts</Text>
        {alerts.length === 0 ? (
          <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">
            No alerts. Official IU alerts appear here the moment they are sent.
          </Text>
        ) : (
          alerts.map((alert) => <AlertCard key={alert.id} alert={alert} dark={dark} />)
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
