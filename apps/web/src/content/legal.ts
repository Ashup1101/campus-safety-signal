// Draft privacy policy and terms for the local pilot. Plain data so a lawyer can review the words
// and the pages render them as written. Version strings match the consent records (consents.py).

export interface LegalDoc {
  title: string;
  version: string;
  updated: string;
  sections: { heading: string; paragraphs: string[] }[];
}

export const DRAFT_BANNER = "Draft: needs legal review. Not in effect; for the local pilot demo only.";

export const PRIVACY: LegalDoc = {
  title: "Privacy policy (draft)",
  version: "2026-11-draft-1",
  updated: "2026-11-26",
  sections: [
    {
      heading: "What this service is",
      paragraphs: [
        "Campus Safety Signal relays official IU alerts and shows patterns built from public data. It is not an official IU service.",
      ],
    },
    {
      heading: "What we hold about you",
      paragraphs: [
        "Your account: email address, display name and role (student or parent), and who you are linked with and the relationship you chose.",
        "Your choices: which features you agreed to (with the policy version and time), your watch zones, and your subscription settings.",
        "Survey answers as numbers only, and counts of how alerts reached your devices.",
      ],
    },
    {
      heading: "What we never hold",
      paragraphs: [
        "Your location history. Live location is shared only when you turn sharing on, held in memory while a linked parent is viewing, and never saved.",
        "Check-in answers: your phone sends one word (in your home area, near home or on campus, or away) to the parent who asked, and it is not kept. Your home area stays on your phone.",
      ],
    },
    {
      heading: "Consent",
      paragraphs: [
        "Precise location, sharing with parents, community notes, digests and briefings each need your yes, asked when you first use them. You can say no and still get official alerts.",
        "You can withdraw any consent in Settings; the feature stops at once.",
      ],
    },
    {
      heading: "How long we keep things",
      paragraphs: [
        "Community notes are deleted 24 hours after the incident closes. Sign-in links expire after 15 minutes.",
        "Everything else stays until you delete your account.",
      ],
    },
    {
      heading: "Deleting your data",
      paragraphs: [
        "Delete my account (Settings) removes your account, links, invites, zones, inbox, consents, subscriptions, notes and survey answers right away. Deleted records are overwritten in the database.",
      ],
    },
    {
      heading: "Contact",
      paragraphs: ["Questions about this draft: open an issue on the project's public repository."],
    },
  ],
};

export const TERMS: LegalDoc = {
  title: "Terms of use (draft)",
  version: "2026-11-draft-1",
  updated: "2026-11-26",
  sections: [
    {
      heading: "Not an emergency service",
      paragraphs: [
        "In an emergency call 911. This service can be late, incomplete or unavailable, and it relays IU's own words without changing them.",
      ],
    },
    {
      heading: "Not an official IU service",
      paragraphs: ["IU and IUPD do not run or endorse this demo. Official alerts come from IU's public channels."],
    },
    {
      heading: "Community notes",
      paragraphs: [
        "Notes are unverified. Do not post names, descriptions of people, contact details, links or requests for money. Do not stay in an unsafe place to post.",
        "Notes can be hidden by reports or moderators, and IU can switch them off.",
      ],
    },
    {
      heading: "Activity levels and forecasts",
      paragraphs: [
        "Quiet, Elevated and High describe how often incidents or calls for service happened, not whether a place is safe. Calls for service are not crimes.",
      ],
    },
    {
      heading: "Changes",
      paragraphs: ["A new version will be shown with its date, and features that need consent will ask again."],
    },
  ],
};
