#!/usr/bin/env python3
"""Tests for scripts/reconcile_plan.py.

Run: python3 scripts/tests/test_reconcile_plan.py

Two things carry real cost if they are wrong. The TTL decision: too eager and
every run re-hits every source; too lax and a closed ticket gets chased. And the
mis-attribution signal, which is deliberately weaker than the original spec -
these pin that it only speaks when it has evidence, because the spec's version
measured at roughly 80% false positives on a real ledger.
"""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "reconcile_plan.py"

spec = importlib.util.spec_from_file_location("reconcile_plan", SCRIPT)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

FAILURES = []
NOW = datetime.fromisoformat("2026-08-14T12:00:00")


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


class FakeConfig:
    def __init__(self, raw):
        self.raw = raw


CONTACTS = {
    "Acme Corp": {"people": ["A. Contact", "Dana Reed"]},
    "Beta Co": {"people": ["B. Person", "Sam Okafor"]},
}
CONFIG = FakeConfig({
    "identity": {"name": "Test User"},
    "contacts": CONTACTS,
    "sources": [
        {"type": "issues", "weight": "low"},
        {"type": "chat", "weight": "high"},
    ],
})


def promise(**kw):
    base = {
        "id": "p1", "what": "Do the thing", "context": "Acme Corp",
        "owner": "A. Contact", "source": {"type": "chat", "url": "https://x"},
        "verifyStatus": None, "lastVerified": None,
        "_overdue": False, "_flagged": False,
    }
    base.update(kw)
    return base


def main():
    # --- the TTL decision --------------------------------------------------
    verify, reason = rp.ttl_decision(promise(), NOW, 24)
    check(verify and "never verified" in reason, "a never-verified promise is verified")

    verify, reason = rp.ttl_decision(
        promise(verifyStatus="verified-open", lastVerified="2026-08-14T09:00:00"), NOW, 24)
    check(not verify and "still fresh" in reason, "a 3h-old verdict is reused, not re-hit")

    verify, reason = rp.ttl_decision(
        promise(verifyStatus="verified-open", lastVerified="2026-08-12T09:00:00"), NOW, 24)
    check(verify and "TTL" in reason, "a 51h-old verdict is stale and re-verified")

    verify, _ = rp.ttl_decision(
        promise(verifyStatus="verified-open", lastVerified="2026-08-13T12:00:00"), NOW, 24)
    check(verify, "exactly at the TTL boundary re-verifies (>= is the rule)")

    verify, reason = rp.ttl_decision(
        promise(verifyStatus="resolved", lastVerified="not a date"), NOW, 24)
    check(
        verify and "no readable lastVerified" in reason,
        "a verdict with an unreadable timestamp is re-verified, never trusted",
    )

    # --- ordering: urgency first, then source weight -----------------------
    entries = rp.plan(CONFIG, [
        promise(id="low-weight-flagged", source={"type": "issues", "url": "u"}, _flagged=True),
        promise(id="high-weight-calm", source={"type": "chat", "url": "u"}),
    ], NOW, 24)
    check(
        [e["id"] for e in entries] == ["low-weight-flagged", "high-weight-calm"],
        "a flagged low-weight item outranks a calm high-weight one - urgency "
        "beats source weight, per reference/scheduling.md",
    )

    # --- the mis-attribution signal ----------------------------------------
    none_signal = rp.misattribution_signal(
        promise(context="Acme Corp", owner="A. Contact"), CONTACTS, "Test User")
    check(none_signal is None, "an owner on this context's roster is silent")

    none_signal = rp.misattribution_signal(
        promise(context="Acme Corp", owner="Acme Telecom/Northwind (vendor)"), CONTACTS, "Test User")
    check(
        none_signal is None,
        "an owner naming NOBODY recognisable stays silent - a vendor, a team or "
        "an org is not evidence of mis-attribution (the spec's original rule "
        "fired here, and was wrong ~80% of the time on real data)",
    )

    none_signal = rp.misattribution_signal(
        promise(context="Acme Corp", owner="Test User (asked by someone)"),
        CONTACTS, "Test User")
    check(none_signal is None, "a promise owned by the user themselves is silent")

    none_signal = rp.misattribution_signal(
        promise(context="Acme Corp", owner="Self"), CONTACTS, "Test User")
    check(none_signal is None, "`Self` is silent")

    signal = rp.misattribution_signal(
        promise(context="Acme Corp", owner="Sam Okafor"), CONTACTS, "Test User")
    check(
        signal and signal["namesOnOtherContexts"] == {"Sam Okafor": ["Beta Co"]},
        "an owner who IS on another context's roster but not this one is flagged, "
        "with the evidence attached",
    )
    check(
        signal and "outranks" in signal["advice"],
        "...and is explicitly advisory, not a verdict",
    )

    unknown_context = rp.misattribution_signal(
        promise(context="Not In Contacts", owner="Sam Okafor"), CONTACTS, "Test User")
    check(unknown_context is None, "a context with no roster cannot be judged, so is silent")

    # --- word boundaries, same rule as pronoun matching ---------------------
    check(rp.word_in("Sam", "Sam Okafor"), "a whole-word name matches")
    check(not rp.word_in("Sam", "Samantha Jones"), "a short name does not match inside a longer one")

    print()
    if FAILURES:
        print("%d check(s) failed:" % len(FAILURES))
        for label in FAILURES:
            print("  - %s" % label)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
