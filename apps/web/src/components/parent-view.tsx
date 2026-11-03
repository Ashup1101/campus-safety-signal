"use client";

import { Bell, HeartHandshake, MapPin, PauseCircle, Shield, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { ActivityMap, Legend } from "@/components/activity-map";
import { AlertBanner, AlertCard } from "@/components/alerts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, color, tokens, useDark, useSession, useSocket } from "@/lib/client";
import {
  clockTime,
  toneOf,
  type Alert,
  type Clock,
  type Segments,
  type Student,
  type TimeWindow,
  type Zone,
} from "@/shared/api";

const PARENTS = [
  { id: "parent_mom", label: "Mom" },
  { id: "parent_dad", label: "Dad" },
];

function notifyBrowser(alert: Alert) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  new Notification(tokens.alert[toneOf(alert)].label, { body: alert.text, tag: alert.id });
}

function SharingStatus({ student }: { student: Student }) {
  if (student.sharing === "on" && student.location) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm">
        <MapPin className="size-4 text-primary" /> Sharing live location · updated{" "}
        {clockTime(student.location.at)}
      </span>
    );
  }
  if (student.sharing === "on") {
    return <span className="text-sm text-muted-foreground">Sharing is on. Waiting for the first update…</span>;
  }
  if (student.sharing === "paused") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
        <PauseCircle className="size-4" /> Sharing paused
      </span>
    );
  }
  return <span className="text-sm text-muted-foreground">Not sharing right now</span>;
}

export function ParentView({ accountId, onSwitch }: { accountId: string; onSwitch: (id: string) => void }) {
  const dark = useDark();
  const { session, error } = useSession(accountId);
  const token = session?.token;
  const [students, setStudents] = useState<Student[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [banner, setBanner] = useState<Alert | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [segments, setSegments] = useState<Segments | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [clock, setClock] = useState<Clock | null>(null);
  const [chosen, setChosen] = useState<TimeWindow | null>(null);
  const [permission, setPermission] = useState<string>("default");

  useEffect(() => {
    if (!token) return;
    let live = true;
    Promise.all([
      api<Alert[]>("/api/alerts", token),
      api<Zone[]>("/api/zones", token),
      api<Segments>("/api/segments", token),
    ]).then(([history, mine, map]) => {
      if (!live) return;
      setAlerts(history);
      setZones(mine);
      setSegments(map);
      setClock(map.clock);
    });
    return () => {
      live = false;
    };
  }, [token]);

  const nameOf = (id: string) => students.find((s) => s.id === id)?.name ?? "Your student";

  const { connected } = useSocket(token, (message, send) => {
    switch (message.type) {
      case "hello":
        setStudents(message.students ?? []);
        setClock(message.clock);
        break;
      case "alert":
        setAlerts((list) => [message.alert, ...list]);
        setBanner(message.alert);
        notifyBrowser(message.alert);
        requestAnimationFrame(() => send({ type: "ack", alert_id: message.alert.id, client: "web" }));
        break;
      case "location":
        setStudents((list) =>
          list.map((s) =>
            s.id === message.student_id
              ? { ...s, location: { lat: message.lat, lon: message.lon, at: message.at } }
              : s,
          ),
        );
        break;
      case "sharing":
        setStudents((list) =>
          list.map((s) =>
            s.id === message.student_id
              ? { ...s, sharing: message.state, location: message.state === "on" ? s.location : null }
              : s,
          ),
        );
        if (message.state === "paused") setNotice(`${nameOf(message.student_id)}: Sharing paused.`);
        break;
      case "heads_up":
        setNotice(
          `Heads-up: ${message.student_name} is on ${message.segment_name}, which is busier at this time of night.`,
        );
        break;
      case "clock":
        setClock(message.clock);
        break;
    }
  });

  const window: TimeWindow =
    chosen ?? (clock?.windows.includes("event_night") ? "event_night" : (clock?.windows[0] ?? "late_night"));
  const warm = { color: color(tokens.warm, dark), background: dark ? tokens.warm.softDark : tokens.warm.softLight };

  return (
    <div className="flex min-h-screen flex-col">
      {banner && <AlertBanner alert={banner} dark={dark} onClose={() => setBanner(null)} />}
      <header className="flex flex-wrap items-center gap-3 px-5 py-4">
        <Shield className="size-6 text-primary" />
        <div className="mr-auto">
          <h1 className="text-lg font-semibold">Campus Safety Signal</h1>
          <p className="text-xs text-muted-foreground">Parent view · local demo · test accounts only</p>
        </div>
        <Badge variant={connected ? "default" : "outline"}>{connected ? "Connected" : "Connecting…"}</Badge>
        <div className="flex gap-1 rounded-full bg-muted p-1">
          {PARENTS.map((p) => (
            <Button key={p.id} size="sm" variant={p.id === accountId ? "outline" : "ghost"} onClick={() => onSwitch(p.id)}>
              <UserRound /> {p.label}
            </Button>
          ))}
        </div>
      </header>
      {error && <p className="mx-5 rounded-xl bg-muted p-4 text-sm">{error}</p>}
      <main className="grid flex-1 gap-4 px-5 pb-6 lg:grid-cols-[2fr_1fr]">
        <Card className="flex flex-col">
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>Around campus</CardTitle>
              <CardDescription>
                {clock?.live === false ? `Demo clock: ${new Date(clock.now).toLocaleString()}` : "Live"}
              </CardDescription>
            </div>
            <div className="flex gap-1 rounded-full bg-muted p-1">
              {(["late_night", "event_night"] as const).map((w) => (
                <Button key={w} size="sm" variant={w === window ? "outline" : "ghost"} onClick={() => setChosen(w)}>
                  {w === "late_night" ? "Late nights" : "Event nights"}
                </Button>
              ))}
            </div>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-3">
            <div className="h-[460px] lg:h-full">
              <ActivityMap segments={segments} window={window} students={students} zones={zones} dark={dark} />
            </div>
            <Legend dark={dark} window={window} />
          </CardContent>
        </Card>
        <div className="flex flex-col gap-4">
          {students.map((student) => (
            <Card key={student.id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <HeartHandshake className="size-5 text-primary" /> {student.name}
                </CardTitle>
                <SharingStatus student={student} />
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  {student.name} chooses when to share and can pause anytime. You see the location only while this
                  page is open; it is never saved.
                </p>
              </CardContent>
            </Card>
          ))}
          {notice && (
            <div className="rounded-xl p-4 text-sm" style={warm}>
              {notice}
              <button className="ml-2 underline-offset-2 hover:underline" onClick={() => setNotice(null)}>
                OK
              </button>
            </div>
          )}
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Alerts</CardTitle>
              {permission !== "granted" && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    if (typeof Notification !== "undefined") Notification.requestPermission().then(setPermission);
                  }}
                >
                  <Bell /> Browser notifications
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {alerts.length === 0 ? (
                <p className="text-sm text-muted-foreground">No alerts. Official IU alerts appear here the moment they are sent.</p>
              ) : (
                <ul className="flex max-h-[420px] flex-col gap-3 overflow-y-auto">
                  {alerts.map((alert) => (
                    <AlertCard key={alert.id} alert={alert} dark={dark} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Watch zones</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {zones.map((zone) => (
                <Badge key={zone.name} variant="secondary">
                  {zone.name}
                </Badge>
              ))}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
