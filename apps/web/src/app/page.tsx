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
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 px-5 py-10">
      <div>
        <h1 className="text-2xl font-semibold">Campus Safety Signal</h1>
        <p className="text-muted-foreground">Local demo with test accounts only. Nothing here is hosted.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {ENTRIES.map(({ href, icon: Icon, title, text }) => (
          <Link key={href} href={href} className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Card className="h-full transition-colors hover:bg-muted">
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
