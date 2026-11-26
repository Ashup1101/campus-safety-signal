import Link from "next/link";
import { DRAFT_BANNER, type LegalDoc } from "@/content/legal";

/** A draft legal document: banner first, version and date shown, plain headings and paragraphs. */
export function LegalPage({ doc }: { doc: LegalDoc }) {
  return (
    <main className="mx-auto max-w-2xl space-y-6 px-5 py-8">
      <p role="note" className="rounded-lg border-2 border-dashed p-3 text-sm font-medium">
        {DRAFT_BANNER}
      </p>
      <header>
        <h1 className="text-2xl font-semibold">{doc.title}</h1>
        <p className="text-sm text-muted-foreground">
          Version {doc.version}, updated {doc.updated}.
        </p>
      </header>
      {doc.sections.map((s) => (
        <section key={s.heading} className="space-y-2">
          <h2 className="text-lg font-medium">{s.heading}</h2>
          {s.paragraphs.map((p) => (
            <p key={p} className="text-sm leading-6">
              {p}
            </p>
          ))}
        </section>
      ))}
      <nav className="flex gap-4 text-sm underline">
        <Link href="/privacy">Privacy policy</Link>
        <Link href="/terms">Terms of use</Link>
      </nav>
    </main>
  );
}
