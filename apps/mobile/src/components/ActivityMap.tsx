import { Fragment } from "react";
import { Text, View } from "react-native";
import MapView, { Marker, Polyline } from "react-native-maps";
import {
  levelFor,
  pointText,
  type IncidentPoints,
  type SegmentFeature,
  type Segments,
  type TimeWindow,
} from "../shared/api";
import tokens from "../shared/tokens.json";

const REGION = { latitude: 39.1672, longitude: -86.524, latitudeDelta: 0.016, longitudeDelta: 0.016 };
// Native markers are costly on a phone: the newest dots only (the server sends newest first).
export const MAX_DOTS = 150;
const DOT = { light: "#3a2326", dark: "#f3ede1" };


function path(line: number[][]) {
  return line.map(([longitude, latitude]) => ({ latitude, longitude }));
}

function middle(feature: SegmentFeature) {
  const line = feature.geometry.coordinates[Math.floor(feature.geometry.coordinates.length / 2)];
  const [longitude, latitude] = line[Math.floor(line.length / 2)];
  return { latitude, longitude };
}

// Activity streets: teal / amber / deep orange (no glow, same as the web); Elevated and High get a
// crisp casing (quiet streets skip it: about 1,300 generated streets would double the overlays).
// High is also thicker and labeled. Dots: filled = address, ring = block or street stretch.
export function ActivityMap({
  segments,
  window,
  dark,
  onSelect,
  points = null,
}: {
  segments: Segments | null;
  window: TimeWindow;
  dark: boolean;
  onSelect: (feature: SegmentFeature) => void;
  points?: IncidentPoints | null;
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
            {level !== "quiet" && (
              <Polyline
                coordinates={path(line)}
                strokeColor={dark ? "#160f11" : "#fbf8f1"}
                strokeWidth={tokens.activity[level].width + (level === "high" ? 4 : 3)}
                lineCap="round"
              />
            )}
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
      {(points?.features ?? []).slice(0, MAX_DOTS).map((p, i) => (
        <Marker
          key={`dot-${i}`}
          coordinate={{ latitude: p.geometry.coordinates[1], longitude: p.geometry.coordinates[0] }}
          title={pointText(p.properties)}
          tracksViewChanges={false}
        >
          <View
            className="size-2.5 rounded-full border-[1.5px]"
            style={{
              borderColor: DOT[tone],
              backgroundColor: p.properties.precision === "address" ? DOT[tone] : "transparent",
            }}
          />
        </Marker>
      ))}
    </MapView>
  );
}
