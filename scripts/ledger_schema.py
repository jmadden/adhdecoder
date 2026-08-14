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

SCHEMA_VERSION = 3
SWEEP_LOG_CAP = 10

# --- what schemaVersion 3 defines -----------------------------------------
TOP_LEVEL = {
    "schemaVersion", "lastSwept", "promises", "dedup", "knownChannels",
    "watchedThreads", "dismissedFromBoard", "suppressed", "people", "sweepLog",
    "itemMeta", "projects",
}
PROMISE = {
    "id", "title", "context", "direction", "what", "owner", "expectBy", "status",
    "stakes", "stakesOverride", "source", "noteRef", "noteOnly", "created",
    "lastVerified", "verifyStatus", "verifyReason", "why", "deadlineType",
    "snoozedUntil", "driftClearedUntil", "history", "promotedTo", "note",
    "completedDate", "relatedRefs",
}
PROJECT = {
    "id", "name", "status", "aliases", "keywords", "sources", "include", "exclude",
    "targetDate", "checkInEvery", "lastCheckIn", "snoozedUntil", "note", "updated",
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

LEVEL_KEYS = {
    "top": TOP_LEVEL, "promise": PROMISE, "itemMeta": ITEM_META, "project": PROJECT,
}

# --- legal values ---------------------------------------------------------
DIRECTIONS = ("they-owe-me", "i-owe-them")
STATUSES = ("pending", "met", "overdue", "cleared", "promoted")
STAKES = ("high", "normal")
STAKES_OVERRIDE = ("high", "low", None)
VERIFY_STATUSES = (
    "verified-open", "resolved", "reassigned", "mis-attributed", "unverifiable", None,
)
DEADLINE_TYPES = ("hard", "soft", "none")
# a project is `active` or it is `done`. There is deliberately no `paused`:
# `snoozedUntil` already means "quiet, and it comes back" everywhere else in this
# schema, and a paused project is one more thing that silently drops out of view
PROJECT_STATUSES = ("active", "done")

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


def validate_project(record):
    """Shape + enum check for one project record. Returns a list of problems.

    A project groups promises that already exist; it never owns them and never
    carries a deadline of its own that could compete with a promise's `expectBy`
    (see `reference/projects.md`). `targetDate` drives the project-level slipping
    signal and nothing else.
    """
    problems = []
    if not isinstance(record, dict):
        return ["project is not an object"]

    for key in sorted(set(record) - PROJECT):
        problems.append(
            "unknown field `%s` - not in schemaVersion %d; name it in "
            "reference/ledger-schema.md first" % (key, SCHEMA_VERSION)
        )

    for required in ("id", "name"):
        if not str(record.get(required) or "").strip():
            problems.append("`%s` is required" % required)

    if record.get("status") not in PROJECT_STATUSES:
        problems.append(
            "`status` must be one of %s, got %r"
            % (list(PROJECT_STATUSES), record.get("status"))
        )

    for field in ("aliases", "keywords", "sources", "include", "exclude"):
        value = record.get(field)
        if value is not None and not isinstance(value, list):
            problems.append("`%s` must be a list" % field)
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                if not isinstance(entry, str) or not entry.strip():
                    problems.append("`%s[%d]` must be a non-empty string" % (field, index))

    # a project with no way to gain a member can never lag and never clear: it is
    # furniture. `sources` alone counts - it narrows, but it can also stand alone
    # ("everything from this system")
    if not any(record.get(f) for f in ("aliases", "keywords", "sources", "include")):
        problems.append(
            "a project needs at least one `keywords`, `aliases`, `sources` or "
            "`include` entry, or nothing can ever be a member of it"
        )

    # an id both pinned and excluded is a contradiction, and whichever wins is
    # a rule the user did not choose
    both = sorted(set(record.get("include") or []) & set(record.get("exclude") or []))
    if both:
        problems.append(
            "%r is in both `include` and `exclude`; pick one" % both[0]
        )

    every = record.get("checkInEvery")
    if every is not None and (not isinstance(every, int) or isinstance(every, bool) or every < 1):
        problems.append("`checkInEvery` must be a positive whole number of days, got %r" % every)

    for field in ("targetDate", "snoozedUntil", "lastCheckIn"):
        value = record.get(field)
        if value not in (None, "") and not _is_date(value):
            problems.append("`%s` must be YYYY-MM-DD, got %r" % (field, value))
    updated = record.get("updated")
    if updated not in (None, "") and not _is_iso(updated):
        problems.append("`updated` must be ISO 8601, got %r" % updated)

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

    projects = state.get("projects")
    if projects is not None and not isinstance(projects, list):
        problems.append("`projects` must be a list")
        projects = None
    if isinstance(projects, list):
        seen_projects = {}
        for index, record in enumerate(projects):
            if not isinstance(record, dict):
                problems.append("projects[%d] is not an object" % index)
                continue
            key = record.get("id")
            if key in seen_projects:
                problems.append(
                    "duplicate project id %r at projects[%d] and projects[%d]"
                    % (key, seen_projects[key], index)
                )
            else:
                seen_projects[key] = index
            for problem in validate_project(record):
                problems.append("projects[%d] (%s): %s" % (index, key, problem))

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
