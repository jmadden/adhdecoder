#!/usr/bin/env python3
"""What reconcile needs to verify this run, and in what order. Stdlib only, read-only.

Reconcile's *judgment* is not here and cannot be: reading a Jira ticket or a
Slack thread and deciding resolved / reassigned / still-open needs a live source
and a reader. What IS mechanical, and was being re-derived on every item on
every run, is:

    - the TTL cache decision (is this verdict still fresh enough to reuse?)
    - the order to work in (source weight, urgency first)
    - the mis-attribution lookup against `config.contacts`

The TTL one is the expensive mistake. Re-hitting every source for every promise
on every run costs real API calls; skipping a stale verdict quietly chases a
closed ticket. Both failures come from a judgement call made in prose, one item
at a time.

Usage:
    reconcile_plan.py --config CFG [--now ISO] [--ttl-hours 24]
                      [--select slipping] [--id ID ...] [--json]

Exit 0 always when the config reads; the plan is the output, not a verdict.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_query as lq  # noqa: E402

DEFAULT_TTL_HOURS = 24
WEIGHT_ORDER = {"high": 0, "medium": 1, "low": 2}


def word_in(needle, haystack):
    """Whole-word, case-insensitive containment. Same rule as pronoun matching:
    a short name must not match inside a longer unrelated word."""
    if not needle or not haystack:
        return False
    return bool(re.search(r"(?<!\w)%s(?!\w)" % re.escape(str(needle).lower()),
                          str(haystack).lower()))


def hours_since(stamp, now):
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if when.tzinfo is not None and now.tzinfo is None:
        when = when.replace(tzinfo=None)
    elif when.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return (now - when).total_seconds() / 3600.0


def ttl_decision(promise, now, ttl_hours):
    """Reuse the cached verdict, or re-verify? Returns (verify, reason)."""
    status = promise.get("verifyStatus")
    age = hours_since(promise.get("lastVerified"), now)
    if not status:
        return True, "never verified"
    if age is None:
        return True, "verified %r but no readable lastVerified" % status
    if age >= ttl_hours:
        return True, "cached %r is %.1fh old (TTL %dh)" % (status, age, ttl_hours)
    return False, "cached %r is %.1fh old, still fresh" % (status, age)


def source_weight(config):
    """Map source type -> configured weight, for ordering."""
    weights = {}
    for source in config.raw.get("sources") or []:
        weights[str(source.get("type"))] = str(source.get("weight") or "medium").lower()
    return weights


def misattribution_signal(promise, contacts, identity_name):
    """An ADVISORY flag, never a verdict. Returns a dict or None.

    `reference/reconciliation.md` originally specified this as decisive: an owner
    not listed in that context's `contacts.people` makes the promise
    `mis-attributed` regardless of what the source says. Measured against a real
    ledger that rule fired on 8 of 10 checkable promises, and nearly all were
    false: real `owner` values are prose describing a party - a vendor
    ("Acme Telecom/Northwind"), a team ("platform triage"), an org ("Acme Corp
    (customer)"), or several people at once - not a single roster name.

    So the mechanical check only speaks when it has real evidence: the owner
    names someone who IS on another context's roster but not this one. An owner
    naming nobody recognisable is not evidence of anything and stays silent.
    Even then it is a prompt to confirm, not a verdict - the adapter's reading of
    the live source outranks it.
    """
    context = promise.get("context")
    owner = promise.get("owner") or ""
    if not context or context not in contacts or not owner:
        return None
    if word_in(identity_name, owner) or owner.strip().lower() in ("self", "unassigned", ""):
        return None

    on_this = [n for n in (contacts[context].get("people") or []) if word_in(n, owner)]
    if on_this:
        return None

    elsewhere = {}
    for other, entry in contacts.items():
        if other == context:
            continue
        for person in entry.get("people") or []:
            if word_in(person, owner):
                elsewhere.setdefault(person, []).append(other)
    if not elsewhere:
        return None

    return {
        "owner": owner,
        "context": context,
        "namesOnOtherContexts": {k: sorted(v) for k, v in sorted(elsewhere.items())},
        "advice": "confirm the context is right; the adapter's read of the live "
                  "source outranks this signal",
    }


def plan(config, promises, now, ttl_hours, wanted_ids=None):
    contacts = config.raw.get("contacts") or {}
    identity_name = ((config.raw.get("identity") or {}).get("name")) or ""
    weights = source_weight(config)

    entries = []
    for promise in promises:
        if wanted_ids and promise.get("id") not in wanted_ids:
            continue
        verify, reason = ttl_decision(promise, now, ttl_hours)
        source_type = (promise.get("source") or {}).get("type") or "unknown"
        weight = weights.get(source_type, "medium")
        entries.append({
            "id": promise.get("id"),
            "what": (promise.get("what") or promise.get("title") or "")[:110],
            "sourceType": source_type,
            "sourceUrl": (promise.get("source") or {}).get("url"),
            "weight": weight,
            "verify": verify,
            "reason": reason,
            "verifyStatus": promise.get("verifyStatus"),
            "lastVerified": promise.get("lastVerified"),
            "overdue": bool(promise.get("_overdue")),
            "flagged": bool(promise.get("_flagged")),
            "misattribution": misattribution_signal(promise, contacts, identity_name),
            "_order": (
                0 if promise.get("_flagged") else 1,      # urgency first...
                WEIGHT_ORDER.get(weight, 1),              # ...then source weight
                str(promise.get("id")),
            ),
        })

    entries.sort(key=lambda e: e["_order"])
    for entry in entries:
        entry.pop("_order")
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--now", default=None, help="ISO 8601 clock override (tests)")
    parser.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    parser.add_argument(
        "--select", default="open",
        help="which promises to consider (a ledger_query selector, default `open`)",
    )
    parser.add_argument("--id", action="append", default=None, help="restrict to these ids")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = lq.Config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    promises, _meta = lq.query(config, now)
    chosen = lq.select(promises, args.select)
    entries = plan(config, chosen, now, args.ttl_hours, set(args.id) if args.id else None)

    to_verify = [e for e in entries if e["verify"]]
    cached = [e for e in entries if not e["verify"]]
    flags = [e for e in entries if e["misattribution"]]

    if args.json:
        json.dump({
            "now": now.isoformat(), "ttlHours": args.ttl_hours, "selector": args.select,
            "verify": to_verify, "cached": cached, "misattributionSignals": flags,
        }, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    print("verify %d, reuse cached verdict for %d (TTL %gh)"
          % (len(to_verify), len(cached), args.ttl_hours))
    for entry in to_verify:
        print("  [%s] %-9s %s" % (
            "!" if entry["flagged"] else " ", entry["sourceType"], entry["what"]))
        print("      %s" % entry["reason"])
    if cached:
        print("skip (fresh):")
        for entry in cached:
            print("  %-9s %s" % (entry["sourceType"], entry["what"][:80]))
    if flags:
        print("\nmis-attribution signals (advisory, confirm before acting):")
        for entry in flags:
            signal = entry["misattribution"]
            print("  %s" % entry["what"][:70])
            print("    owner %r on context %r names %s"
                  % (signal["owner"], signal["context"],
                     ", ".join("%s (on %s)" % (k, "/".join(v))
                               for k, v in signal["namesOnOtherContexts"].items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
