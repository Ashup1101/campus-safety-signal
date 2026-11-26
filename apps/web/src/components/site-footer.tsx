"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SERVER } from "@/lib/client";

/** On every page: not IU, the draft policy and terms, and when the public data was last updated. */
export function SiteFooter() {
  const [updated, setUpdated] = useState<string | null>(null);
  useEffect(() => {
    fetch(`${SERVER}/api/data-updated`)
      .then((r) => r.json())
      .then((d: { updated_at: string | null }) => setUpdated(d.updated_at))
      .catch(() => {});
  }, []);
  return (
    <footer className="flex flex-wrap gap-x-4 gap-y-1 px-5 py-4 text-xs text-muted-foreground">
      <span>Not an official IU service. Built from public data. Local demo with test accounts.</span>
      <span>Data last updated: {updated ? new Date(updated).toLocaleString() : "unknown"}.</span>
      <Link href="/privacy" className="underline">
        Privacy policy (draft)
      </Link>
      <Link href="/terms" className="underline">
        Terms (draft)
      </Link>
    </footer>
  );
}
