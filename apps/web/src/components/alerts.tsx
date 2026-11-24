"use client";

import { ClipboardCheck, ExternalLink, HeartHandshake, History, ShieldAlert, ShieldCheck, X } from "lucide-react";
import type { ReactNode } from "react";
import { color, tokens } from "@/lib/client";
import {
  areaSketch,
  areaStreets,
  checkInText,
  clockTime,
  toneOf,
  type Alert,
  type AlertThread,
  type CheckIn,
  type SegmentFeature,
  type Tone,
} from "@/shared/api";

const ICONS: Record<Tone, typeof ShieldAlert> = {
  official: ShieldAlert,
  normal: ShieldCheck,
  drill: ClipboardCheck,
  reconstruction: History,
};

function palette(tone: Tone, dark: boolean) {
  const entry = tokens.alert[tone];
  return { accent: color(entry, dark), soft: dark ? entry.softDark : entry.softLight, label: entry.label };
}

// One card per incident: IU's latest words, its updates beneath, and the all-clear closing it.
// Red only while a live official alert is open; a closed card turns calm.
export function ThreadCard({
  thread,
  dark,
  variant = "gameday",
  features = [],
  children,
}: {
  thread: AlertThread;
  dark: boolean;
  variant?: "gameday" | "strava";
  features?: SegmentFeature[];
  children?: ReactNode;
}) {
  const { latest, closed, live, tone } = thread;
  // Live: the source's own tone (red only for a live official alert). Closed: calm all-clear.
  // Quiet for 6 h without an all-clear: grey, never claiming it is over.
  const look: Tone = closed ? "normal" : live ? tone : "reconstruction";
  const shown = palette(look, dark);
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
    <li className="overflow-hidden rounded-xl border" style={{ borderColor: shown.accent, background: shown.soft }}>
      {variant === "gameday" && live && <div className="stripe-live h-1.5" aria-hidden />}
      <div className="p-4">
      <div className="mb-1.5 flex items-center gap-2 text-xs font-medium" style={{ color: shown.accent }}>
        <Icon className="size-4" />
        <span>{label}</span>
        {live && (
          // A slow pulse (Tailwind's 2 s cycle, well under 3 flashes per second), off with reduced motion.
          <span className="inline-flex items-center gap-1 font-normal">
            <span className="size-2 rounded-full motion-safe:animate-pulse" style={{ background: shown.accent }} aria-hidden />
            Live
          </span>
        )}
        <span className="ml-auto font-normal text-muted-foreground">{clockTime(latest.received_at)}</span>
      </div>
      <p className={variant === "gameday" ? "text-base font-medium leading-snug" : "text-sm leading-relaxed"}>{latest.text}</p>
      {variant === "strava" && (
        <div className="numerals mt-2 flex gap-4 text-xs text-muted-foreground">
          <span>
            <span className="text-base font-semibold text-foreground">{thread.alerts.length}</span> {thread.alerts.length === 1 ? "message" : "messages"}
          </span>
          <span>
            <span className="text-base font-semibold text-foreground">{thread.area.length}</span> {thread.area.length === 1 ? "street segment" : "street segments"}
          </span>
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          Sent {clockTime(latest.official_at)} · received {clockTime(latest.received_at)}
        </span>
        {latest.link && (
          <a
            href={latest.link}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
          >
            Source <ExternalLink className="size-3" />
          </a>
        )}
      </div>
      <AreaSketch features={features} area={thread.area} accent={shown.accent} />
      {children}
      {earlier.length > 0 && (
        <div className="mt-3 border-t pt-2" style={{ borderColor: `${shown.accent}40` }}>
          <div className="mb-1 text-xs font-semibold text-muted-foreground">Earlier updates</div>
          <ul className="space-y-1">
            {earlier.map((alert) => (
              <li key={alert.id} className="text-xs leading-snug text-muted-foreground">
                {clockTime(alert.received_at)} · {alert.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      </div>
    </li>
  );
}

// What the student chose to tell their family during this alert. Private to linked family.
export function CheckInLine({ checkIn }: { checkIn: CheckIn }) {
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg bg-background/60 px-3 py-2 text-sm">
      <HeartHandshake className="size-4 shrink-0 text-primary" aria-hidden />
      <span>
        <span className="font-medium">{checkIn.student_name}:</span> {checkInText(checkIn)}
      </span>
      <span className="ml-auto text-xs text-muted-foreground">{clockTime(checkIn.at)}</span>
    </div>
  );
}

export function AlertBanner({
  alert,
  dark,
  onClose,
}: {
  alert: Alert;
  dark: boolean;
  onClose: () => void;
}) {
  const tone = toneOf(alert);
  const { accent, soft, label } = palette(tone, dark);
  const Icon = ICONS[tone];
  return (
    <div
      role="alert"
      className="sticky top-0 z-20 flex items-start gap-3 border-b px-5 py-3"
      style={{ background: soft, borderColor: accent }}
    >
      <Icon className="mt-0.5 size-5 shrink-0" style={{ color: accent }} />
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold" style={{ color: accent }}>
          {label}
        </div>
        <p className="text-sm">{alert.text}</p>
      </div>
      <button aria-label="Dismiss" onClick={onClose} className="rounded-full p-1 hover:bg-black/5">
        <X className="size-4" />
      </button>
    </div>
  );
}

// The streets IU's text names, highlighted on a faint sketch of the demo streets. Text names the
// streets too, so it never depends on color alone.
export function AreaSketch({
  features,
  area,
  accent,
}: {
  features: SegmentFeature[];
  area: string[];
  accent: string;
}) {
  const paths = areaSketch(features, area, 240, 120);
  if (paths.length === 0) return null;
  const streets = areaStreets(features, area).join(", ");
  return (
    <figure className="mt-3">
      <svg viewBox="0 0 240 120" className="h-24 w-full rounded-lg bg-background/60" role="img" aria-label={`Map: ${streets}`}>
        {paths.map((p) => (
          <path
            key={p.id}
            d={p.d}
            fill="none"
            stroke={p.inArea ? accent : "currentColor"}
            strokeOpacity={p.inArea ? 1 : 0.45}
            strokeWidth={p.inArea ? 5 : 2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <figcaption className="mt-1 text-xs text-muted-foreground">Area named in the alert: {streets}</figcaption>
    </figure>
  );
}
