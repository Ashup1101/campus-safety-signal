import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";
import { PRIVACY } from "@/content/legal";

export const metadata: Metadata = { title: "Privacy policy (draft)" };

export default function Privacy() {
  return <LegalPage doc={PRIVACY} />;
}
