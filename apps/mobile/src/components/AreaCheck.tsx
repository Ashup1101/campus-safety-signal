import * as Location from "expo-location";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { apiSend } from "../client";
import type { SegmentLevel, TimeWindow } from "../shared/api";
import tokens from "../shared/tokens.json";

interface Nearby {
  id: string;
  name: string;
  meters: number;
  levels: Partial<Record<TimeWindow, SegmentLevel>>;
}

// One location reading, sent once, answered with the streets within 400 m. Nothing is stored.
export function AreaCheck({ token, window }: { token: string; window: TimeWindow }) {
  const [found, setFound] = useState<Nearby[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const check = async () => {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== "granted") {
      setNote("Location is off for this app. Nothing was checked.");
      return;
    }
    const here = await Location.getCurrentPositionAsync({});
    const response = await apiSend("/api/area-check", token, "POST", {
      lat: here.coords.latitude,
      lon: here.coords.longitude,
    });
    if (!response.ok) {
      setNote(response.status === 422 ? "This works around Bloomington only." : "Could not check right now.");
      return;
    }
    setNote(null);
    setFound(((await response.json()) as { segments: Nearby[] }).segments.slice(0, 5));
  };
  return (
    <View className="mt-3 rounded-xl bg-card p-4 dark:bg-card-dark">
      <Pressable accessibilityRole="button" onPress={check} className="min-h-11 items-center justify-center rounded-full bg-muted dark:bg-muted-dark">
        <Text className="font-medium text-foreground dark:text-foreground-dark">Check my area</Text>
      </Pressable>
      <Text className="mt-2 text-xs text-muted-foreground dark:text-muted-foreground-dark">
        Uses your location once for this answer. It is never saved.
      </Text>
      {note && <Text className="mt-2 text-sm text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
      {found?.length === 0 && (
        <Text className="mt-2 text-sm text-foreground dark:text-foreground-dark">No mapped street within 400 m.</Text>
      )}
      {found?.map((s) => {
        const level = s.levels[window];
        return (
          <Text key={s.id} className="mt-2 text-sm text-foreground dark:text-foreground-dark">
            {s.name} ({s.meters} m): {level ? `${tokens.activity[level.level].label}. ${level.reason}` : "no data for this window"}
          </Text>
        );
      })}
    </View>
  );
}
