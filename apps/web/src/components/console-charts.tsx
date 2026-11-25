"use client";

import { useState, type ReactNode } from "react";

/** A chart with its text equivalent: one button switches between the picture and a table of
 * the same numbers, so nothing on the console is readable only as a picture or a color. */
export function ChartWithTable({ title, chart, table }: { title: string; chart: ReactNode; table: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="space-y-2">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium">{title}</span>
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => setAsTable((t) => !t)}
          className="rounded-md border px-2 py-1 text-xs aria-pressed:bg-secondary"
        >
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </figcaption>
      {asTable ? <div className="overflow-x-auto">{table}</div> : chart}
    </figure>
  );
}
