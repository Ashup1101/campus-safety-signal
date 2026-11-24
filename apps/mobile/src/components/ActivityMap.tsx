import { Fragment } from "react";
import { Text, View } from "react-native";
import MapView, { Marker, Polyline } from "react-native-maps";
import { levelFor, type SegmentFeature, type Segments, type TimeWindow } from "../shared/api";
import tokens from "../shared/tokens.json";

const REGION = { latitude: 39.1672, longitude: -86.524, latitudeDelta: 0.016, longitudeDelta: 0.016 };


function path(line: number[][]) {
  return line.map(([longitude, latitude]) => ({ latitude, longitude }));
}

function middle(feature: SegmentFeature) {
  const line = feature.geometry.coordinates[Math.floor(feature.geometry.coordinates.length / 2)];
  const [longitude, latitude] = line[Math.floor(line.length / 2)];
  return { latitude, longitude };
}

// Activity streets: teal / amber / deep orange over a crisp casing (no glow, same as the web);
// High is also thicker and labeled.
export function ActivityMap({
  segments,
  window,
  dark,
  onSelect,
}: {
  segments: Segments | null;
  window: TimeWindow;
  dark: boolean;
  onSelect: (feature: SegmentFeature) => void;
}) {
  const features = segments?.features ?? [];
  const tone = dark ? "dark" : "light";
  return (
    <MapView
      style={{ flex: 1 }}
      initialRegion={REGION}
      showsUserLocation
      showsPointsOfInterests={false}
      userInterfaceStyle={tone}
    >
      {features.map((feature) => {
        const { level } = levelFor(feature, window);
        const color = tokens.activity[level][tone];
        return feature.geometry.coordinates.map((line, i) => (
          <Fragment key={`${feature.id}-${i}`}>
            <Polyline
              coordinates={path(line)}
              strokeColor={dark ? "#160f11" : "#fbf8f1"}
              strokeWidth={tokens.activity[level].width + (level === "high" ? 4 : level === "elevated" ? 3 : 2)}
              lineCap="round"
            />
            <Polyline
              coordinates={path(line)}
              strokeColor={color}
              strokeWidth={tokens.activity[level].width}
              lineCap="round"
              tappable
              onPress={() => onSelect(feature)}
            />
          </Fragment>
        ));
      })}
      {features
        .filter((feature) => levelFor(feature, window).level === "high")
        .map((feature) => (
          <Marker
            key={`${feature.id}-label`}
            coordinate={middle(feature)}
            anchor={{ x: 0.5, y: 1.2 }}
            tracksViewChanges={false}
            onPress={() => onSelect(feature)}
          >
            <View className="rounded-full px-2 py-0.5" style={{ backgroundColor: tokens.activity.high[tone] }}>
              <Text className="text-xs font-semibold text-white">{tokens.activity.high.label}</Text>
            </View>
          </Marker>
        ))}
    </MapView>
  );
}
