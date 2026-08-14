#!/usr/bin/env python3
"""The ledger schema, as data. Stdlib only, importable by every other script.

`reference/ledger-schema.md` is the prose; this is the machine-readable form of
the same thing. Both the read-side validator (`validate-state.py`) and the
write path (`ledger_write.py`) import from here, so a field can never be legal
to write but unknown to the validator - the class of drift that produced two
spellings of "this note is malformed" and three duplicates of fields that
already existed.

Nothing here reads or writes a file. It answers questions about a record:
what fields exist, which values are legal, and whether a proposed promise is
safe to write.
"""

import re

SCHEMA_VERSION = 2
SWEEP_LOG_CAP = 10

# --- what schemaVersion 2 defines -----------------------------------------
TOP_LEVEL = {
    "schemaVersion", "lastSwept", "promises", "dedup", "knownChannels",
    "watchedThreads", "dismissedFromBoard", "suppressed", "people", "sweepLog",
    "itemMeta",
}
PROMISE = {
    "id", "title", "context", "direction", "what", "owner", "expectBy", "status",
    "stakes", "stakesOverride", "source", "noteRef", "noteOnly", "created",
    "lastVerified", "verifyStatus", "verifyReason", "why", "deadlineType",
    "snoozedUntil", "driftClearedUntil", "history", "promotedTo", "note",
    "completedDate", "relatedRefs",
}
ITEM_META = {
    "snoozedUntil", "deadlineType", "deadlineTypeReason", "verifyStatus",
    "verifyReason", "lastVerified", "source", "noteOnly", "dismissedFromBoard",
    "markMetDraft", "updateDraft", "appliedMarkMet",
}

# --- deprecated: recognised, reported as a note, never written again ------
DEPRECATED = {
    "promise": {
        "createdAt": "created",
        "counterparty": "owner (+ note for the nuance)",
    },
    "itemMeta": {
        "resolvedNotDropped": "markMetDraft",
        "closedBy": "appliedMarkMet.by",
        "recommendation": "updateDraft",
        "parseError": "nothing; parse failures are detected live, never stored",
        "frontmatterWarning": "nothing; lints are detected live, never stored",
    },
}

LEVEL_KEYS = {"top": TOP_LEVEL, "promise": PROMISE, "itemMeta": ITEM_META}

# --- legal values ---------------------------------------------------------
DIRECTIONS = ("they-owe-me", "i-owe-them")
STATUSES = ("pending", "met", "overdue", "cleared", "promoted")
STAKES = ("high", "normal")
STAKES_OVERRIDE = ("high", "low", None)
VERIFY_STATUSES = (
    "verified-open", "resolved", "reassigned", "mis-attributed", "unverifiable", None,
)
DEADLINE_TYPES = ("hard", "soft", "none")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ISO 8601 with an optional time part; deliberately permissive about offsets,
# strict about the leading date, since that is what as_date() reads
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")


def _is_date(value):
    return isinstance(value, str) and bool(DATE_RE.match(value))


def _is_iso(value):
    return isinstance(value, str) and bool(ISO_RE.match(value))


def reality_gate(record):
    """The rule that keeps ADHDecoder from resurrecting vague 'go find out X'.

    A promise may be written ONLY with all three of: a named `owner`, a concrete
    `what`, and an `expectBy`. Returns a list of problems; empty means it passes.

    This is deliberately separate from schema validation: a record can be
    perfectly well-formed and still be a phantom chase.
    """
    problems = []
    if not str(record.get("owner") or "").strip():
        problems.append("reality gate: `owner` is missing - a promise needs a named party")
    what = str(record.get("what") or "").strip()
    if not what:
        problems.append("reality gate: `what` is missing - needs one concrete deliverable")
    elif len(what) < 8:
        problems.append(
            "reality gate: `what` is too vague (%r) - needs a concrete deliverable, "
            "not a topic" % what
        )
    if not record.get("expectBy"):
        problems.append(
            "reality gate: `expectBy` is missing - without a date nothing can be chased"
        )
    return problems


