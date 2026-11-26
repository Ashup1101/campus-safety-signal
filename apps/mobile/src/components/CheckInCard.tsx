import { CircleHelp, Home, Radar } from "lucide-react-native";
import { Pressable, Text, View } from "react-native";
import { bandResultText, okResultText, type Band, type BandState, type OkState } from "../shared/api";

export interface Reassure {
  band?: { state: BandState | "pending"; band?: Band; answered_at?: string };
  ok?: OkState | "pending";
  arrivedAt?: string;
}

function Action({ label, onPress, busy }: { label: string; onPress: () => void; busy: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ busy }}
      disabled={busy}
      onPress={onPress}
      className="min-h-11 flex-1 items-center justify-center rounded-full border border-border px-3 dark:border-border-dark"
    >
      <Text className="text-foreground dark:text-foreground-dark">{busy ? "Asking…" : label}</Text>
    </Pressable>
  );
}

/** "Check in" (a coarse band from the student's phone) and "Are you OK?" for one linked student.
 * Answers are words with an icon; nothing here is stored. */
export function CheckInCard({
  name,
  state,
  muted,
  onCheckIn,
  onAreYouOk,
}: {
  name: string;
  state: Reassure;
  muted: string;
  onCheckIn: () => void;
  onAreYouOk: () => void;
}) {
  const band = state.band;
  return (
    <View className="mt-3 gap-2">
      <View className="flex-row gap-2">
        <Action label="Check in" onPress={onCheckIn} busy={band?.state === "pending"} />
        <Action label="Are you OK?" onPress={onAreYouOk} busy={state.ok === "pending"} />
      </View>
      {band && band.state !== "pending" && (
        <View className="flex-row items-center gap-2" accessibilityLiveRegion="polite">
          <Radar size={16} color={muted} />
          <Text className="flex-1 text-sm text-foreground dark:text-foreground-dark">
            {bandResultText(name, { ...band, state: band.state })}
          </Text>
        </View>
      )}
      {state.ok === "pending" && (
        <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
          {name} is asked first. You will hear their answer, or &quot;No answer yet&quot; after 10 minutes.
        </Text>
      )}
      {state.ok && state.ok !== "pending" && (
        <View className="flex-row items-center gap-2" accessibilityLiveRegion="polite">
          <CircleHelp size={16} color={muted} />
          <Text className="flex-1 text-sm text-foreground dark:text-foreground-dark">{okResultText(name, state.ok)}</Text>
        </View>
      )}
      {state.arrivedAt && (
        <View className="flex-row items-center gap-2" accessibilityLiveRegion="polite">
          <Home size={16} color={muted} />
          <Text className="flex-1 text-sm text-foreground dark:text-foreground-dark">
            {name} arrived home ({new Date(state.arrivedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}).
            Sharing ended.
          </Text>
        </View>
      )}
    </View>
  );
}
