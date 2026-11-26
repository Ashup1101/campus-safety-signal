import { ChevronDown, ChevronRight, Users } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { api } from "../client";
import { NoteComposer } from "./NoteComposer";
import type { ThreadNotes } from "../shared/api";

/** Confirmed community notes under IU's alert, collapsed by default and always labeled
 * unverified. IU's own words stay the card above; notes never replace them. */
export function CommunityNotes({
  token,
  threadId,
  version,
  muted,
  student,
}: {
  token: string;
  threadId: string;
  version: number; // bumps when the server says this thread's notes changed
  muted: string;
  student?: { live: boolean; closed: boolean }; // students may post; parents read only
}) {
  const [found, setFound] = useState<ThreadNotes | null>(null);
  const [open, setOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let live = true;
    api<ThreadNotes>(`/api/threads/${encodeURIComponent(threadId)}/notes`, token).then(
      (notes) => live && setFound(notes),
      () => live && setFound(null),
    );
    return () => {
      live = false;
    };
  }, [token, threadId, version, refresh]);

  if (!found || !found.enabled) return null;
  const count = found.notes.length;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <View className="mt-3 border-t border-border pt-2 dark:border-border-dark">
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`${found.label}, ${count === 0 ? "none confirmed yet" : `${count} confirmed`}`}
        onPress={() => setOpen((o) => !o)}
        className="min-h-11 flex-row items-center gap-2"
      >
        <Chevron size={16} color={muted} />
        <Text className="text-sm text-foreground dark:text-foreground-dark">
          {found.label} · {count === 0 ? "none confirmed yet" : count}
        </Text>
      </Pressable>
      {open && (
        <View className="gap-2 pb-1">
          {count === 0 && (
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
              A note shows only after several students nearby say the same thing.
            </Text>
          )}
          {found.notes.map((group) => (
            <View key={group.tag} className="gap-1">
              <View className="flex-row items-center gap-2">
                <Users size={14} color={muted} />
                <Text className="text-sm font-medium text-foreground dark:text-foreground-dark">
                  {group.tag} · {group.people} students nearby
                </Text>
              </View>
              {group.texts.map((t) => (
                <Text key={t.id} className="pl-6 text-sm text-foreground dark:text-foreground-dark">
                  &quot;{t.text}&quot;
                </Text>
              ))}
            </View>
          ))}
          {student && (
            <NoteComposer
              key={found.mine?.tag ?? "new"}
              token={token}
              threadId={threadId}
              live={student.live}
              closed={student.closed}
              mine={found.mine}
              onSaved={() => setRefresh((n) => n + 1)}
            />
          )}
          {found.mine && found.mine.state !== "visible" && (
            <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
              Your note: {found.mine.tag}{" "}
              {found.mine.state === "held"
                ? "(waiting for a moderator)"
                : found.mine.state === "hidden"
                  ? "(hidden for review)"
                  : "(shows once others nearby agree)"}
            </Text>
          )}
        </View>
      )}
    </View>
  );
}
