# ADHDecoder — Parity Port (build spec)

Build input. Drop into the repo as `reference/parity-port.md`. Written
2026-07-27. This ports the proven sweep TECHNIQUES from the user's prior
homegrown decoder into ADHDecoder **generically**. Every technique below is
user-agnostic; all specifics (handles, channel lists, watched accounts,
timezone, noise patterns) live in the user's instance config / context
directory, never in the plugin.

Principle: **technique -> plugin, specifics -> config.** No names, customers,
ids, or channels in these files.

## Chat adapter (the biggest gap-closer)

Search alone is unreliable and silently returns zero for messages that exist.
So layer three passes every run:

1. **Mention-token search** for the user's handle (from `config.identity`), over
   a window of `lastSwept - overlap` to now (a few hours of overlap absorbs
   search-index lag). Plus a recipient/`to:` pass for DMs.
2. **Known-channel registry backstop.** Keep a self-expanding list (in
   `state.json`) of channels the user has appeared in; each run, read those
   channels directly since `lastSwept` and scan for the user's mentions,
   regardless of what search returned. Add a channel the first time it produces
   a hit; never remove it. This is the real safety net for the "search returned
   empty but a real mention exists" failure.
3. **Silent-reply tracking.** Track threads the user has posted in
   (channel + parent ts, in `state.json`); re-read them each run and surface new
   replies since `lastSwept` even when they never re-mention the user.

On any hit, read the FULL thread before deciding (the prior messages carry the
substance). Specifics -> config: the user's handle, the registry (auto-built).

## Issue-tracker adapter

- **Timezone-correct filtering.** The tracker's query datetimes may be in a
  different timezone than the user; convert the since-cutoff to the tracker's tz,
  or filter by each issue's own `updated` offset. Do not trust a naive datetime
  filter. (Config: the tracker's timezone.)
- **Sync-noise recognition.** Recurring non-activity timestamp bumps (e.g. a
  nightly bulk-sync) are not real activity; a bump alone is not "new activity."
  (Config: an optional known-noise pattern, e.g. a recurring bump time.)
- **Priority persistence.** An item at or above a high-priority threshold that
  is assigned to / mentions / is watched by the user stays flagged until it is
  closed or explicitly reassigned away, never dropped just because "no new
  comment." A quiet high-priority item is not a resolved one. (Config: the
  threshold.)
- **Buckets:** assignee, comment-mentions, watcher (with new activity).

## CRM adapter

- Sweep open records (e.g. cases) on the user's **watched accounts** (from the
  context directory) AND records where the user is owner or a follower.
- **Severity / SLA thresholds always flag** on a watched account (config: which
  tiers).
- A "blocked on our team" internal-dependency value = an action item, not FYI.
- Treat CRM datetimes per its own timezone (often UTC).
- If a record links to a tracker issue, it is the SAME work item, decode once,
  cross-reference both ids.

## Calendar adapter

- Query the calendar **directly** for events changed since `lastSwept`,
  self-created / self-organized events leave no email trail, so email alone
  misses them.
- Decode substantive changes only: new event, time/date change, attendee
  add/drop, real agenda edit. Skip pure RSVP-status changes.

## Call-intelligence + meeting-notes adapters

- Only count meetings the user actually **attended** (confirm attendance, do not
  trust an org-wide feed).
- Extract **user-owned** action items / follow-ups.
- **Dedup across both:** one meeting can produce a call record AND a notes doc;
  decode once, prefer the richer source, cross-reference the other.
- Treat auto-generated notes as **lossy**: match names loosely, and use them
  only as last-resort corroboration, never as the lead source (they mislabel
  owners and bury direct mentions).

## Docs adapter

- Mentions of the user in comments, and others' edits/comments on pages the user
  authored. Never surface the user's own edits back at them.

## Cross-cutting (apply across adapters)

- **Context enrichment before creating.** Before recording a swept item as a NEW
  promise, match it against existing promises (by source ref/key, or
  context + topic). If it matches, **enrich/attach** (update lastVerified, add a
  history line) rather than create a duplicate. Only decode as new if it maps to
  nothing.
- **Research/reconcile source order.** When verifying or researching a single
  item, check sources in the configured **weight** order (chat/email/issues/...);
  lead with the source that actually assigns ownership. Auto-notes are
  last-resort corroboration, never the lead.
- **Draft/nudge judgment (from prior feedback):**
  - Internal-teammate nudges are collaborative sanity-checks ("does that sound
    right?"), not deadline-y chases; keep the deadline tone for the counterparty.
  - Never chase vague "go find out X", a chase needs a named owner + a concrete
    ask + a date (the reality gate).
  - Distinguish the internal team from the counterparty; do not chase the wrong
    side.
  - Route real technical build work to its owner with a worked example; do not
    have the user guess technical artifacts.

## Where specifics live (not in the plugin)

- `config.identity`: the user's handles/tokens per source.
- `config.sources[]`: enabled sources + provider + weight + cadence + tz + any
  noise pattern.
- `config.contacts` (context directory): watched accounts, channels, people.
- `state.json`: the auto-built channel registry, silent-reply thread set, dedup,
  snooze/verify metadata.

## Build scope

Enhance the existing per-source adapters (chat, email, issues, crm) and add/flesh
calendar, docs, and calls adapters, all with the generic techniques above.
Add context-enrichment to the sweep's write path. Keep everything generic;
grep for any personal/company identifiers before committing.
