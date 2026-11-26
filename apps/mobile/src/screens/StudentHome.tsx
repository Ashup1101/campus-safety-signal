import * as Location from "expo-location";
import * as Notifications from "expo-notifications";
import { House, LogOut, MapPin, PauseCircle, Settings as SettingsIcon, Shield } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Text, View, useColorScheme } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { ActivityMap } from "../components/ActivityMap";
import { AlertBanner, CheckInControls, ThreadCard } from "../components/AlertCard";
import { CheckingInBadge } from "../components/CheckingInBadge";
import { AreaCheck } from "../components/AreaCheck";
import { CommunityNotes } from "../components/CommunityNotes";
import { Survey } from "../components/Survey";
import { Inbox, type MailboxMessage } from "../components/Inbox";
import { Scoreboard } from "../components/Scoreboard";
import { api, useSocket, type Session } from "../client";
import { homeArea, reassurance, signingKey } from "../home";
import { AreYouOk } from "../components/AreYouOk";
import { ConsentSheet } from "../components/ConsentSheet";
import { consentsApi, type ConsentKind, type ConsentState } from "../consents";
import { answerBand } from "../signing";
import { notifyAreYouOk, onAreYouOkAnswer, registerAreYouOk } from "../notifications";
import { HOME, HOME_RADIUS_M, distance, highSegmentHere, type LatLon } from "../geo";
import {
  activeWindows,
  hasTonight,
  levelFor,
  reachedHomeOnEventNight,
  tonightMethod,
  threadsOf,
  tonightOf,
  toneOf,
  type Alert,
  type Area,
  type CheckIn,
  type Clock,
  type IncidentPoints,
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
      className={`min-h-11 justify-center rounded-full px-4 ${active ? "bg-card dark:bg-card-dark" : ""}`}
    >
      <Text className="text-xs text-foreground dark:text-foreground-dark">{label}</Text>
    </Pressable>
  );
}

