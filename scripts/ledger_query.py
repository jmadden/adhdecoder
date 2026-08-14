#!/usr/bin/env python3
"""The ADHDecoder ledger Query, as one implementation.

This is the `query()` operation of `reference/ledger-backend-interface.md`: it
resolves where the ledger lives, reads it (for a note-backed read-only backend,
the union of open records plus the builtin `state.json`), overlays `itemMeta`,
and recomputes derived state. Every read-side skill calls this rather than
re-deriving "overdue" from prose, because a second derivation is a second
answer, and the two disagree on exactly the cases that matter (an overridden
deadline, a snooze, a dismissal a draft outranks).

Read-only by contract: this module opens files for reading only. It never
writes a note, never writes `state.json`, and has no write path at all.

As a library:
    import ledger_query as lq
    promises, meta = lq.query(lq.Config(path), now)

As a CLI, for skills that need the mechanical read and supply their own
judgment (nudge copy, tiering, tone):
    ledger_query.py --config <config.json> --select slipping --json
    ledger_query.py --config <config.json> --select drifting --context "Acme"

Selectors are defined in SELECTORS below. Generic by construction: field names
and thresholds only, never a user's values.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# stdlib only, by hard rule: the plugin must install with no pip step. The
# frontmatter parser lives beside this file and refuses anything it cannot parse
# rather than guessing (see frontmatter.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter import (  # noqa: E402
    FrontmatterError,
    duplicate_frontmatter_keys,
    parse_frontmatter,
)

THEY_OWE_HINTS = (
    "chase", "follow up", "follow-up", "waiting on", "get ", "ask ", "confirm with",
    "hear back", "nudge", "check with",
)
I_OWE_HINTS = (
    "deliver", "provide", "send", "build", "answer", "set up", "configure",
    "spec ", "draft", "write", "reply", "respond", "review", "investigate",
    "diagnose", "escalate", "recommend", "assess", "pull ", "take charge",
)

# drift thresholds, in BUSINESS days, for an open promise with no expectBy
# (on real note-backed data most open items have no date; date-only chasing
# misses all of them, which is the silent-rot zone)
STALE_DAYS_HIGH = 2       # high-stakes AND actionable: matters, and it's on the user
STALE_DAYS_ANY = 5        # any other open item
STALE_DAYS_BLOCKED = 10   # blocked: waiting on someone else, deserves patience
DUE_SOON_DAYS = 7


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def as_date(value):
    """Coerce a frontmatter/JSON date to a `date`, or None. Never raises."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def first_scalar(value):
    """requester/customer may be a scalar or a YAML list. Take one stable value."""
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items[0] if items else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


WIKILINK_RE = re.compile(r"^\[\[([^\]]+)\]\]$")


def strip_wikilink(value):
    """`[[Acme]]` -> `Acme`, `[[Acme|Acme Corp]]` -> `Acme Corp`. Else unchanged.

    A note's `projects` field holds Obsidian wikilinks, and `context` falls back
    to it when `customer` is empty. Without this the context is the literal
    string `[[Acme]]`, which silently fails every exact match downstream: the
    `--context` filter, the board chip, reconcile's roster lookup. A non-link
    string passes through untouched, so this is safe to apply anywhere a display
    value is derived.
    """
    if value is None:
        return None
    match = WIKILINK_RE.match(str(value).strip())
    if not match:
        return value
    inner = match.group(1)
    # `[[target|display]]` - the display half is what a human reads
    return inner.split("|")[-1].strip() or value


def canonical(value):
    """Fold a context/alias to its match key. MATCHING ONLY, never displayed.

    Case and incidental whitespace are not meaningful differences between two
    spellings of the same customer, and neither is the wikilink wrapper.
    """
    if value is None:
        return ""
    return " ".join(str(strip_wikilink(value)).split()).casefold()


def business_days_between(start, end):
    if start is None or end is None or end <= start:
        return 0
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

