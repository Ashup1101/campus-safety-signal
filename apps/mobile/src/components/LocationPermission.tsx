import * as Location from "expo-location";
import { useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import { pressed, ui } from "./ui";

/** Whether iOS lets the app use location while closed, with a way to change it in iOS Settings. */
export function LocationPermission() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  useEffect(() => {
    Location.getBackgroundPermissionsAsync().then((p) => setAllowed(p.granted), () => setAllowed(false));
  }, []);
  return (
    <View className="gap-2">
      <Text className="text-foreground dark:text-foreground-dark">
        Location while the app is closed: {allowed === null ? "checking…" : allowed ? "allowed" : "not allowed"}
      </Text>
      <Text className={ui.note}>Used only during a session you start, never longer than 2 hours, never saved.</Text>
      <Pressable accessibilityRole="button" onPress={() => Linking.openSettings()} style={pressed} className="min-h-11 justify-center self-start">
        <Text className="text-sm underline text-foreground dark:text-foreground-dark">Change in iOS Settings</Text>
      </Pressable>
    </View>
  );
}