export function StudentHome({
  session,
  onLeave,
  onSettings,
}: {
  session: Session;
  onLeave: () => void;
  onSettings: () => void;
}) {
  const dark = useColorScheme() === "dark";
  const token = session.token;
  const [viewers, setViewers] = useState<string[]>([]);
  const [okRequest, setOkRequest] = useState<{ request_id: string; from: string } | null>(null);
  // Consents (Sprint 11): asked the first time each feature is used; location waits for a yes.
  const [consent, setConsent] = useState<Partial<Record<ConsentKind, ConsentState>>>({});
  const [asking, setAsking] = useState<{ kind: ConsentKind; then?: () => void } | null>(null);
  useEffect(() => {
    consentsApi.list(token).then((found) => {
      const states = Object.fromEntries(found.map((c) => [c.kind, c.state]));
      setConsent(states);
      if (states.location_precise === "not_asked") setAsking({ kind: "location_precise" });
    }, () => {});
  }, [token]);
  const choose = async (granted: boolean) => {
    const current = asking;
    setAsking(null);
    if (!current) return;
    await consentsApi.choose(token, current.kind, granted).catch(() => null);
    setConsent((c) => ({ ...c, [current.kind]: granted ? "granted" : "declined" }));
    if (granted) current.then?.();
  };
  const locationOk = consent.location_precise === "granted";
  const [sharing, setSharing] = useState<Sharing>("off");
  const [untilHome, setUntilHome] = useState(false);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [checkIns, setCheckIns] = useState<CheckIn[]>([]);
  const [banner, setBanner] = useState<Alert | null>(null);
  const [clock, setClock] = useState<Clock | null>(null);
  const [segments, setSegments] = useState<Segments | null>(null);
  const [points, setPoints] = useState<IncidentPoints | null>(null);
  const [mail, setMail] = useState<MailboxMessage[]>([]);
  const [chosen, setChosen] = useState<TimeWindow | null>(null);
  const [notesVersion, setNotesVersion] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<SegmentFeature | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const here = useRef<LatLon | null>(null);

  // "Minutes ago" figures refresh every 30 s.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
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
    api<MailboxMessage[]>("/api/mailbox", token).then(
      (found) => live && setMail(found),
      () => {},
    );
    api<IncidentPoints>("/api/incidents?days=90", token).then(
      (found) => live && setPoints(found),
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
        setCheckIns(message.check_ins ?? []);
        setClock(message.clock);
        if (message.signing) signingKey.set(message.signing);
        else signingKey.get().then((key) => key || reply({ type: "key_request" }));
        break;
      case "signing":
        signingKey.set({ key_id: message.key_id, secret: message.secret });
        break;
      case "consent_needed":
        setAsking({ kind: message.kind as ConsentKind });
        break;
      case "band_request":
        answerBand(message.request_id).then(reply);
        break;
      case "ok_request": {
        const request = { request_id: message.request_id, from: message.from };
        reassurance.get().then((settings) => {
          if (!settings.areYouOk) {
            reply({ type: "ok_answer", request_id: request.request_id, answer: "off" });
            return;
          }
          setOkRequest(request);
          notifyAreYouOk(request.from, request.request_id);
        });
        break;
      }
      case "check_in": {
        const latest = message.check_in;
        setCheckIns((list) => [...list.filter((c) => c.thread_id !== latest.thread_id), latest]);
        break;
      }
      case "check_in_cleared":
        setCheckIns((list) => list.filter((c) => c.thread_id !== message.thread_id));
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
      case "notes_changed":
        setNotesVersion((v) => ({ ...v, [message.thread_id]: (v[message.thread_id] ?? 0) + 1 }));
        break;
    }
  });

  // Notification buttons answer "Are you OK?" without opening the app.
  useEffect(() => {
    registerAreYouOk();
    return onAreYouOkAnswer((requestId, answer) => {
      send({ type: "ok_answer", request_id: requestId, answer });
      setOkRequest((current) => (current?.request_id === requestId ? null : current));
    });
  }, [send]);

  const changeSharing = useCallback(
    (state: Sharing, home = false) => {
      setSharing(state);
      setUntilHome(state === "on" && home);
      send({ type: "sharing", state });
    },
    [send],
  );

  const share = (home: boolean) => {
    const start = () => changeSharing("on", home);
    if (consent.sharing === "granted") start();
    else setAsking({ kind: "sharing", then: start });
  };

  // The location loop reads the newest state through a ref, so it never restarts.
  // Home area and the student's "Arrived home" switch, read from this phone's secure store.
  const mine = useRef<{ home: Area | null; arrivedHome: boolean; sent: boolean }>({
    home: null,
    arrivedHome: false,
    sent: false,
  });
  useEffect(() => {
    Promise.all([homeArea.get(), reassurance.get()]).then(([home, settings]) => {
      mine.current = { ...mine.current, home, arrivedHome: settings.arrivedHome };
    });
  }, []);

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
      if (!locationOk) return; // no location at all before the student says yes
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted || stopped) return;
      subscription = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, distanceInterval: 5 },
        ({ coords }) => {
          const point = { lat: coords.latitude, lon: coords.longitude };
          here.current = point;
          const now = latest.current;
          const own = mine.current;
          if (
            now.sharing === "on" &&
            own.arrivedHome &&
            !own.sent &&
            reachedHomeOnEventNight(point, own.home, now.clock?.windows ?? [])
          ) {
            own.sent = true; // the server also sends it once per night
            send({ type: "arrived_home" });
            changeSharing("off"); // tells the server too, even if it already counted this arrival
            setNote("You're home. Sharing ended and your family was told you arrived.");
          } else if (now.sharing === "on" && now.untilHome && distance(point, HOME) <= HOME_RADIUS_M) {
            changeSharing("off");
            setNote("You're home. Sharing turned off.");
          } else if (now.sharing === "on" && now.viewers.length > 0) {
            send({ type: "location", ...point });
          }
          const windows = activeWindows(now.clock?.windows ?? [], now.segments);
          const hit = highSegmentHere(point, now.segments?.features ?? [], windows);
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
  }, [changeSharing, send, locationOk]);

  const withTonight = hasTonight(segments);
  const picked = chosen === "tonight" && !withTonight ? null : chosen;
  const window: TimeWindow =
    picked ?? (clock?.windows.includes("event_night") ? "event_night" : (clock?.windows[0] ?? "late_night"));
  const windowLabel = window === "tonight" ? "Tonight" : window === "late_night" ? "Late nights" : "Event nights";
  const threads = threadsOf(alerts, now);
  const tonight = tonightOf(segments, window, threads, now);
  const primary = dark ? "#e8667a" : "#9b1c31";
  const muted = dark ? "#c9bba9" : "#5c4f4a";

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
        <Pressable onPress={onSettings} accessibilityRole="button" accessibilityLabel="Settings" hitSlop={8} className="min-h-11 min-w-11 items-center justify-center">
          <SettingsIcon size={18} color={muted} />
        </Pressable>
        <Pressable onPress={onLeave} accessibilityRole="button" accessibilityLabel="Sign out" hitSlop={8} className="min-h-11 min-w-11 items-center justify-center">
          <LogOut size={18} color={muted} />
        </Pressable>
      </View>
      {banner && <AlertBanner alert={banner} dark={dark} onClose={() => setBanner(null)} />}
      <ScrollView contentContainerClassName="px-4 pb-10">
        <CheckingInBadge viewers={viewers} dark={dark} onPause={() => changeSharing("paused")} />
        <Survey token={token} />
        {asking && <ConsentSheet kind={asking.kind} onChoose={choose} />}
        {okRequest && (
          <AreYouOk
            from={okRequest.from}
            onAnswer={(answer) => {
              send({ type: "ok_answer", request_id: okRequest.request_id, answer });
              setOkRequest(null);
            }}
          />
        )}
        <Scoreboard tonight={tonight} windowLabel={windowLabel} dark={dark} />
        <View className="mt-3 h-80 overflow-hidden rounded-xl">
          <ActivityMap segments={segments} window={window} dark={dark} onSelect={setSelected} points={points} />
        </View>
        <View className="mt-2 flex-row self-start rounded-full bg-muted p-1 dark:bg-muted-dark">
          <Chip label="Late nights" active={window === "late_night"} onPress={() => setChosen("late_night")} />
          <Chip label="Event nights" active={window === "event_night"} onPress={() => setChosen("event_night")} />
          {withTonight && <Chip label="Tonight" active={window === "tonight"} onPress={() => setChosen("tonight")} />}
        </View>
        {window === "tonight" && (
          <Text className="mt-2 text-xs text-muted-foreground dark:text-muted-foreground-dark">
            Expected from city calls for service (calls are not crimes). Made by: {tonightMethod(segments)}.
          </Text>
        )}
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
        <AreaCheck token={session.token} window={window} />
        <Inbox messages={mail} muted={muted} />
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
                <Pressable onPress={() => share(false)} className="min-h-11 flex-row items-center rounded-full bg-primary px-4 dark:bg-primary-dark">
                  <MapPin size={14} color={dark ? "#1c1416" : "#f5efe3"} />
                  <Text className="ml-1.5 text-sm font-medium text-primary-foreground dark:text-primary-foreground-dark">Share</Text>
                </Pressable>
                <Pressable onPress={() => share(true)} className="min-h-11 flex-row items-center rounded-full border border-border px-4 dark:border-border-dark">
                  <House size={14} color={primary} />
                  <Text className="ml-1.5 text-sm text-foreground dark:text-foreground-dark">Share until I&apos;m home</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Pressable onPress={() => changeSharing("paused")} className="min-h-11 flex-row items-center rounded-full border border-border px-4 dark:border-border-dark">
                  <PauseCircle size={14} color={primary} />
                  <Text className="ml-1.5 text-sm text-foreground dark:text-foreground-dark">Pause</Text>
                </Pressable>
                <Pressable onPress={() => changeSharing("off")} className="min-h-11 justify-center rounded-full px-4">
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
          threads.map((thread) => (
            <ThreadCard key={thread.id} thread={thread} dark={dark} features={segments?.features}>
              {thread.live && (
                <CheckInControls
                  current={checkIns.find((c) => c.thread_id === thread.id) ?? null}
                  dark={dark}
                  onSend={(state, place) => send({ type: "check_in", thread_id: thread.id, state, place })}
                />
              )}
              <CommunityNotes
                token={token}
                threadId={thread.id}
                version={(notesVersion[thread.id] ?? 0) + (notesVersion["*"] ?? 0)}
                muted={dark ? "#c9bba9" : "#5c4f4a"}
                student={{ live: thread.live, closed: thread.closed }}
              />
            </ThreadCard>
          ))
        )}
        <Text className="mt-6 text-center text-xs text-muted-foreground dark:text-muted-foreground-dark">
          Not an official IU service. Built from public data.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}
