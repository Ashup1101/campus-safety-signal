import * as Location from "expo-location";
import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { api, apiSend } from "../client";
import { allowedTags, type NotesSettings, type ThreadNotes } from "../shared/api";

/** A student's own note on this alert: one tag, optional short text after the all-clear. The
 * phone's position is sent once for the nearby check and never saved. */
export function NoteComposer({
  token,
  threadId,
  live,
  closed,
  mine,
  onSaved,
}: {
  token: string;
  threadId: string;
  live: boolean;
  closed: boolean;
  mine: ThreadNotes["mine"];
  onSaved: () => void;
}) {
  const [settings, setSettings] = useState<NotesSettings | null>(null);
  const [tag, setTag] = useState<string | null>(mine?.tag ?? null);
  const [text, setText] = useState(mine?.text ?? "");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<NotesSettings>("/api/notes/config", token).then(setSettings, () => {});
  }, [token]);
  if (!settings) return null;
  const tags = allowedTags(settings, live, closed);
  const path = `/api/threads/${encodeURIComponent(threadId)}/note`;

  const save = async () => {
    if (!tag) return;
    setBusy(true);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        setNote("Location is needed once to check you are nearby. It is not saved.");
        return;
      }
      const here = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const body = { tag, text: live ? null : text.trim() || null, lat: here.coords.latitude, lon: here.coords.longitude };
      const response = await apiSend(path, token, mine ? "PUT" : "POST", body);
      const answer = (await response.json()) as { state?: string; detail?: string };
      if (!response.ok) {
        setNote(`Not posted: ${answer.detail ?? "try again"}.`);
        return;
      }
      setNote(answer.state === "held" ? "Saved. A moderator will look before it shows." : "Saved. It shows once others nearby agree.");
      onSaved();
    } catch {
      setNote("Could not post right now.");
    } finally {
      setBusy(false);
    }
  };

  const withdraw = async () => {
    setBusy(true);
    await apiSend(path, token, "DELETE").catch(() => {});
    setBusy(false);
    setNote("Your note was withdrawn.");
    onSaved();
  };

  return (
    <View className="mt-2 gap-2">
      <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
        Don&apos;t stay to post: move away first if you need to. Notes show without your name.
      </Text>
      <View className="flex-row flex-wrap gap-2" accessibilityLabel="Pick one tag">
        {tags.map((t) => (
          <Pressable
            key={t}
            accessibilityRole="button"
            accessibilityState={{ selected: tag === t }}
            onPress={() => setTag(t)}
            className={`min-h-11 justify-center rounded-full border px-3 ${tag === t ? "border-primary" : "border-border dark:border-border-dark"}`}
          >
            <Text className="text-foreground dark:text-foreground-dark">{t}</Text>
          </Pressable>
        ))}
      </View>
      {live ? (
        <Text className="text-xs text-muted-foreground dark:text-muted-foreground-dark">
          Text opens after IU&apos;s all-clear.
        </Text>
      ) : (
        <View>
          <TextInput
            accessibilityLabel="Optional short note"
            value={text}
            onChangeText={setText}
            maxLength={settings.text_limit}
            placeholder="Optional: what is useful to know about the area"
            className="min-h-11 rounded-lg border border-border px-3 text-foreground dark:border-border-dark dark:text-foreground-dark"
          />
          <Text
            accessibilityLiveRegion="polite"
            className="mt-1 text-right text-xs text-muted-foreground dark:text-muted-foreground-dark"
          >
            {text.length} of {settings.text_limit}
          </Text>
        </View>
      )}
      <View className="flex-row gap-2">
        <Pressable
          accessibilityRole="button"
          disabled={!tag || busy}
          onPress={save}
          className="min-h-11 flex-1 items-center justify-center rounded-full border border-border px-3 dark:border-border-dark"
        >
          <Text className="text-foreground dark:text-foreground-dark">{mine ? "Update my note" : "Post note"}</Text>
        </Pressable>
        {mine && (
          <Pressable
            accessibilityRole="button"
            disabled={busy}
            onPress={withdraw}
            className="min-h-11 items-center justify-center rounded-full border border-border px-3 dark:border-border-dark"
          >
            <Text className="text-foreground dark:text-foreground-dark">Withdraw</Text>
          </Pressable>
        )}
      </View>
      {note && (
        <Text accessibilityLiveRegion="polite" className="text-xs text-foreground dark:text-foreground-dark">
          {note}
        </Text>
      )}
    </View>
  );
}
