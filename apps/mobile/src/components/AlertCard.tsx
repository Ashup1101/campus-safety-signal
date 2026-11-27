import {
  ClipboardCheck,
  ExternalLink,
  HeartHandshake,
  History,
  House,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react-native";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { AccessibilityInfo, Animated, Linking, Pressable, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";
import {
  SHELTER_PLACES,
  areaSketch,
  areaStreets,
  checkInText,
  clockTime,
  toneOf,
  type Alert,
  type AlertThread,
  type CheckIn,
  type CheckInState,
  type SegmentFeature,
  type ShelterPlace,
  type Tone,
} from "../shared/api";
import tokens from "../shared/tokens.json";
import { Stripe } from "./Scoreboard";

const ICONS: Record<Tone, typeof ShieldAlert> = {
  official: ShieldAlert,
  normal: ShieldCheck,
  drill: ClipboardCheck,
  reconstruction: History,
};

function colors(tone: Tone, dark: boolean) {
  const entry = tokens.alert[tone];
  return {
    accent: dark ? entry.dark : entry.light,
    soft: dark ? entry.softDark : entry.softLight,
    label: entry.label,
  };
}

// One card per incident: IU's latest words, its updates beneath, and the all-clear closing it.
// Red only while a live official alert is open; a closed card turns calm.
// A slow pulse (one cycle every 2 s, well under 3 flashes per second); still with Reduce Motion.
function LiveDot({ color }: { color: string }) {
  const opacity = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    let loop: Animated.CompositeAnimation | null = null;
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (reduce || cancelled) return;
      loop = Animated.loop(
        Animated.sequence([
          Animated.timing(opacity, { toValue: 0.35, duration: 1000, useNativeDriver: true }),
          Animated.timing(opacity, { toValue: 1, duration: 1000, useNativeDriver: true }),
        ]),
      );
      loop.start();
    });
    return () => {
      cancelled = true;
      loop?.stop();
    };
  }, [opacity]);
  return <Animated.View style={{ opacity, width: 8, height: 8, borderRadius: 4, backgroundColor: color }} />;
}