class Config:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        with open(self.path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.raw = raw
        storage = raw.get("storage") or {}
        overrides = storage.get("overrides") or {}
        ledger = raw.get("ledger") or {}
        schedule = raw.get("schedule") or {}

        self.knowledge_path = Path(storage.get("knowledgePath", "")).expanduser()
        self.instance_path = Path(storage.get("instancePath", "")).expanduser()
        self.tasks_dir = self.knowledge_path / overrides.get("tasksDir", "Tasks")
        self.state_file = self.instance_path / overrides.get("stateFile", "state.json")
        # a deprecated legacy alias is treated exactly like `obsidian`
        self.backend = "obsidian" if ledger.get("backend") in ("obsidian", "tasknotes") else "builtin"
        self.write_mode = ledger.get("writeMode", "readonly")
        cutover = ledger.get("cutover") or {}
        self.readwrite = (
            self.write_mode == "readwrite" and bool(cutover.get("singleWriterConfirmed"))
        )
        self.board_path = schedule.get("boardPath") or None
        self.vault_name = self.knowledge_path.parent.name if self.knowledge_path.parts else ""


# --------------------------------------------------------------------------
# note parsing (a note-backed read-only backend)
# --------------------------------------------------------------------------

def split_frontmatter(text):
    """Return (frontmatter_text, body). Raises ValueError when malformed.

    Line-based: the closing delimiter is a line that is exactly `---`, so a
    horizontal rule in the body is never mistaken for the end of frontmatter.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("no opening --- on frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    raise ValueError("no closing --- on frontmatter")


CANONICAL_PRIORITIES = ("high", "medium", "low", "")


def live_frontmatter_warnings(frontmatter_text, frontmatter):
    """Everything about THIS note's current content that a lint can catch by
    reading it fresh. Combined and returned as one string, or None.

    Deliberately separate from anything itemMeta might store: a fact this
    function can check is always re-derived, never trusted from a stale cache.
    Adding a new mechanical check here means it self-heals the moment the note
    is fixed, with no reconcile pass and no itemMeta write required.
    """
    findings = []
    duplicates = duplicate_frontmatter_keys(frontmatter_text)
    if duplicates:
        findings.append(
            "duplicate frontmatter key(s): %s - the last value wins and the "
            "earlier one is discarded" % ", ".join(duplicates)
        )
    priority = str(frontmatter.get("priority") or "").strip().lower()
    if priority not in CANONICAL_PRIORITIES:
        findings.append(
            "priority: %s is not a canonical TaskNotes value (expects high/medium/low)"
            % priority
        )
    return "; ".join(findings) if findings else None


def infer_direction(title):
    lowered = (title or "").lower()
    for hint in THEY_OWE_HINTS:
        if lowered.startswith(hint) or (" " + hint) in lowered:
            return "they-owe-me"
    for hint in I_OWE_HINTS:
        if lowered.startswith(hint) or (" " + hint) in lowered:
            return "i-owe-them"
    return "i-owe-them"


def extract_source(body, note_url):
    """Best ACTIONABLE source from the note body, else the note link itself."""
    for match in re.finditer(r"\[[^\]]*\]\((https?://[^\s)]+)\)", body):
        url = match.group(1)
        if not url.startswith("obsidian://"):
            return {"type": "note-extracted", "ref": None, "url": url}, False
    match = re.search(r"(?<![(\w])(https?://[^\s)>\]]+)", body)
    if match:
        return {"type": "note-extracted", "ref": None, "url": match.group(1)}, False
    return {"type": "note", "ref": None, "url": note_url}, True


def note_url_for(vault, knowledge_path, note_path):
    from urllib.parse import quote

    rel = note_path.relative_to(knowledge_path.parent).with_suffix("")
    return "obsidian://open?vault=%s&file=%s" % (quote(vault), quote(str(rel)))


def read_notes(config):
    """Enumerate tasksDir -> (promises, parse_failures). Never skips silently.

    A note whose frontmatter does not parse is invisible to everything
    downstream: no promise, no board, no count. Failures are collected and
    returned so a surface can name them, and are never auto-repaired.
    """
    promises = []
    failures = []
    if not config.tasks_dir.is_dir():
        return promises, failures

    for note_path in sorted(config.tasks_dir.glob("*.md"), key=lambda p: p.name):
        rel_id = str(note_path.relative_to(config.knowledge_path))
        try:
            text = note_path.read_text(encoding="utf-8")
            frontmatter_text, body = split_frontmatter(text)
            frontmatter = parse_frontmatter(frontmatter_text)
            if frontmatter is None:
                frontmatter = {}
            if not isinstance(frontmatter, dict):
                raise ValueError("frontmatter is not a mapping")
        except (FrontmatterError, ValueError, OSError) as error:
            symptom = str(error).splitlines()[0][:160]
            failures.append({"file": note_path.name, "id": rel_id, "symptom": symptom})
            continue

        tags = frontmatter.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        tags = [str(t).strip() for t in tags]
        if "task" not in tags:
            failures.append(
                {"file": note_path.name, "id": rel_id, "symptom": "missing the `task` tag"}
            )
            continue

        live_warning = live_frontmatter_warnings(frontmatter_text, frontmatter)
        note_status = str(frontmatter.get("status") or "todo").strip().lower()
        due = as_date(frontmatter.get("due"))
        scheduled = as_date(frontmatter.get("scheduled"))
        priority = str(frontmatter.get("priority") or "").strip().lower()
        title = first_scalar(frontmatter.get("title")) or note_path.stem
        # `projects` holds wikilinks; strip them here so the context that reaches
        # every surface and every filter is the plain name
        context = strip_wikilink(
            first_scalar(frontmatter.get("customer"))
            or first_scalar(frontmatter.get("projects"))
        )
        owner = first_scalar(frontmatter.get("requester")) or first_scalar(
            frontmatter.get("customer")
        )
        note_url = note_url_for(config.vault_name, config.knowledge_path, note_path)
        source, note_only = extract_source(body, note_url)

        if "ongoing" in tags or (scheduled and not due):
            deadline_type = "soft"
        else:
            deadline_type = "hard"

        history = [
            {"ts": m.group(1), "note": m.group(2).strip()}
            for m in re.finditer(r"^\s*[-*]?\s*update\s+(\S+)\s*[-–]\s*(.*)$", body, re.M | re.I)
        ]

        promises.append(
            {
                "id": rel_id,
                "title": title,
                "context": context,
                "direction": infer_direction(title),
                "what": first_scalar(frontmatter.get("title")) or title,
                "owner": owner,
                "expectBy": due.isoformat() if due else None,
                "status": "met" if note_status == "done" else "pending",
                "completedDate": (
                    as_date(frontmatter.get("completedDate")).isoformat()
                    if as_date(frontmatter.get("completedDate"))
                    else None
                ),
                "stakes": "high" if priority == "high" else "normal",
                "source": source,
                "noteRef": {"url": note_url},
                "noteOnly": note_only,
                "lastVerified": frontmatter.get("dateModified"),
                "verifyStatus": None,
                "verifyReason": None,
                "why": None,
                "deadlineType": deadline_type,
                "snoozedUntil": None,
                "history": history,
                # everything this function can catch by reading the note fresh;
                # never a silent success, and never allowed to go stale (see
                # `_liveWarning` handling in query() - a live check always wins)
                "frontmatterWarning": live_warning,
                "_liveWarning": live_warning,
                # the note's OWN last edit, kept separate from `lastVerified`
                # (which an itemMeta verify overlay can replace). Project
                # movement needs "when did a human touch this", not "when did a
                # sweep last look at it" - see last_movement()
                "_noteModified": frontmatter.get("dateModified"),
                "_origin": "note",
                "_noteStatus": note_status,
            }
        )
    return promises, failures


# --------------------------------------------------------------------------
# people
# --------------------------------------------------------------------------

def pronouns_for(owner, people):
    """Recorded pronouns for this owner, or None.

    Every surface that writes copy naming a person must read `state.json`'s
    `people` map rather than infer from a name. Where pronouns are unrecorded the
    copy stays name-only, never guessed.

    Matching rules, both load-bearing:

    - **Word boundaries.** Owners read like "Full Name (Org)" or free prose, so
      matching is on whole words. A recorded "Sam" must not match inside
      "Samantha Jones" and hand one person's pronouns to another.
    - **Longest key first.** When both "Robin" and "Robin Vega" are recorded, the
      more specific record wins. Sorted order would be deterministic but
      arbitrary, and arbitrary here means misgendering someone.

    Ties between equal-length keys break alphabetically, so the result is a pure
    function of the ledger.
    """
    if not owner or not isinstance(people, dict):
        return None
    lowered = str(owner).lower()
    for name in sorted(people, key=lambda n: (-len(str(n)), str(n))):
        entry = people[name]
        if not isinstance(entry, dict):
            continue
        pronouns = entry.get("pronouns")
        if not pronouns:
            continue
        if re.search(r"(?<!\w)%s(?!\w)" % re.escape(str(name).lower()), lowered):
            return str(pronouns)
    return None


# --------------------------------------------------------------------------
# the union
# --------------------------------------------------------------------------

def dedup_url(promise):
    """The url a record may be deduped on, or None.

    `noteOnly` sources ARE the note link, so they identify one note rather than
    one shared item and can never stand in for a cross-store match.
    """
    if promise.get("noteOnly"):
        return None
    return (promise.get("source") or {}).get("url") or None


def union(notes, state_promises):
    """Collapse a state.json promise into the note that already owns its source.

    Deliberately ONE-WAY (the board is the union of open notes plus state.json
    promises, deduped by source link). Two records from the SAME store never
    collapse: distinct tasks routinely cite one ticket or doc, and swallowing one
    of them is data loss that looks like an empty result. Returns
    (records, collapsed) so a collapse is never invisible.
    """
    note_urls = {}
    for promise in notes:
        url = dedup_url(promise)
        if url:
            note_urls.setdefault(url, promise["id"])

    records = list(notes)
    collapsed = []
    for promise in state_promises:
        url = dedup_url(promise)
        if url and url in note_urls:
            collapsed.append({"id": promise["id"], "into": note_urls[url], "url": url})
            continue
        records.append(promise)
    return records, collapsed


# --------------------------------------------------------------------------
# derived state
# --------------------------------------------------------------------------

def decorate(promise, now):
    """Recompute derived state. Never trusts a persisted `overdue`.

    One definition, so the board and every chase agree about the same ledger.
    """
    today = now.date()
    expect_by = as_date(promise.get("expectBy"))
    deadline_type = promise.get("deadlineType") or "hard"
    is_open = promise.get("status") in ("pending", "overdue")

    promise["_expectBy"] = expect_by
    promise["_open"] = is_open
    promise["_overdue"] = bool(
        is_open and expect_by and expect_by < today and deadline_type == "hard"
    )
    promise["_dueToday"] = bool(is_open and expect_by == today)
    # a soft/none date in the past is NOT overdue; saying "due <past date>" reads
    # as a missed hard deadline, so it gets its own wording
    promise["_softPast"] = bool(
        is_open and expect_by and expect_by < today and deadline_type != "hard"
    )
    promise["_dueSoon"] = bool(
        is_open and expect_by and today < expect_by <= today + timedelta(days=DUE_SOON_DAYS)
    )

    snoozed_until = as_date(promise.get("snoozedUntil"))
    promise["_snoozed"] = bool(snoozed_until and snoozed_until > today)

    last_verified = as_date(promise.get("lastVerified"))
    promise["_staleDays"] = business_days_between(last_verified, today)

    draft = promise.get("markMetDraft") or promise.get("updateDraft")
    promise["_draft"] = draft if isinstance(draft, dict) else None
    promise["_readyToClose"] = bool(
        is_open and (promise.get("verifyStatus") == "resolved" or promise["_draft"])
    )
    # A pending draft outranks a board dismissal: dismissal means "stop showing
    # me this as work", a draft is an unanswered question about the record.
    promise["_suppressed"] = promise["_snoozed"] or (
        promise["_dismissed"] and not promise["_readyToClose"]
    )
    promise["_flagged"] = bool(
        is_open and (promise.get("stakes") == "high" or promise["_overdue"])
    )
    completed = as_date(promise.get("completedDate")) or (
        as_date(promise.get("lastVerified")) if not is_open else None
    )
    promise["_completed"] = completed
    promise["_doneToday"] = bool(not is_open and completed == today)

    # drift: an open promise with no date rots invisibly, so staleness stands in.
    # `blocked` takes priority over stakes, in the SLOW direction: it means
    # "waiting on someone else, nothing to do until they reply," which deserves
    # more patience than an untouched item Jim could act on himself - not less.
    # Conflating the two (both fast-tracked to 2 days) was the actual bug: a
    # note correctly parked as "waiting on the vendor" surfaced as urgent just as
    # fast as a real high-stakes item still sitting in the user's own queue.
    if promise.get("_noteStatus") == "blocked":
        threshold = STALE_DAYS_BLOCKED
    elif promise.get("stakes") == "high":
        threshold = STALE_DAYS_HIGH
    else:
        threshold = STALE_DAYS_ANY
    promise["_stale"] = bool(
        is_open and expect_by is None and promise["_staleDays"] >= threshold
    )
    cleared_until = as_date(promise.get("driftClearedUntil"))
    promise["_driftCleared"] = bool(cleared_until and cleared_until > today)
    return promise


def sort_key(promise):
    """Flagged first, then earliest date, then id. Total and stable."""
    expect_by = promise.get("_expectBy")
    return (
        0 if promise.get("_flagged") else 1,
        expect_by.isoformat() if expect_by else "9999-99-99",
        str(promise.get("id")),
    )


# --------------------------------------------------------------------------
# query
# --------------------------------------------------------------------------

def read_state(config):
    """Parse state.json, or refuse clearly if another session is mid-write."""
    if not config.state_file.is_file():
        return {}
    try:
        with open(config.state_file, encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise SystemExit(
            "the ledger did not parse: %s\n"
            "%s\n"
            "If another session (a scheduled run, another instance) is writing it "
            "right now, re-run in a moment. Nothing was changed." % (error, config.state_file)
        )


# --------------------------------------------------------------------------
# projects (a declared grouping of promises that already exist)
# --------------------------------------------------------------------------

# Business days of silence before a project reads as quiet. Deliberately NOT one
# of the STALE_DAYS_* constants: those are calibrated for a single promise (2/5/10)
# and a multi-week effort tripping after two quiet days is a nag, not a signal.
# Ten business days is two working weeks, which on real data is slower than any
# healthy rhythm observed and faster than anything anyone would call "lagging".
PROJECT_QUIET_DAYS = 10


def project_members(project, promises):
    """Ids of every promise belonging to this project, in Query order.

    Two ways in, checked in this order:
      1. `include` - an explicitly pinned id, regardless of its context. This is
         the ONLY way to split one customer into two workstreams, because both
         workstreams carry the same `customer` and therefore the same context.
      2. an alias matching the promise's canonical context.
    """
    pinned = set(project.get("include") or [])
    aliases = {canonical(a) for a in (project.get("aliases") or []) if canonical(a)}
    members = []
    for promise in promises:
        pid = promise.get("id")
        if pid in pinned or canonical(promise.get("context")) in aliases:
            members.append(pid)
    return members


def last_movement(members):
    """The most recent date anything in this project actually moved.

    **`lastVerified` is deliberately NOT movement.** It records when the system
    last LOOKED at an item, and a sweep refreshes it on everything it touches.
    Counting it would mean a swept ledger can never go quiet: the automated pass
    that is supposed to notice a stalled project would be the very thing keeping
    it looking alive. That is the same self-defeating signal that let a note keep
    a five-week-dead date while every sweep re-blessed it.

    What counts is work: a close, a note the user edited, a logged update, or a
    new item arriving (`created`) - each of which requires a human to have done
    something.
    """
    stamps = []
    for promise in members:
        for value in (
            promise.get("completedDate"),
            promise.get("created"),
            promise.get("_noteModified"),
        ):
            stamp = as_date(value)
            if stamp:
                stamps.append(stamp)
        for entry in promise.get("history") or []:
            if isinstance(entry, dict):
                stamp = as_date(entry.get("ts"))
                if stamp:
                    stamps.append(stamp)
    return max(stamps) if stamps else None


def projects(promises, state, now):
    """Declared projects, each with a computed rollup. Read-only, never stored.

    The rollup is derived on every read for the same reason every other derived
    value is: a stored count is a second answer that goes stale silently. Nothing
    here is written back.
    """
    today = now.date()
    by_id = {p.get("id"): p for p in promises}
    out = []
    for declared in state.get("projects") or []:
        if not isinstance(declared, dict):
            continue
        member_ids = project_members(declared, promises)
        members = [by_id[mid] for mid in member_ids if mid in by_id]
        pinned = set(declared.get("include") or [])

        moved = last_movement(members)
        movement_days = business_days_between(moved, today)
        starts = [as_date(p.get("created")) for p in members]
        starts = [s for s in starts if s]
        next_dates = sorted(
            p["_expectBy"] for p in members if p["_open"] and p.get("_expectBy")
        )
        open_members = [p for p in members if p["_open"] and not p["_dismissed"]]
        snoozed_until = as_date(declared.get("snoozedUntil"))
        snoozed = bool(snoozed_until and snoozed_until > today)
        target = as_date(declared.get("targetDate"))
        active = declared.get("status", "active") == "active"

        # Quiet does NOT require open work. A project whose members are all closed
        # but which was never marked done has nothing left to surface it - that is
        # precisely the effort that falls out of view, so it must still be able to
        # go quiet. A project that just closed its last item moved today, so it
        # stays silent on its own without a grace-period special case.
        quiet = bool(
            active and not snoozed and members and movement_days >= PROJECT_QUIET_DAYS
        )
        slipping = bool(
            active
            and not snoozed
            and target
            and target <= today + timedelta(days=DUE_SOON_DAYS)
        )

        lag, reason = None, None
        if quiet:
            lag = "quiet"
            reason = "nothing has moved in %s" % plural_days(movement_days)
        elif slipping:
            lag = "date-slipping"
            reason = (
                "target date %s has passed" % target.isoformat()
                if target < today
                else "target date %s is %s away"
                % (target.isoformat(), plural_days((target - today).days, calendar=True))
            )

        record = dict(declared)
        record["rollup"] = {
            "memberIds": member_ids,
            "memberCount": len(members),
            "openCount": len(open_members),
            "closedCount": len([p for p in members if not p["_open"]]),
            "pinnedCount": len([m for m in member_ids if m in pinned]),
            "lastMovement": moved.isoformat() if moved else None,
            "movementDays": movement_days,
            "firstSeen": min(starts).isoformat() if starts else None,
            "spanDays": (today - min(starts)).days if starts else 0,
            "nextDate": next_dates[0].isoformat() if next_dates else None,
            "lag": lag,
            "lagReason": reason,
            "snoozed": snoozed,
        }
        out.append(record)

    # deterministic: lagging first, then longest-quiet, then id. The board asserts
    # byte-identical output across runs.
    out.sort(key=lambda r: (
        r["rollup"]["lag"] is None,
        -r["rollup"]["movementDays"],
        str(r.get("id")),
    ))
    return out


def plural_days(count, calendar=False):
    unit = "day" if calendar else "business day"
    return "%d %s%s" % (count, unit, "" if count == 1 else "s")


def query(config, now):
    """The Query. Returns (promises, meta).

    `promises` are schema-shaped records with derived state attached under
    underscore-prefixed keys. `meta` carries what a surface must be able to
    report: parse failures, cross-store collapses, frontmatter warnings, and the
    raw state for `lastSwept` / `suppressed` / `sweepLog`.
    """
    state = read_state(config)

    notes, failures = ([], [])
    if config.backend == "obsidian":
        notes, failures = read_notes(config)

    state_promises = []
    for promise in state.get("promises") or []:
        if promise.get("status") == "promoted":
            continue
        record = dict(promise)
        record["_origin"] = "state"
        record.setdefault("_noteStatus", None)
        record.setdefault("_liveWarning", None)
        record.setdefault("_noteModified", None)
        state_promises.append(record)

    records, collapsed = union(notes, state_promises)

    item_meta = state.get("itemMeta") or {}
    dismissed_ids = set(state.get("dismissedFromBoard") or [])
    people = state.get("people") or {}
    promises = []
    for promise in records:
        meta = item_meta.get(promise["id"]) or {}
        for field in (
            "verifyStatus", "verifyReason", "lastVerified", "snoozedUntil",
            "deadlineType", "deadlineTypeReason", "why", "noteOnly",
            "markMetDraft", "updateDraft", "appliedMarkMet",
        ):
            if field in meta and meta[field] is not None:
                promise[field] = meta[field]
        if isinstance(meta.get("source"), dict) and meta["source"].get("url"):
            promise["source"] = meta["source"]

        # frontmatterWarning is ALWAYS the live check on this read of this file,
        # and a stored `itemMeta.frontmatterWarning` is ignored (the field is
        # deprecated in `ledger_schema.py`). A stored lint is a claim about the
        # note's content with no way to re-check it, so it outlives the note it
        # described - the write-once-stale bug `parseError` was deprecated for,
        # reintroduced through this field. Gating it on a timestamp did not save
        # it: the gate borrowed `lastVerified`, which unrelated verify writes
        # bump, so a verify 16 seconds after a note was FIXED carried a
        # days-old warning forward as current. And nothing ever wrote the field
        # from code, so the stored half was a rule with no writer.
        promise["frontmatterWarning"] = promise.pop("_liveWarning", None)
        promise["_dismissed"] = (
            promise["id"] in dismissed_ids or bool(meta.get("dismissedFromBoard"))
        )
        promise["_pronouns"] = pronouns_for(promise.get("owner"), people)
        promises.append(decorate(promise, now))

    promises.sort(key=sort_key)
    warnings = [
        {
            "file": Path(str(p["id"])).name,
            "id": p["id"],
            "warning": p["frontmatterWarning"],
        }
        for p in promises
        if p.get("frontmatterWarning")
    ]
    # projects are computed here, once, and stamped back onto their members, so a
    # consumer can group without re-deriving membership (the second-answer trap)
    rollups = projects(promises, state, now)
    owner_of = {}
    # by id, not by the display sort: which project a shared member is stamped
    # with must not depend on which one happens to be lagging today
    for record in sorted(rollups, key=lambda r: str(r.get("id"))):
        for member_id in record["rollup"]["memberIds"]:
            owner_of.setdefault(member_id, record.get("id"))
    for promise in promises:
        promise["_projectId"] = owner_of.get(promise.get("id"))

    meta = {
        "failures": failures,
        "collapsed": collapsed,
        "warnings": sorted(warnings, key=lambda w: w["file"]),
        "projects": rollups,
        "state": state,
    }
    return promises, meta


# --------------------------------------------------------------------------
# selectors (what the read-side skills ask for)
# --------------------------------------------------------------------------

def select(promises, selector):
    """Mechanical selection only. Tiering, copy and tone stay with the skill."""
    active = [p for p in promises if not p["_suppressed"]]
    if selector == "all":
        return list(promises)
    if selector == "open":
        return [p for p in active if p["_open"]]
    if selector == "closed":
        return [p for p in promises if not p["_open"]]
    if selector == "ready-to-close":
        return [p for p in active if p["_readyToClose"]]
    if selector == "slipping":
        # what chase-in chases: a real date has passed, or lands today. Soft and
        # dateless items are NOT here; they reach the user through drift.
        return [
            p for p in active
            if p["_open"] and not p["_readyToClose"] and (p["_overdue"] or p["_dueToday"])
        ]
    if selector == "drifting":
        # what drift flags: business-day staleness on dateless items, plus
        # high-stakes items already overdue or due soon. Honours a drift clear.
        return [
            p for p in active
            if p["_open"] and not p["_readyToClose"] and not p["_driftCleared"]
            and (p["_stale"] or (p["stakes"] == "high" and (p["_overdue"] or p["_dueSoon"])))
        ]
    if selector == "waiting":
        return [p for p in active if p["_open"] and p["direction"] == "they-owe-me"]
    if selector == "owed":
        return [p for p in active if p["_open"] and p["direction"] == "i-owe-them"]
    if selector == "upcoming":
        return [p for p in active if p["_open"] and p["_dueSoon"]]
    if selector == "snoozed":
        return [p for p in promises if p["_snoozed"]]
    raise SystemExit("unknown selector %r; expected one of: %s" % (selector, ", ".join(SELECTORS)))


SELECTORS = (
    "all", "open", "closed", "ready-to-close", "slipping", "drifting",
    "waiting", "owed", "upcoming", "snoozed",
)

DERIVED_FIELDS = (
    "open", "overdue", "dueToday", "dueSoon", "softPast", "snoozed", "staleDays",
    "stale", "driftCleared", "readyToClose", "dismissed", "suppressed", "flagged",
    "doneToday", "pronouns", "origin", "noteStatus", "projectId",
)


def jsonable(value):
    """Coerce dates for the JSON contract.

    A real YAML parser turns `dateModified` into a datetime, so note-backed
    records carry date objects in fields the schema describes as strings. Walk
    and stringify rather than special-casing one field, since any frontmatter key
    can arrive this way.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(promise):
    """Schema fields as-is, derived state under `derived`, private keys dropped."""
    out = {k: jsonable(v) for k, v in promise.items() if not k.startswith("_")}
    derived = {}
    for name in DERIVED_FIELDS:
        key = "_" + name
        if key in promise:
            value = promise[key]
            derived[name] = value.isoformat() if isinstance(value, date) else value
    derived["expectBy"] = (
        promise["_expectBy"].isoformat() if promise.get("_expectBy") else None
    )
    derived["completed"] = (
        promise["_completed"].isoformat() if promise.get("_completed") else None
    )
    out["derived"] = derived
    return out


# tokens that identify an org's TYPE, not the org. Dropping them is what lets
# "Acme CU" and "Acme Credit Union" recognise each other as one candidate.
ORG_SUFFIX_TOKENS = {
    "cu", "fcu", "credit", "union", "federal", "financial", "bank", "banking",
    "inc", "llc", "ltd", "co", "corp", "company", "group", "the", "of",
}


def name_tokens(value):
    return [w for w in re.split(r"[^a-z0-9]+", canonical(value)) if w]


def merge_key(value):
    """The token two spellings of one org share: the first non-org-type word.

    "Acme CU" and "Acme Credit Union" both key on "acme". A lone acronym keys on
    itself and is matched separately (see `acronym_of`), because initials are
    ambiguous enough to merge two DIFFERENT orgs: two unrelated customers whose
    names differ from the second word on still share their initials, and merging
    those would put one customer's work under another customer's name. Nothing
    here may do that.
    """
    words = name_tokens(value)
    if not words:
        return ""
    meaningful = [w for w in words if w not in ORG_SUFFIX_TOKENS]
    return meaningful[0] if meaningful else words[0]


def acronym_of(value):
    """Initials of a multi-word name, or "" - used only to place a lone acronym.

    Requires 3+ letters: two-letter initials collide constantly across different
    organisations, and a wrong merge here renames a customer.
    """
    words = name_tokens(value)
    if len(words) < 3:
        return ""
    acronym = "".join(w[0] for w in words)
    return acronym if len(acronym) >= 3 else ""


def merge_candidates(clusters):
    """Fold candidates that look like one org into one suggestion. Advisory only.

    Two passes, both conservative, because a false merge files one customer's
    work under another customer's name:

      1. group on the first non-org-type token ("Acme CU" + "Acme Credit Union")
      2. attach a cluster whose ONLY spelling is a bare acronym to the group
         whose spelled-out name has exactly those initials ("ACU" -> "Acme
         Credit Union"). A cluster that is already spelled out never merges by
         initials.

    Everything merged is printed, so a wrong grouping is visible before anything
    is declared, and costs one edit to split.
    """
    groups = {}
    order = []
    for cluster in clusters:
        key = merge_key(cluster["spellings"][0] if cluster["spellings"] else cluster["name"])
        target = groups.get(key)
        if target is None:
            groups[key] = cluster
            order.append(cluster)
        else:
            absorb(target, cluster)

    # pass 2: a bare acronym joins the spelled-out name with those initials
    by_acronym = {}
    for cluster in order:
        for spelling in cluster["spellings"]:
            acronym = acronym_of(spelling)
            if acronym:
                by_acronym.setdefault(acronym, cluster)

    survivors = []
    for cluster in order:
        lone = [s for s in cluster["spellings"] if len(name_tokens(s)) == 1]
        if len(cluster["spellings"]) == 1 and lone:
            host = by_acronym.get(canonical(lone[0]).replace(" ", ""))
            if host is not None and host is not cluster:
                absorb(host, cluster)
                continue
        survivors.append(cluster)

    survivors.sort(key=lambda c: (-c["memberCount"], c["suggestedId"]))
    return survivors


def absorb(target, other):
    """Fold `other`'s counts and spellings into `target`."""
    target["memberCount"] += other["memberCount"]
    target["openCount"] += other["openCount"]
    target["spellings"] = sorted(set(target["spellings"]) | set(other["spellings"]))
    for stem, ids in other["slugClusters"].items():
        target["slugClusters"].setdefault(stem, []).extend(ids)
    for field, keep in (("firstSeen", min), ("lastMovement", max)):
        values = [v for v in (target.get(field), other.get(field)) if v]
        target[field] = keep(values) if values else None


def candidate_clusters(promises, declared):
    """Context clusters nobody has declared yet, as project suggestions.

    Read-only and advisory. It exists because the alternative to a bootstrap is
    hand-writing JSON, and a feature that costs a hand-written record does not
    get used. It suggests; the write path decides.
    """
    claimed = set()
    for project in declared:
        for alias in project.get("aliases") or []:
            if canonical(alias):
                claimed.add(canonical(alias))

    clusters = {}
    homeless = []
    for promise in promises:
        key = canonical(promise.get("context"))
        if not key:
            homeless.append(promise)
            continue
        if key in claimed:
            continue
        clusters.setdefault(key, []).append(promise)

    out = []
    for key, members in clusters.items():
        spellings = sorted({str(p.get("context")) for p in members if p.get("context")})
        # the id-slug half of `<sourceRef>:<slug>` is where the user's OWN
        # decomposition already lives, and it is the only signal that separates
        # two workstreams sharing one customer. Surfaced as a hint, never applied.
        slugs = {}
        for promise in members:
            pid = str(promise.get("id") or "")
            if ":" in pid:
                stem = pid.split(":", 1)[1].rsplit("-", 1)[0]
                if stem:
                    slugs.setdefault(stem, []).append(pid)
        moved = last_movement(members)
        starts = [as_date(p.get("created")) for p in members]
        starts = [s for s in starts if s]
        out.append({
            "suggestedId": re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "project",
            "name": spellings[0] if spellings else key,
            "spellings": spellings,
            "memberCount": len(members),
            "openCount": len([p for p in members if p["_open"]]),
            "firstSeen": min(starts).isoformat() if starts else None,
            "lastMovement": moved.isoformat() if moved else None,
            "slugClusters": {k: v for k, v in sorted(slugs.items()) if len(v) > 1},
        })
    out.sort(key=lambda c: (-c["memberCount"], c["suggestedId"]))
    return merge_candidates(out), homeless


def print_projects(promises, meta, now, args):
    """Render declared projects (and optionally candidates). Prints only."""
    declared = meta["projects"]
    candidates, homeless = ([], [])
    if args.candidates:
        candidates, homeless = candidate_clusters(promises, meta["state"].get("projects") or [])

    if args.json:
        json.dump(
            {
                "now": now.isoformat(),
                "projects": jsonable(declared),
                "candidates": jsonable(candidates),
                "unclusterable": len(homeless),
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        print()
        return 0

    lagging = [p for p in declared if p["rollup"]["lag"]]
    print("%d project(s) declared, %d lagging" % (len(declared), len(lagging)))
    for project in declared:
        roll = project["rollup"]
        state_note = []
        if project.get("status") == "done":
            state_note.append("done")
        if roll["snoozed"]:
            state_note.append("snoozed until %s" % project.get("snoozedUntil"))
        if roll["lag"]:
            state_note.append("%s - %s" % (roll["lag"], roll["lagReason"]))
        print(
            "  %s (%s)\n      %d items, %d open | last movement %s | next %s%s"
            % (
                project.get("name"),
                project.get("id"),
                roll["memberCount"],
                roll["openCount"],
                roll["lastMovement"] or "never",
                roll["nextDate"] or "nothing dated",
                ("\n      " + "; ".join(state_note)) if state_note else "",
            )
        )

    if args.candidates:
        print("\n%d undeclared cluster(s):" % len(candidates))
        for cluster in candidates:
            print(
                "  %s - %d items, %d open | %s -> %s"
                % (
                    cluster["name"], cluster["memberCount"], cluster["openCount"],
                    cluster["firstSeen"] or "?", cluster["lastMovement"] or "?",
                )
            )
            if len(cluster["spellings"]) > 1:
                print(
                    "      %d spellings look like one org: %s"
                    % (len(cluster["spellings"]), ", ".join(cluster["spellings"]))
                )
            for stem, ids in cluster["slugClusters"].items():
                print("      %d items share the slug %s-* (a possible split)"
                      % (len(ids), stem))
            print(
                "      declare: ledger_write.py --config CFG project-set --id %s \\\n"
                "                 --name %r%s"
                % (
                    cluster["suggestedId"], cluster["name"],
                    "".join(" \\\n                 --alias %r" % s for s in cluster["spellings"]),
                )
            )
        if homeless:
            print(
                "\n  %d item(s) have no context and cannot be clustered - pin them "
                "with --include if they belong to a project." % len(homeless)
            )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Query the ADHDecoder ledger (read-only).")
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--now", default=None, help="ISO 8601 clock override (determinism/tests)")
    parser.add_argument(
        "--select", default="open", help="one of: %s" % ", ".join(SELECTORS)
    )
    parser.add_argument("--context", default=None, help="only this context (exact, case-insensitive)")
    parser.add_argument(
        "--direction", default=None, choices=("they-owe-me", "i-owe-them"),
        help="only this direction",
    )
    parser.add_argument("--project", default=None, help="only members of this project id")
    parser.add_argument(
        "--projects", action="store_true",
        help="print declared projects and their rollup instead of promises",
    )
    parser.add_argument(
        "--candidates", action="store_true",
        help="with --projects: suggest projects from clusters not yet declared",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable records")
    args = parser.parse_args(argv)

    config = Config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    promises, meta = query(config, now)

    if args.projects or args.candidates:
        return print_projects(promises, meta, now, args)

    chosen = select(promises, args.select)
    if args.project:
        wanted = str(args.project).strip()
        chosen = [p for p in chosen if p.get("_projectId") == wanted]
    if args.context:
        wanted = canonical(args.context)
        chosen = [p for p in chosen if canonical(p.get("context")) == wanted]
    if args.direction:
        chosen = [p for p in chosen if p.get("direction") == args.direction]

    if args.json:
        json.dump(
            {
                "selector": args.select,
                "now": now.isoformat(),
                "count": len(chosen),
                "promises": [public(p) for p in chosen],
                "parseFailures": meta["failures"],
                "frontmatterWarnings": meta["warnings"],
                "collapsed": meta["collapsed"],
                "lastSwept": meta["state"].get("lastSwept"),
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        print()
        return 0

    print("%s: %d of %d records" % (args.select, len(chosen), len(promises)))
    for promise in chosen:
        flags = []
        if promise["_overdue"]:
            flags.append("overdue")
        if promise["_softPast"]:
            flags.append("soft date passed")
        if promise["_stale"]:
            flags.append("%d business days untouched" % promise["_staleDays"])
        if promise["_readyToClose"]:
            flags.append("ready to close")
        owner = promise.get("owner") or "unknown"
        if promise.get("_pronouns"):
            name, sep, rest = owner.partition(" (")
            owner = "%s (%s)%s%s" % (name, promise["_pronouns"], sep, rest)
        print(
            "  [%s] %s\n      owner=%s expectBy=%s%s"
            % (
                promise.get("verifyStatus") or "unverified",
                (promise.get("what") or promise.get("title") or "")[:96],
                owner,
                promise.get("expectBy") or "none",
                (" | " + ", ".join(flags)) if flags else "",
            )
        )
    for failure in meta["failures"]:
        print("  parse failure: %s (%s)" % (failure["file"], failure["symptom"]))
    for warning in meta["warnings"]:
        print("  frontmatter warning: %s (%s)" % (warning["file"], warning["warning"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
