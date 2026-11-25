import { Inbox as InboxIcon } from "lucide-react-native";
import { Text, View } from "react-native";

// The local mailbox in the app: briefings, digests and follow-ups (the demo's stand-in for email).
export interface MailboxMessage {
  id: number;
  kind: "briefing" | "digest" | "alert" | "correction" | "all_clear";
  subject: string;
  body: string;
  created_at: string;
}

const KIND: Record<MailboxMessage["kind"], string> = {
  briefing: "Before the night",
  digest: "Digest",
  alert: "Alert",
  correction: "Correction",
  all_clear: "All clear",
};
const SHOWN = 3;

export function Inbox({ messages, muted }: { messages: MailboxMessage[]; muted: string }) {
  return (
    <View className="mt-3 rounded-xl bg-card p-4 dark:bg-card-dark">
      <View className="mb-2 flex-row items-center gap-2">
        <InboxIcon size={18} color={muted} />
        <Text className="font-semibold text-foreground dark:text-foreground-dark">Inbox</Text>
      </View>
      {messages.length === 0 ? (
        <Text className="text-sm text-muted-foreground dark:text-muted-foreground-dark">
          Briefings arrive the afternoon before an event night; digests at 7 am when there is something to report.
        </Text>
      ) : (
        messages.slice(0, SHOWN).map((m) => (
          <View key={m.id} className="mt-2">
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
              {KIND[m.kind]} · {new Date(m.created_at).toLocaleString()}
            </Text>
            <Text className="font-medium text-foreground dark:text-foreground-dark">{m.subject}</Text>
            <Text className="text-sm text-foreground dark:text-foreground-dark" numberOfLines={4}>
              {m.body}
            </Text>
          </View>
        ))
      )}
    </View>
  );
}
