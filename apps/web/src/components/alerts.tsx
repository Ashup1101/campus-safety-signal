"use client";

import { ClipboardCheck, ExternalLink, History, ShieldAlert, ShieldCheck, X } from "lucide-react";
import type { ReactNode } from "react";
import { color, tokens } from "@/lib/client";
import { clockTime, toneOf, type Alert, type AlertThread, type Tone } from "@/shared/api";

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
  children,
}: {
  thread: AlertThread;
  dark: boolean;
  children?: ReactNode;
}) {
  const { latest, closed, tone } = thread;
  const shown = palette(closed ? "normal" : tone, dark);
  const label = closed && tone !== "normal" ? `${tokens.alert[tone].label} · All clear` : shown.label;
  const Icon = ICONS[closed ? "normal" : tone];
  const earlier = thread.alerts.slice(0, -1).reverse();
  return (
    <li className="rounded-xl border p-4" style={{ borderColor: shown.accent, background: shown.soft }}>
      <div className="mb-1.5 flex items-center gap-2 text-xs font-medium" style={{ color: shown.accent }}>
        <Icon className="size-4" />
        <span>{label}</span>
        <span className="ml-auto font-normal text-muted-foreground">{clockTime(latest.received_at)}</span>
      </div>
      <p className="text-sm leading-relaxed">{latest.text}</p>
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
    </li>
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
