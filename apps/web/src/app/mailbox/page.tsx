"use client";

import { useState } from "react";
import { MailboxView } from "@/components/mailbox-view";

export default function MailboxPage() {
  const [accountId, setAccountId] = useState("parent_mom");
  return <MailboxView key={accountId} accountId={accountId} onSwitch={setAccountId} />;
}
