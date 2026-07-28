# ADHDecoder — Radiate Out (Phase 4) Spec

Build input. Drop into the plugin repo as `reference/radiate-out.md`, then build
`skills/radiate-out/SKILL.md`. Written 2026-07-27. This is the customer-facing
loop-closer, so the safety gates are the point.

## Purpose

Publish status **outward** so people stop chasing the user ("where does this
stand?"). Reads the ledger, composes a short per-context status, and hands the
user a ready-to-publish **draft**. It is the mirror of chase-in: chase-in nudges
others; radiate-out tells others where things stand before they ask.

## Generic

- Store-agnostic: reads the ledger through the same Query interface as chase-in
  / drift / panic (so it works on `state.json` or a read-only backend
  unchanged). Group by the promise `context` / customer field.
- Target-agnostic: the publish target is a configured `~~chat` canvas/channel,
  or simply a copyable draft. No storage/chat product specifics in the core skill.

## Two modes

1. **Status board (proactive).** Per customer/context, compose a short
   "Where things stand" summary, grouped:
   - **In flight** (we're on it) - open `i-owe-them` promises.
   - **Waiting on you** (them) - open `they-owe-me` promises.
   - **Recently shipped** - promises closed/met in the last ~1-2 weeks.
   Output is a DRAFT the user reviews and posts. Batched: one review per context.

2. **Already-answered catch (reactive).** When someone asks "any update on X?",
   locate the user's last status/answer on X (from the ledger + source link) and
   hand the user that link plus a one-line re-point draft, so answering again
   costs seconds instead of a re-dig.

## Hard gates (customer-facing, do not skip)

- **Never auto-post, never auto-send.** Everything is a draft the user
  explicitly publishes. This keeps the standing never-auto-post guardrail.
- **Verified-only goes outward.** Only include items confirmed against the
  source of truth. Anything unverified or possibly-stale is WITHHELD from the
  customer draft and flagged to the user as "confirm before sending." A wrong
  public status is worse than no status.
- **Plain, reassuring tone.** Customer-facing copy. No internal jargon, no
  ticket-speak, no blame.

## Output

- Per context: a short, scannable status draft (In flight / Waiting on you /
  Recently shipped), each line one promise, linking to its source.
- Plus, held separately, a "confirm before sending" list of anything unverified,
  so the user decides what is safe to publish.
- The user approves and posts. ADHDecoder posts nothing itself in v1.

## Defer (not this build)

- Auto-publishing / live canvas sync (needs the freshness ritual and a mature
  verification pipeline; decided earlier as draft-and-user-publishes, batched).
- Full source reconciliation behind "verified" (depends on the sweep's verify
  pipeline maturing; today, treat a promise as verified only if its source
  status was confirmed, otherwise it goes in the "confirm before sending" list).

## Guardrails recap

Never auto-send / auto-post / auto-create tasks. Drafts only. Verified-only
outward. No hidden files. Reads the ledger backend; writes nothing outward.
