---
name: help
description: >
  Orientation for someone who just installed ADHDecoder: a two-line explanation
  of the loop-closer model plus the command cheat-sheet. Use when the user says
  things like "what can ADHDecoder do", "get started with ADHDecoder", "how do I
  use ADHDecoder", "ADHDecoder help", or "what are the commands". If config is
  missing or thin, it leads with a pointer to run setup first. Read-only; shows
  orientation, writes nothing, sends nothing.
---

# Help (orientation)

Orient a new user fast, then get out of the way. Read `reference/onboarding.md`
(the cheat-sheet + first-run rule) before running. This skill only explains and
points; it writes nothing.

## What this does / does not do

- **Explains the model in two lines**, then shows the cheat-sheet. No wall of docs.
- **Checks first-run.** If config is absent or thin (no enabled source, or no
  backend + identity), lead with "ADHDecoder isn't set up yet - want to run
  `setup`?" before the cheat-sheet, so a brand-new user has a next step.
- **Read-only.** Never writes config/state, never sends or posts.

## What to show

**The model (two lines):** ADHDecoder closes the follow-up loop. It tracks the
**promises** flowing both ways - what others owe you (chase in) and what you owe
them (radiate out) - and surfaces the one time-sensitive thing you're most at
risk of dropping. Every outward message is a draft you approve; nothing
auto-sends.

**The command cheat-sheet:**

- "what's slipping" / "who do I chase" -> chase-in
- "what's drifting / gone quiet" -> drift
- "panic" / "I'm overwhelmed" -> panic
- "where do things stand for <context>" -> radiate-out
- "is this still open / reconcile this" -> reconcile
- "<someone> owes me <X> by <date>" / replying to an ask -> set-the-clock
- "run a sweep" / "daily run" -> sweep / daily-run
- "help" / "set me up" / "check my setup" -> help / setup / doctor

If not set up yet, point to `setup`. If set up but something looks off, point to
`doctor`.

## Guardrails

- Read-only. Writes nothing, sends nothing, posts nothing.
- Keep it short - orientation, not a manual. Deeper detail lives in
  `reference/method.md` and the per-capability specs.
