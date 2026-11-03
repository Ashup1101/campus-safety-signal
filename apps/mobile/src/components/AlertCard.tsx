import { ClipboardCheck, History, ShieldAlert, ShieldCheck, X } from "lucide-react-native";
import { Pressable, Text, View } from "react-native";
import { clockTime, toneOf, type Alert, type Tone } from "../shared/api";
import tokens from "../shared/tokens.json";

const ICONS: Record<Tone, typeof ShieldAlert> = {
  official: ShieldAlert,
  normal: ShieldCheck,
  drill: ClipboardCheck,
  reconstruction: History,
};

function palette(alert: Alert, dark: boolean) {
  const tone = toneOf(alert);
  const entry = tokens.alert[tone];
  return {
    Icon: ICONS[tone],
    accent: dark ? entry.dark : entry.light,
    soft: dark ? entry.softDark : entry.softLight,
    label: entry.label,
  };
}

export function AlertCard({ alert, dark }: { alert: Alert; dark: boolean }) {
  const { Icon, accent, soft, label } = palette(alert, dark);
  return (
    <View className="mb-3 rounded-xl border p-4" style={{ borderColor: accent, backgroundColor: soft }}>
      <View className="mb-1.5 flex-row items-center">
        <Icon size={16} color={accent} />
        <Text className="ml-1.5 text-xs font-semibold" style={{ color: accent }}>
          {label}
        </Text>
        <Text className="ml-auto text-xs text-muted-foreground dark:text-muted-foreground-dark">
          {clockTime(alert.received_at)}
        </Text>
      </View>
      <Text className="text-sm leading-5 text-foreground dark:text-foreground-dark">{alert.text}</Text>
    </View>
  );
}

export function AlertBanner({ alert, dark, onClose }: { alert: Alert; dark: boolean; onClose: () => void }) {
  const { Icon, accent, soft, label } = palette(alert, dark);
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
      <Pressable onPress={onClose} accessibilityLabel="Dismiss" className="p-1">
        <X size={16} color={accent} />
      </Pressable>
    </View>
  );
}
