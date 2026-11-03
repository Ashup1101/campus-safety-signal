"use client";

import { useState } from "react";
import { ParentView } from "@/components/parent-view";

export default function ParentPage() {
  const [accountId, setAccountId] = useState("parent_mom");
  return <ParentView key={accountId} accountId={accountId} onSwitch={setAccountId} />;
}
