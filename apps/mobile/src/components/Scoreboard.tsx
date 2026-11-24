import { Text, View } from "react-native";
import Svg, { Defs, Pattern, Rect } from "react-native-svg";
import type { Tonight } from "../shared/api";
import tokens from "../shared/tokens.json";

// Game day: crimson and cream stripes mark anything live (hard stops, no blend), same as the web.
export function Stripe({ dark, height = 6 }: { dark: boolean; height?: number }) {
  const crimson = dark ? tokens.brand.crimson.dark : tokens.brand.crimson.light;
  const cream = tokens.brand.surface.light;
  return (
    <Svg width="100%" height={height} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Defs>
        <Pattern id="stripe" width={16} height={16} patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
          <Rect width={8} height={16} fill={crimson} />
          <Rect x={8} width={8} height={16} fill={cream} />
        </Pattern>
      </Defs>
      <Rect width="100%" height={height} fill="url(#stripe)" />
    </Svg>
  );
}

function ago(minutes: number | null): string {
  if (minutes === null) return "None";
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h`;
  return `${Math.round(minutes / 1440)} d`;
}

// The scoreboard strip: ink panel, cream numerals, the stripe only while something is live.
export function Scoreboard({ tonight, windowLabel, dark }: { tonight: Tonight; windowLabel: string; dark: boolean }) {
  const cells = [
    {
      label: `Busiest, ${windowLabel.toLowerCase()}`,
      value: tonight.top ? tokens.activity[tonight.top.level].label : "Quiet",
      note: tonight.top?.name ?? "No busy streets",
    },
    { label: "Live alerts", value: String(tonight.live), note: tonight.live ? "Alert in progress" : "Nothing live" },
    { label: "Last alert", value: ago(tonight.lastMinutes), note: tonight.lastMinutes === null ? "No alerts yet" : "ago" },
  ];
  return (
    <View
      accessible
      accessibilityLabel={cells.map((c) => `${c.label}: ${c.value}, ${c.note}`).join(". ")}
      className="mt-3 overflow-hidden rounded-2xl bg-foreground dark:bg-foreground-dark"
    >
      {tonight.live > 0 ? <Stripe dark={dark} height={8} /> : <View className="h-2 bg-primary dark:bg-primary-dark" />}
      <View className="flex-row">
        {cells.map((cell, index) => (
          <View
            key={cell.label}
            className={`flex-1 px-3 py-3 ${index > 0 ? "border-l border-background/15 dark:border-background-dark/15" : ""}`}
          >
            <Text className="text-[11px] text-background/70 dark:text-background-dark/70" numberOfLines={1}>
              {cell.label}
            </Text>
            <Text
              className="mt-1 text-2xl font-semibold text-background dark:text-background-dark"
              style={{ fontVariant: ["tabular-nums"], letterSpacing: -0.4 }}
              numberOfLines={1}
            >
              {cell.value}
            </Text>
            <Text className="mt-1 text-xs text-background/80 dark:text-background-dark/80" numberOfLines={1}>
              {cell.note}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}
