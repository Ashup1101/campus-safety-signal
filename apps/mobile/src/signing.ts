// Answering a parent's check-in: one location reading -> band -> signed answer. Only the band
// word leaves the phone. Off, no home area, no key or no location: the parent is told the student
// hasn't turned on check-ins (declined), never a guess.
import * as Location from "expo-location";
import { homeArea, reassurance, signingKey } from "./home";
import { bandOf, signBand, type ClientMessage } from "./shared/api";

export async function answerBand(requestId: string): Promise<ClientMessage> {
  const declined: ClientMessage = { type: "band_answer", request_id: requestId, declined: true };
  const [settings, home, key] = await Promise.all([reassurance.get(), homeArea.get(), signingKey.get()]);
  if (!settings.bandAnswers || !home || !key) return declined;
  try {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status !== "granted") return declined;
    const here = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    const band = bandOf({ lat: here.coords.latitude, lon: here.coords.longitude }, home);
    const answeredAt = new Date().toISOString();
    return {
      type: "band_answer",
      request_id: requestId,
      band,
      answered_at: answeredAt,
      signature: signBand(key.secret, requestId, band, answeredAt),
    };
  } catch {
    return declined;
  }
}
