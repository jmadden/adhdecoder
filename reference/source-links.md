# ADHDecoder — Source Links on Action Items (build spec)

Build input. Drop into the repo as `reference/source-links.md`. Written
2026-07-27. Generic; no personal or company data.

## Problem

The rule exists (every promise has a `source`; surfaces are spec'd to show a
source link; "link, never paste"), but the link quality is weak:

- A TaskNotes-derived promise gets `source` = an `obsidian://` link to the NOTE,
  not the underlying issue / chat thread / email the action actually lives in.
- Reconcile discovers the real live source (the ticket, the chat permalink, the
  sent email) but does not write it back, so it is found then discarded.

Goal: every action item carries a one-click link to the **real** source, and
reconcile's discovered link is kept and shown.

## Schema (reference/ledger-schema.md)

- **`source`** `{ type, ref, url }`: the best **actionable** source, prefer the
  underlying ticket / chat permalink / email over a note link.
- **`noteRef`** (optional) `{ url }`: the `obsidian://` (or file) link to the
  backing note, so the record is still one click away. Distinct from `source`.
- If no underlying source can be found, `source` falls back to the note link,
  flagged `noteOnly: true`.

## Capture (where the link comes from)

1. **TaskNotes adapter.** When reading a note, EXTRACT underlying source refs
   from its frontmatter/body and set `source` to the most relevant, `noteRef`
   to the note link:
   - issue keys (e.g. `ISSUE-123` pattern) -> build the tracker issue URL;
   - chat permalinks / archive URLs found in the body;
   - email/thread ids, doc/wiki URLs, CRM case numbers -> their canonical URL.
   Most relevant wins; if none found, `noteOnly: true` with the note link.
2. **Sweep.** When it records a promise from a swept item, set `source` to that
   item's **canonical permalink** (issue URL; chat permalink from channel id +
   message ts; email thread; CRM record URL), not a paraphrase.
3. **Reconcile.** When it locates/confirms the live source, **write that link
   back** onto the promise's `source` (upgrading a note-only link). Persist per
   backend: `state.json`-backed promises persist it via the ledger; for a
   read-only TaskNotes promise, persist the enriched link in the `state.json`
   companion keyed by item id (same pattern as `snoozedUntil` / verify metadata,
   never written to the note).

## Surface (where the link shows)

- **chase-in / drift / panic / internal boards:** each item's fact line includes
  a clickable **`source.url`**; optionally the `noteRef` too. Prefer the
  actionable source; if `noteOnly`, show the note link (a small "(note)" hint is
  fine).
- **radiate-out (customer-facing):** do NOT put internal links (tracker/chat/
  internal docs) into a draft meant for a customer. Customer drafts either omit
  links or include only customer-appropriate ones. This is a hard rule, an
  internal Jira/Slack link must never land in customer-facing copy.

## Guardrails

- **Read-only preserved:** reconcile's source-link enrichment for TaskNotes goes
  to the `state.json` companion, never the note or the source.
- **Link, never paste** raw content.
- **No internal links in customer-facing output** (see radiate-out above).
- No hidden files; never auto-send / auto-post.

## Build scope (v1)

- TaskNotes adapter: extract underlying refs -> `source` + `noteRef` (+
  `noteOnly` fallback).
- Sweep: emit canonical permalinks as `source`.
- Reconcile: write the discovered source link back (persist per backend rules).
- Surfaces: render `source.url` per item on internal boards; strip internal
  links from customer-facing radiate-out drafts.
