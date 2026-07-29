# ADHDecoder — The Method

The durable brain of ADHDecoder. Portable, no personal or company data. Skills
reference this. Read it to understand what the system is trying to do.

## The core reframe

Most tools catch what comes **in**. They have no sense of **time** or
**promises**, so the follow-up loop leaks. ADHDecoder closes the loop. It
leaks in two directions:

- **Chase in:** you lose track of what others owe *you*.
- **Radiate out:** others chase *you*, because your updates do not land where
  they look.

Three loop-closers, one shape:

1. **Set the clock** (info goes out): capture the promised-by date.
2. **Chase in** (a date passes): nudge to chase, precisely.
3. **Radiate out** (proactive status): publish so nobody chases you.

Plus **panic button** (reactive spiral-breaker) and **drift** (are you on
target or wandering) riding alongside.

## The ADHD design principles

These override convenience. Every feature obeys them.

- **Eat the grunt.** Do the toil (draft, aggregate, pre-fill) so the only part
  left for the user is judgment and a send. "Review + approve" is doable;
  "go do the boring thing" is not.
- **One move.** Surface a single, absurdly small next step to beat activation
  energy.
- **No flood.** Dedup hard. Overdue items get more prominent, not more numerous.
- **Track at the promise level, not sub-task minutia.**
- **Advisor by default.** Most items are "they owe the doing, the user owes the
  guidance." Route real technical build work to the right owner, do not fake it.
- **Boring beats shiny is the enemy.** The failure mode is drift, not
  forgetting: time-sensitive grunt work slips because it is not interesting.
  Defend against that specifically.
- **De-escalate.** No wall of red. Make things smaller.

## The decode format

For every new item, produce this block:

```
## [SOURCE-ID] — [short title] ([customer/context])

**THE ASK** — what is requested, in one or two lines. Who asked, and when.
**WHO** — requester + role; anyone already doing part; SMEs; cc/FYI.
**YOUR ROLE** — what the user specifically owns. Concrete, behavioral.
**NOT YOUR ROLE** — what others own.
**DONE LOOKS LIKE** — the concrete finished state.
**WHAT'S MISSING (blockers)** — open questions to resolve before acting.
**SET THE CLOCK** — who owes what back, by when (feeds the ledger). Ask it.
**FLAG (only if real)** — risk, sensitivity, bigger-than-it-looks.
**DRAFT REPLY** — a ready-to-send confirmation that restates the ask, names
what is needed, and sets the clock. Approve and send. Never auto-posted.
```

## The promise triple (what the ledger owns)

A promise is not a new object; it is a missing field on things already tracked.
The ledger owns only: **expect-by date + who-owes + direction**. Everything
else it references. See `ledger-schema.md`.

- **Direction:** `they-owe-me` (chase them) or `i-owe-them` (do it, or send a
  holding status).
- A promise becomes chaseable only when real: **named owner + concrete
  deliverable + a date** (or user confirmation). Vague "go find out X" never
  becomes a chase.

## Stakes (auto-inferred, never hand-tagged)

Computed each sweep from signals the sources already expose:

- CRM S1/S2 severity or T1/T2 SLA tier
- Issue-tracker priority High or above
- A go-live within ~2 weeks
- An expect-by date within ~2 days
- A `why` naming a go-live or a dated dependency raises stakes to high
- An explicit PCI / security / bigger-than-it-looks flag
- A watchlist customer raises stakes; internal lowers them (tiebreak)

Optional manual override: the user may pin high or mute low. Never required.

## Chase in

Tiered by stakes: high-stakes get proactive early nudges; the rest stay quiet
until overdue. A promise changes **state** (due-soon -> due-today -> overdue ->
aging), it does not repeat. Aging overdue items get louder, never drop silently.
Each chase hands the user a ready-to-send, specific nudge. Escalation ladder:
friendly check-in -> firmer + restate impact -> loop in a manager. Auto-close
when met (reply landed, issue moved).

## Panic button (reactive)

The user triggers it mid-spiral. It regulates, it does not aggregate. Output:
most time-sensitive first; a drift check (what is due vs what the user has
visibly touched); the one item being avoided (time-sensitive AND grunt); one
small move. Pure ephemeral: renders in chat, never written to the knowledge
base.

## Drift

Runs on the panic button AND as a quiet passive flag each sweep. It sees only
**digital** activity, so it frames observationally ("hasn't visibly moved in N
days"), offers a one-tap "handled offline" clear (with an optional skippable
note), and cools down after clearing. Fires only on time-sensitive items.

## Guardrails (hard)

- Never auto-send, never auto-post. Drafts only.
- Never auto-create tasks; promotion is deliberate.
- Hide raw feeds; decoded shortlist only, one click to source.
- Verified-only goes to any customer-facing surface.
- **Verified before surfaced.** Never present a promise as a settled fact or a
  required action without a fresh reconcile verdict shown inline. A search
  snippet is never enough: read the full source thread and the backing note
  first. See `reference/verification-discipline.md`.
- **First run.** If config is absent or thin (no enabled source, or missing
  backend + identity), offer `setup` rather than erroring, inventing paths, or
  returning an empty board. See `reference/onboarding.md`.
- No hidden files; single writer per synced location.
