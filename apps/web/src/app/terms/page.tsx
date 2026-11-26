import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";
import { TERMS } from "@/content/legal";

export const metadata: Metadata = { title: "Terms of use (draft)" };

export default function Terms() {
  return <LegalPage doc={TERMS} />;
}