def validate_promise(record, enforce_reality_gate=True):
    """Shape + enum check for one promise record. Returns a list of problems."""
    problems = []
    if not isinstance(record, dict):
        return ["promise is not an object"]

    unknown = sorted(set(record) - PROMISE)
    for key in unknown:
        replacement = DEPRECATED["promise"].get(key)
        if replacement:
            problems.append("deprecated field `%s` - use %s" % (key, replacement))
        else:
            problems.append(
                "unknown field `%s` - not in schemaVersion %d; name it in "
                "reference/ledger-schema.md first" % (key, SCHEMA_VERSION)
            )

    for required in ("id", "direction", "status"):
        if not record.get(required):
            problems.append("`%s` is required" % required)

    if record.get("direction") not in DIRECTIONS:
        problems.append(
            "`direction` must be one of %s, got %r" % (list(DIRECTIONS), record.get("direction"))
        )
    if record.get("status") not in STATUSES:
        problems.append(
            "`status` must be one of %s, got %r" % (list(STATUSES), record.get("status"))
        )
    if record.get("stakes") is not None and record.get("stakes") not in STAKES:
        problems.append(
            "`stakes` must be one of %s, got %r" % (list(STAKES), record.get("stakes"))
        )
    if record.get("stakesOverride") not in STAKES_OVERRIDE:
        problems.append(
            "`stakesOverride` must be one of %s, got %r"
            % (list(STAKES_OVERRIDE), record.get("stakesOverride"))
        )
    if record.get("verifyStatus") not in VERIFY_STATUSES:
        problems.append(
            "`verifyStatus` must be one of %s, got %r"
            % (list(VERIFY_STATUSES), record.get("verifyStatus"))
        )
    if record.get("deadlineType") is not None and record.get("deadlineType") not in DEADLINE_TYPES:
        problems.append(
            "`deadlineType` must be one of %s, got %r"
            % (list(DEADLINE_TYPES), record.get("deadlineType"))
        )

    for field in ("expectBy", "snoozedUntil", "completedDate"):
        value = record.get(field)
        if value not in (None, "") and not _is_date(value):
            problems.append("`%s` must be YYYY-MM-DD, got %r" % (field, value))
    for field in ("created", "lastVerified", "driftClearedUntil"):
        value = record.get(field)
        if value not in (None, "") and not _is_iso(value):
            problems.append("`%s` must be ISO 8601, got %r" % (field, value))

    source = record.get("source")
    if source is not None:
        if not isinstance(source, dict):
            problems.append("`source` must be an object of { type, ref, url }")
        elif not source.get("url"):
            problems.append("`source.url` is required when `source` is present")

    history = record.get("history")
    if history is not None:
        if not isinstance(history, list):
            problems.append("`history` must be a list")
        else:
            for index, entry in enumerate(history):
                if not isinstance(entry, dict) or not entry.get("ts") or "note" not in entry:
                    problems.append("`history[%d]` must be { ts, note }" % index)

    if record.get("status") == "promoted" and not record.get("promotedTo"):
        problems.append("`status: promoted` requires `promotedTo` naming the new record")

    if enforce_reality_gate and record.get("status") in ("pending", "overdue"):
        problems.extend(reality_gate(record))

    return problems


def validate_state(state):
    """Structural check on a whole state.json. Returns a list of problems.

    Used as the POST-write gate: if a write would leave the file in a state this
    rejects, the write is rolled back rather than persisted.
    """
    problems = []
    if not isinstance(state, dict):
        return ["top level is not an object"]

    unknown = sorted(set(state) - TOP_LEVEL)
    for key in unknown:
        problems.append("unknown top-level field `%s`" % key)

    promises = state.get("promises")
    if not isinstance(promises, list):
        problems.append("`promises` must be a list")
        promises = []

    seen_ids = {}
    for index, record in enumerate(promises):
        if not isinstance(record, dict):
            problems.append("promises[%d] is not an object" % index)
            continue
        pid = record.get("id")
        if pid in seen_ids:
            problems.append(
                "duplicate promise id %r at promises[%d] and promises[%d]"
                % (pid, seen_ids[pid], index)
            )
        else:
            seen_ids[pid] = index
        for problem in validate_promise(record, enforce_reality_gate=False):
            problems.append("promises[%d] (%s): %s" % (index, pid, problem))

    item_meta = state.get("itemMeta")
    if item_meta is not None and not isinstance(item_meta, dict):
        problems.append("`itemMeta` must be an object keyed by promise id")

    for field, kind in (
        ("dismissedFromBoard", list), ("knownChannels", list), ("watchedThreads", list),
        ("suppressed", list), ("sweepLog", list), ("people", dict), ("dedup", dict),
    ):
        value = state.get(field)
        if value is not None and not isinstance(value, kind):
            problems.append("`%s` must be a %s" % (field, kind.__name__))

    return problems
