import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Campus Safety Signal demo",
  description: "Local IUPD demo: official alerts, consent-based sharing, activity map.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <div className="flex-1">{children}</div>
        <footer className="px-5 py-4 text-xs text-muted-foreground">
          Not an official IU service. Built from public data. Local demo with test accounts.
        </footer>
      </body>
    </html>
  );
}