// The streets IU's text names, highlighted on a faint sketch of the demo streets, with a caption.
function AreaSketch({ features, area, accent, faint }: { features: SegmentFeature[]; area: string[]; accent: string; faint: string }) {
  const paths = areaSketch(features, area, 240, 120);
  if (paths.length === 0) return null;
  const streets = areaStreets(features, area).join(", ");
  return (
    <View className="mt-3">
      <View className="overflow-hidden rounded-lg bg-background/60 dark:bg-background-dark/60">
        <Svg width="100%" height={96} viewBox="0 0 240 120">
          {paths.map((p) => (
            <Path
              key={p.id}
              d={p.d}
              fill="none"
              stroke={p.inArea ? accent : faint}
              strokeOpacity={p.inArea ? 1 : 0.45}
              strokeWidth={p.inArea ? 5 : 2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
        </Svg>
      </View>
      <Text className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground-dark">
        Area named in the alert: {streets}
      </Text>
    </View>
  );
}

export function ThreadCard({
  thread,
  dark,
  features = [],
  children,
}: {
  thread: AlertThread;
  dark: boolean;
  features?: SegmentFeature[];
  children?: ReactNode;
}) {
  const { latest, closed, live, tone } = thread;
  // Live: the source's own tone (red only for a live official alert). Closed: calm all-clear.
  // Quiet for 6 h without an all-clear: grey, never claiming it is over.
  const look: Tone = closed ? "normal" : live ? tone : "reconstruction";
  const shown = colors(look, dark);
  const name = tokens.alert[tone].label;
  const label = closed
    ? tone === "normal"
      ? name
      : `${name} · All clear`
    : live
      ? name
      : `${name} · No update for 6 h`;
  const Icon = ICONS[closed ? "normal" : tone];
  const earlier = thread.alerts.slice(0, -1).reverse();
  return (
    <View
      accessibilityLabel={`${label}. ${latest.text}`}
      className="mb-3 overflow-hidden rounded-xl border"
      style={{ borderColor: shown.accent, backgroundColor: shown.soft }}
    >
      {live && <Stripe dark={dark} />}
      <View className="p-4">
        <View className="mb-1.5 flex-row items-center">
          <Icon size={16} color={shown.accent} />
          <Text className="ml-1.5 text-xs font-semibold" style={{ color: shown.accent }}>
            {label}
          </Text>
          {live && (
            <View
              className="ml-2 flex-row items-center rounded-full border px-2 py-0.5"
              style={{ borderColor: shown.accent }}
              accessibilityLabel="Live"
            >
              <LiveDot color={shown.accent} />
              <Text className="ml-1 text-xs font-semibold" style={{ color: shown.accent }}>
                Live
              </Text>
            </View>
          )}
          <Text
            className="ml-auto text-xs text-muted-foreground dark:text-muted-foreground-dark"
            style={{ fontVariant: ["tabular-nums"] }}
          >
            {clockTime(latest.received_at)}
          </Text>
        </View>
        <Text className="text-[17px] font-medium leading-6 text-foreground dark:text-foreground-dark">{latest.text}</Text>
        <View className="mt-2 flex-row flex-wrap items-center">
          <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
            Sent {clockTime(latest.official_at)} · received {clockTime(latest.received_at)}
          </Text>
          {latest.link && (
            <Pressable
              onPress={() => Linking.openURL(latest.link ?? "")}
              accessibilityRole="link"
              accessibilityLabel="Open the official source"
              hitSlop={12}
              className="ml-2 flex-row items-center"
              style={({ pressed }) => ({ opacity: pressed ? 0.5 : 1 })}
            >
              <ExternalLink size={12} color={shown.accent} />
              <Text className="ml-1 text-xs" style={{ color: shown.accent }}>
                Source
              </Text>
            </Pressable>
          )}
        </View>
        <AreaSketch features={features} area={thread.area} accent={shown.accent} faint={dark ? "#c9bba9" : "#5c4f4a"} />
        {children}
        {earlier.length > 0 && (
          <View className="mt-3 border-t pt-2" style={{ borderColor: shown.accent + "40" }}>
            <Text className="mb-1 text-xs font-semibold text-muted-foreground dark:text-muted-foreground-dark">
              Earlier updates
            </Text>
            {earlier.map((alert) => (
              <Text
                key={alert.id}
                className="mb-1 text-xs leading-4 text-muted-foreground dark:text-muted-foreground-dark"
                style={{ fontVariant: ["tabular-nums"] }}
              >
                {clockTime(alert.received_at)} · {alert.text}
              </Text>
            ))}
          </View>
        )}
      </View>
    </View>
  );
}

export function AlertBanner({ alert, dark, onClose }: { alert: Alert; dark: boolean; onClose: () => void }) {
  const tone = toneOf(alert);
  const { accent, soft, label } = colors(tone, dark);
  const Icon = ICONS[tone];
  return (
    <View
      accessibilityRole="alert"
      className="mx-4 mb-3 flex-row items-start rounded-xl border p-3"
      style={{ borderColor: accent, backgroundColor: soft }}
    >
      <Icon size={20} color={accent} />
      <View className="ml-2 flex-1">
        <Text className="text-xs font-semibold" style={{ color: accent }}>
          {label}
        </Text>
        <Text className="text-sm text-foreground dark:text-foreground-dark">{alert.text}</Text>
      </View>
      <Pressable onPress={onClose} accessibilityLabel="Dismiss" hitSlop={12} className="p-1">
        <X size={16} color={accent} />
      </Pressable>
    </View>
  );
}

// Private check-in on a live card: one tap tells linked family only; nothing is kept after the
// all-clear. Places come from a fixed list (no typing, so no names or rumors).
export function CheckInControls({
  current,
  dark,
  onSend,
}: {
  current: CheckIn | null;
  dark: boolean;
  onSend: (state: CheckInState, place?: ShelterPlace) => void;
}) {
  const [picking, setPicking] = useState(false);
  const [changing, setChanging] = useState(false);
  const primary = dark ? "#e8667a" : "#9b1c31";
  if (current && !changing) {
    return (
      <View className="mt-3 flex-row items-center rounded-lg bg-background/60 px-3 py-2 dark:bg-background-dark/60">
        <HeartHandshake size={16} color={primary} />
        <Text className="ml-2 flex-1 text-sm text-foreground dark:text-foreground-dark">
          Sent to your family: {checkInText(current)}
        </Text>
        <Pressable onPress={() => setChanging(true)} accessibilityRole="button" accessibilityLabel="Change check-in" hitSlop={8} className="min-h-11 justify-center px-3">
          <Text className="text-sm font-medium" style={{ color: primary }}>
            Change
          </Text>
        </Pressable>
      </View>
    );
  }
  const send = (state: CheckInState, place?: ShelterPlace) => {
    onSend(state, place);
    setPicking(false);
    setChanging(false);
  };
  return (
    <View className="mt-3">
      <Text className="mb-2 text-xs text-muted-foreground dark:text-muted-foreground-dark">
        Let your family know. Only they see it.
      </Text>
      <View className="flex-row flex-wrap gap-2">
        <Pressable
          onPress={() => send("safe")}
          accessibilityRole="button"
          accessibilityLabel="Tell my family I'm safe"
          className="min-h-11 flex-row items-center rounded-full bg-primary px-4 dark:bg-primary-dark"
        >
          <HeartHandshake size={14} color={dark ? "#1c1416" : "#f5efe3"} />
          <Text className="ml-1.5 text-sm font-medium text-primary-foreground dark:text-primary-foreground-dark">I&apos;m safe</Text>
        </Pressable>
        <Pressable
          onPress={() => setPicking((open) => !open)}
          accessibilityRole="button"
          accessibilityLabel="Tell my family where I'm sheltering"
          accessibilityState={{ expanded: picking }}
          className="min-h-11 flex-row items-center rounded-full border border-border px-4 dark:border-border-dark"
        >
          <House size={14} color={primary} />
          <Text className="ml-1.5 text-sm text-foreground dark:text-foreground-dark">I&apos;m sheltering at…</Text>
        </Pressable>
      </View>
      {picking && (
        <View className="mt-2 flex-row flex-wrap gap-2">
          {SHELTER_PLACES.map((place) => (
            <Pressable
              key={place}
              onPress={() => send("sheltering", place)}
              accessibilityRole="button"
              accessibilityLabel={`Sheltering at ${place}`}
              className="min-h-11 justify-center rounded-full bg-card px-4 dark:bg-card-dark"
            >
              <Text className="text-sm text-foreground dark:text-foreground-dark">{place}</Text>
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}
