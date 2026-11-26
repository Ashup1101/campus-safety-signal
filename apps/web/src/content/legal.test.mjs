// The draft legal pages: versions match the consent records and every required topic is covered.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DRAFT_BANNER, PRIVACY, TERMS } from "./legal.ts";

test("drafts say they need legal review and carry the consent version", () => {
  assert.match(DRAFT_BANNER, /needs legal review/);
  const server = readFileSync(new URL("../../../server/demo_server/consents.py", import.meta.url), "utf8");
  for (const doc of [PRIVACY, TERMS]) assert.ok(server.includes(`"${doc.version}"`), doc.title);
});

test("the privacy draft covers data held, retention, deletion, consent and contact", () => {
  const headings = PRIVACY.sections.map((s) => s.heading.toLowerCase()).join(" | ");
  for (const topic of ["hold", "keep", "deleting", "consent", "contact"]) assert.match(headings, new RegExp(topic));
});
