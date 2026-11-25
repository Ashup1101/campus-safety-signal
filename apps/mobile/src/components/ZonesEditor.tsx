import { useCallback, useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import MapView, { Circle } from "react-native-maps";
import { api, apiSend } from "../client";

interface Zone {
  id: number;
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
}
const REGION = { latitude: 39.1672, longitude: -86.524, latitudeDelta: 0.03, longitudeDelta: 0.03 };
const RADII = [200, 400, 800, 1500];

// Watch zones: where alerts and digests matter to this person. Up to 5, own zones only.
export function ZonesEditor({ token, zoneColor }: { token: string; zoneColor: string }) {
  const [zones, setZones] = useState<Zone[]>([]);
  const [center, setCenter] = useState<{ lat: number; lon: number } | null>(null);
  const [radius, setRadius] = useState(400);
  const [name, setName] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api<Zone[]>("/api/zones", token).then(setZones, () => {});
  }, [token]);
  useEffect(refresh, [refresh]);

  const save = async () => {
    if (!center || !name.trim()) {
      setNote("Tap the map to pick the middle, then give the zone a name.");
      return;
    }
    const response = await apiSend("/api/zones", token, "POST", { name, lat: center.lat, lon: center.lon, radius_m: radius });
    setNote(response.ok ? "Zone saved." : response.status === 409 ? "Up to 5 watch zones." : "Pick a place around Bloomington.");
    if (response.ok) {
      setCenter(null);
      setName("");
    }
    refresh();
  };
  const rename = async (zone: Zone, newName: string) => {
    if (!newName.trim() || newName === zone.name) return;
    await apiSend(`/api/zones/${zone.id}`, token, "PUT", { ...zone, name: newName });
    refresh();
  };
  const remove = async (zone: Zone) => {
    await apiSend(`/api/zones/${zone.id}`, token, "DELETE");
    refresh();
  };

  return (
    <View>
      {zones.map((zone) => (
        <View key={zone.id} className="mb-2 flex-row items-center gap-2">
          <TextInput
            accessibilityLabel={`Rename ${zone.name}`}
            defaultValue={zone.name}
            onEndEditing={(e) => rename(zone, e.nativeEvent.text)}
            className="flex-1 rounded-xl border border-border px-3 py-2 text-foreground dark:border-border-dark dark:text-foreground-dark"
          />
          <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">{zone.radius_m} m</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={`Delete ${zone.name}`} onPress={() => remove(zone)} className="min-h-11 justify-center px-2">
            <Text className="underline text-foreground dark:text-foreground-dark">Delete</Text>
          </Pressable>
        </View>
      ))}
      <View className="mt-2 h-56 overflow-hidden rounded-xl">
        <MapView
          style={{ flex: 1 }}
          initialRegion={REGION}
          onPress={(e) => setCenter({ lat: e.nativeEvent.coordinate.latitude, lon: e.nativeEvent.coordinate.longitude })}
        >
          {zones.map((zone) => (
            <Circle key={zone.id} center={{ latitude: zone.lat, longitude: zone.lon }} radius={zone.radius_m} strokeColor={zoneColor} />
          ))}
          {center && (
            <Circle center={{ latitude: center.lat, longitude: center.lon }} radius={radius} strokeColor={zoneColor} strokeWidth={2} />
          )}
        </MapView>
      </View>
      <Text className="mt-2 text-xs text-muted-foreground dark:text-muted-foreground-dark">
        {center ? "Middle picked. Choose a size and a name." : "Tap the map to pick the middle of a new zone."}
      </Text>
      <View className="mt-2 flex-row gap-2">
        {RADII.map((r) => (
          <Pressable
            key={r}
            accessibilityRole="button"
            accessibilityState={{ selected: r === radius }}
            onPress={() => setRadius(r)}
            className={`min-h-11 flex-1 items-center justify-center rounded-full border ${r === radius ? "border-primary" : "border-border dark:border-border-dark"}`}
          >
            <Text className="text-xs text-foreground dark:text-foreground-dark">{r < 1000 ? `${r} m` : `${r / 1000} km`}</Text>
          </Pressable>
        ))}
      </View>
      <TextInput
        accessibilityLabel="New zone name"
        placeholder="Name, e.g. Near the dorm"
        value={name}
        onChangeText={setName}
        className="mt-2 rounded-xl border border-border px-4 py-3 text-foreground dark:border-border-dark dark:text-foreground-dark"
      />
      <Pressable accessibilityRole="button" onPress={save} className="mt-2 min-h-11 items-center justify-center rounded-full bg-muted dark:bg-muted-dark">
        <Text className="font-medium text-foreground dark:text-foreground-dark">Save zone</Text>
      </Pressable>
      {note && <Text className="mt-2 text-sm text-muted-foreground dark:text-muted-foreground-dark">{note}</Text>}
    </View>
  );
}
