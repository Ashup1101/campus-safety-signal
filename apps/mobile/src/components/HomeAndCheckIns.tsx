import * as Location from "expo-location";
import { useEffect, useState } from "react";
import { Pressable, Switch, Text, View } from "react-native";
import { DEFAULTS, homeArea, reassurance, type Reassurance } from "../home";
import type { Area } from "../shared/api";

const RADII = [150, 300, 600] as const;

const SWITCHES: { key: keyof Reassurance; label: string; help: string }[] = [
  {
    key: "bandAnswers",
    label: "Allow check-ins",
    help: "A linked parent can ask roughly where you are. Your phone answers with one word: in your home area, near home or on campus, or away. Never your location.",
  },
  {
    key: "areYouOk",
    label: "\"Are you OK?\" nudges",
    help: "You are asked first. Your parent hears only if you have not answered in 10 minutes.",
  },
  {
    key: "arrivedHome",
    label: "Tell my parent when I get home on event nights",
    help: "While you share on an event night, reaching your home area ends sharing and sends \"Arrived home\".",
  },
];

/** Home area (kept only on this phone) and the student's reassurance switches. */
export function HomeAndCheckIns() {
  const [home, setHome] = useState<Area | null>(null);
  const [settings, setSettings] = useState<Reassurance>(DEFAULTS);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    homeArea.get().then(setHome);
    reassurance.get().then(setSettings);
  }, []);

  const useHere = async () => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      setNote("Location permission is off, so the home area cannot be set here.");
      return;
    }
    const here = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    const area = { lat: here.coords.latitude, lon: here.coords.longitude, radius_m: home?.radius_m ?? 300 };
    await homeArea.set(area);
    setHome(area);
    setNote("Home area saved on this phone only.");
  };

  const radius = async (radius_m: number) => {
    if (!home) return;
    const area = { ...home, radius_m };
    await homeArea.set(area);
    setHome(area);
  };

  const toggle = async (key: keyof Reassurance, value: boolean) => {
    const next = { ...settings, [key]: value };
    setSettings(next);
    await reassurance.set(next);
  };

  return (
    <View className="gap-3">
      <Text className="text-sm text-foreground dark:text-foreground-dark">
        {home ? `Home area set (${home.radius_m} m around it). It never leaves this phone.` : "No home area yet."}
      </Text>
      <Pressable
        accessibilityRole="button"
        onPress={useHere}
        className="min-h-11 items-center justify-center rounded-full border border-border px-4 dark:border-border-dark"
      >
        <Text className="text-foreground dark:text-foreground-dark">Use where I am now as home</Text>
      </Pressable>
      {home && (
        <View className="flex-row gap-2" accessibilityLabel="Home area size">
          {RADII.map((r) => (
            <Pressable
              key={r}
              accessibilityRole="button"
              accessibilityState={{ selected: home.radius_m === r }}
              onPress={() => radius(r)}
              className={`min-h-11 flex-1 items-center justify-center rounded-full border px-2 ${home.radius_m === r ? "border-primary" : "border-border dark:border-border-dark"}`}
            >
              <Text className="text-foreground dark:text-foreground-dark">{r} m</Text>
            </Pressable>
          ))}
        </View>
      )}
      {SWITCHES.map((s) => (
        <View key={s.key} className="flex-row items-start gap-3">
          <View className="flex-1">
            <Text className="text-foreground dark:text-foreground-dark">{s.label}</Text>
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{s.help}</Text>
          </View>
          <Switch
            accessibilityLabel={s.label}
            value={settings[s.key]}
            onValueChange={(value) => toggle(s.key, value)}
          />
        </View>
      ))}
      {note && <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
    </View>
  );
}
