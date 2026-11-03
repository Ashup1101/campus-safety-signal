"use client";

import { ClipboardCheck, ExternalLink, History, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { color, tokens } from "@/lib/client";
import { clockTime, toneOf, type Alert, type Tone } from "@/shared/api";

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

export function AlertCard({ alert, dark }: { alert: Alert; dark: boolean }) {
  const tone = toneOf(alert);
  const { accent, soft, label } = palette(tone, dark);
  const Icon = ICONS[tone];
  return (
    <li className="rounded-xl border p-4" style={{ borderColor: accent, background: soft }}>
      <div className="mb-1.5 flex items-center gap-2 text-xs font-medium" style={{ color: accent }}>
        <Icon className="size-4" />
        <span>{label}</span>
        <span className="ml-auto font-normal text-muted-foreground">
          received {clockTime(alert.received_at)}
        </span>
      </div>
      <p className="text-sm leading-relaxed">{alert.text}</p>
      {alert.link && (
        <a
          href={alert.link}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:underline"
        >
          Source <ExternalLink className="size-3" />
        </a>
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
