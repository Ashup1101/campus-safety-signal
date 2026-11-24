import { HeartHandshake, MonitorSmartphone, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const ENTRIES = [
  {
    href: "/parent",
    icon: HeartHandshake,
    title: "Parent view",
    text: "Live map with activity streets, the student's location while they share, and alerts.",
  },
  {
    href: "/console",
    icon: ShieldCheck,
    title: "IUPD demo console",
    text: "Drills, replays of past nights, the latency board, and data coverage.",
  },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-[85vh] max-w-3xl flex-col justify-center gap-6 px-5 py-10">
      <div className="overflow-hidden rounded-2xl bg-foreground text-background">
        <div className="h-2 bg-primary" aria-hidden />
        <div className="px-6 py-7">
          <h1 className="text-4xl font-semibold tracking-[-0.02em] sm:text-5xl">Campus Safety Signal</h1>
          <p className="mt-3 max-w-xl text-background/80">
            IU&apos;s official alerts reach students and parents at the same moment, with a street-by-street view of
            what tonight usually looks like. Built from public data; local demo with test accounts only.
          </p>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {ENTRIES.map(({ href, icon: Icon, title, text }) => (
          <Link key={href} href={href} className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Card className="h-full transition-[background-color,transform] duration-100 hover:bg-muted active:scale-[0.99]">
              <CardHeader>
                <Icon className="mb-2 size-6 text-primary" />
                <CardTitle>{title}</CardTitle>
                <CardDescription>{text}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <MonitorSmartphone className="size-4" /> The student view runs in the iPhone Simulator (Expo Go).
      </p>
    </main>
  );
}
