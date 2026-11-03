import { Heart } from "lucide-react-native";
import { Pressable, Text, View } from "react-native";
import tokens from "../shared/tokens.json";

// Shown only inside the app while a parent's screen is open: no notification, no counts, no history.
export function CheckingInBadge({
  viewers,
  dark,
  onPause,
}: {
  viewers: string[];
  dark: boolean;
  onPause: () => void;
}) {
  if (viewers.length === 0) return null;
  const who = viewers.length === 1 ? `${viewers[0]}'s` : `${viewers.join(" and ")} are`;
  const accent = dark ? tokens.warm.dark : tokens.warm.light;
  return (
    <View
      className="flex-row items-center self-start rounded-full py-1.5 pl-3 pr-1.5"
      style={{ backgroundColor: dark ? tokens.warm.softDark : tokens.warm.softLight }}
    >
      <Heart size={14} color={accent} fill={accent} />
      <Text className="ml-1.5 text-sm" style={{ color: accent }}>
        {who} checking in 💛
      </Text>
      <Pressable
        onPress={onPause}
        accessibilityRole="button"
        className="ml-2 rounded-full bg-white/70 px-3 py-1 dark:bg-black/30"
      >
        <Text className="text-xs font-medium" style={{ color: accent }}>
          Pause
        </Text>
      </Pressable>
    </View>
  );
}
