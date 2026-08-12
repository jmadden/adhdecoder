#!/usr/bin/env python3
"""Render the ADHDecoder board from the ledger.

Implements `reference/dashboard.md`. Pure function of (config, ledger, now):
same inputs in, byte-identical HTML out. Writes only `config.schedule.boardPath`.

Reconcile is NOT done here. A deterministic offline script cannot reach live
sources, so it renders the verdicts already in the ledger; the `board` and
`daily-run` skills reconcile first, then call this. See `reference/dashboard.md`
step 2.

Usage:
    render-board.py --config <path to instance config.json> [--now ISO8601]
                    [--out PATH] [--template PATH] [--quiet]

Generic by construction: every rendered value comes from the user's own ledger
and config. No personal or company data lives in this file.
"""

import argparse
import html
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment guard
    sys.exit(
        "render-board.py needs a real YAML parser for note frontmatter.\n"
        "Install it, then re-run:\n"
        "    python3 -m pip install --user pyyaml\n"
        "Refusing to fall back to a naive line parser: a blank `due:` would be\n"
        "misread as the next line's value."
    )

OPEN_NOTE_STATUS = ("todo", "in-progress", "blocked")
VERIFY_LABELS = {
    "verified-open": "verified open",
    "resolved": "resolved",
    "reassigned": "reassigned",
    "mis-attributed": "mis-attributed",
    "unverifiable": "unverified - confirm",
    None: "unverified",
}
THEY_OWE_HINTS = (
    "chase", "follow up", "follow-up", "waiting on", "get ", "ask ", "confirm with",
    "hear back", "nudge", "check with",
)
I_OWE_HINTS = (
    "deliver", "provide", "send", "build", "answer", "set up", "configure",
    "spec ", "draft", "write", "reply", "respond", "review", "investigate",
    "diagnose", "escalate", "recommend", "assess", "pull ", "take charge",
)
SHIPPED_WINDOW_DAYS = 7
TOMORROW_WINDOW_DAYS = 7


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def esc(value):
    """HTML-escape any ledger value, including quotes (used in attributes)."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


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


def humanize_since(stamp, now):
    """`lastSwept` as '2h ago' / '3d ago' / the date. 'never' when absent."""
    when = None
    if stamp:
        try:
            when = datetime.fromisoformat(str(stamp))
        except ValueError:
            when = None
    if when is None:
        return "never"
    reference = now
    if when.tzinfo is not None and reference.tzinfo is None:
        when = when.replace(tzinfo=None)
    elif when.tzinfo is None and reference.tzinfo is not None:
        reference = reference.replace(tzinfo=None)
    seconds = (reference - when).total_seconds()
    if seconds < 0:
        return when.date().isoformat()
    if seconds < 3600:
        return "%dm ago" % int(seconds // 60)
    if seconds < 86400:
        return "%dh ago" % int(seconds // 3600)
    if seconds < 86400 * 7:
        return "%dd ago" % int(seconds // 86400)
    return when.date().isoformat()


def plural(count, word):
    return "%d %s" % (count, word if count == 1 else word + "s")


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
# note parsing
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
    """Enumerate tasksDir -> (promises, parse_failures). Never skips silently."""
    promises = []
    failures = []
    if not config.tasks_dir.is_dir():
        return promises, failures

    for note_path in sorted(config.tasks_dir.glob("*.md"), key=lambda p: p.name):
        rel_id = str(note_path.relative_to(config.knowledge_path))
        try:
            text = note_path.read_text(encoding="utf-8")
            frontmatter_text, body = split_frontmatter(text)
            frontmatter = yaml.safe_load(frontmatter_text)
            if frontmatter is None:
                frontmatter = {}
            if not isinstance(frontmatter, dict):
                raise ValueError("frontmatter is not a mapping")
        except (ValueError, OSError, yaml.YAMLError) as error:
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

        note_status = str(frontmatter.get("status") or "todo").strip().lower()
        due = as_date(frontmatter.get("due"))
        scheduled = as_date(frontmatter.get("scheduled"))
        priority = str(frontmatter.get("priority") or "").strip().lower()
        title = first_scalar(frontmatter.get("title")) or note_path.stem
        context = first_scalar(frontmatter.get("customer")) or first_scalar(
            frontmatter.get("projects")
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
                "_origin": "note",
                "_noteStatus": note_status,
            }
        )
    return promises, failures


# --------------------------------------------------------------------------
# ledger assembly
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

    Deliberately ONE-WAY (adapter spec: the board is the union of open notes plus
    state.json promises, deduped by source link). Two records from the SAME store
    never collapse: distinct tasks routinely cite one ticket or doc, and swallowing
    one of them is data loss that looks like an empty result. Returns
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


def load_ledger(config, now):
    """Union of open notes and state.json promises, deduped, itemMeta overlaid."""
    state = {}
    if config.state_file.is_file():
        with open(config.state_file, encoding="utf-8") as handle:
            state = json.load(handle)

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
        state_promises.append(record)

    records, collapsed = union(notes, state_promises)

    item_meta = state.get("itemMeta") or {}
    dismissed_ids = set(state.get("dismissedFromBoard") or [])
    promises = []
    for promise in records:
        meta = item_meta.get(promise["id"]) or {}
        for field in (
            "verifyStatus", "verifyReason", "lastVerified", "snoozedUntil",
            "deadlineType", "why", "noteOnly", "markMetDraft", "updateDraft",
            "appliedMarkMet",
        ):
            if field in meta and meta[field] is not None:
                promise[field] = meta[field]
        if isinstance(meta.get("source"), dict) and meta["source"].get("url"):
            promise["source"] = meta["source"]
        promise["_dismissed"] = (
            promise["id"] in dismissed_ids or bool(meta.get("dismissedFromBoard"))
        )
        promises.append(decorate(promise, now))

    promises.sort(key=sort_key)
    return promises, failures, state, collapsed


def decorate(promise, now):
    """Recompute derived state. Never trusts a persisted `overdue`."""
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
# grouping
# --------------------------------------------------------------------------

def group_promises(promises, now):
    today = now.date()
    horizon = today + timedelta(days=TOMORROW_WINDOW_DAYS)
    shipped_floor = today - timedelta(days=SHIPPED_WINDOW_DAYS)

    board = {"ready": [], "move": [], "waiting": [], "done": []}
    tomorrow, waiting_tab, shipped, history = [], [], [], []

    for promise in promises:
        if promise["_open"]:
            if promise["_suppressed"]:
                continue
            if promise["_readyToClose"]:
                board["ready"].append(promise)
                continue
            upcoming = promise["_expectBy"] is not None and promise["_expectBy"] > today
            if upcoming:
                if promise["_expectBy"] <= horizon:
                    tomorrow.append(promise)
            elif promise["direction"] == "they-owe-me" or promise.get("_noteStatus") == "blocked":
                board["waiting"].append(promise)
            else:
                board["move"].append(promise)
            if promise["direction"] == "they-owe-me":
                waiting_tab.append(promise)
        else:
            history.append(promise)
            if promise["_doneToday"]:
                board["done"].append(promise)
            if promise["_completed"] and promise["_completed"] >= shipped_floor:
                shipped.append(promise)

    history.sort(key=lambda p: (p["_completed"].isoformat() if p["_completed"] else "0000-00-00", str(p["id"])), reverse=True)
    shipped.sort(key=lambda p: (p["_completed"].isoformat() if p["_completed"] else "0000-00-00", str(p["id"])), reverse=True)
    return board, tomorrow, waiting_tab, shipped, history


# --------------------------------------------------------------------------
# card copy (mechanical: derived from fields that exist, never invented)
# --------------------------------------------------------------------------

def step_text(promise, state, now):
    today = now.date()
    if state == "ready":
        return "ready to close - confirm"
    if state == "done":
        when = promise["_completed"]
        return "done today" if not when else "done %s" % when.isoformat()
    if state == "upcoming":
        return "upcoming - due %s" % promise["_expectBy"].isoformat()
    if state == "waiting":
        if promise["_overdue"]:
            return "waiting - %s overdue" % plural((today - promise["_expectBy"]).days, "day")
        if promise["_softPast"]:
            return "waiting - soft date %s, no hard deadline" % promise["_expectBy"].isoformat()
        if promise.get("_noteStatus") == "blocked":
            return "blocked - no clear action"
        return "waiting - no clear action"
    if promise["_overdue"]:
        return "your move - %s overdue" % plural((today - promise["_expectBy"]).days, "day")
    if promise["_dueToday"]:
        return "your move - due today"
    if promise["_softPast"]:
        return "your move - soft date %s, %s untouched" % (
            promise["_expectBy"].isoformat(),
            plural(promise["_staleDays"], "business day"),
        )
    if promise["_expectBy"] is None:
        return "your move - no date, %s untouched" % plural(promise["_staleDays"], "business day")
    return "your move - due %s" % promise["_expectBy"].isoformat()


def action_text(promise, state, config):
    owner = promise.get("owner") or "the counterparty"
    expect_by = promise["_expectBy"]
    if state == "ready":
        draft = promise["_draft"] or {}
        reason = draft.get("reason") or promise.get("verifyReason") or "the source says this is done."
        if promise.get("updateDraft") and not promise.get("markMetDraft"):
            fields = ", ".join(
                "%s: %s" % (k, v)
                for k, v in sorted(promise["updateDraft"].items())
                if k not in ("reason", "bodyLine", "suggestedBodyLine")
            )
            apply_line = (
                "Confirm and apply the update (%s)." % fields
                if config.readwrite
                else "Apply by hand: %s." % fields
            )
        else:
            completed = (promise.get("markMetDraft") or {}).get("completedDate")
            apply_line = (
                "Confirm and close."
                if config.readwrite
                else "Apply by hand: status: done%s." % (", completedDate: %s" % completed if completed else "")
            )
        return "%s %s" % (apply_line, reason)
    if state == "done":
        return "Nothing. Closed%s." % (
            " " + promise["_completed"].isoformat() if promise["_completed"] else ""
        )
    if state == "upcoming":
        verb = "Nudge" if promise["direction"] == "they-owe-me" else "Deliver to"
        return "%s %s by %s." % (verb, owner, expect_by.isoformat())

    reason = promise.get("verifyReason")
    if promise.get("verifyStatus") in ("unverifiable", "mis-attributed", "reassigned"):
        return "Confirm before acting: %s%s" % (
            VERIFY_LABELS.get(promise.get("verifyStatus")),
            ". " + reason if reason else ".",
        )
    if promise["_softPast"]:
        tail = " Soft date %s, no hard deadline." % expect_by.isoformat()
    elif expect_by:
        tail = " %s %s." % (
            "Expected" if promise["direction"] == "they-owe-me" else "Due",
            expect_by.isoformat(),
        )
    else:
        tail = " No date set."
    if promise["direction"] == "they-owe-me":
        return "Nudge %s.%s" % (owner, tail)
    if promise.get("_noteStatus") == "blocked":
        return "Unblock: check with %s.%s" % (owner, tail)
    return "Deliver to %s.%s" % (owner, tail)


# --------------------------------------------------------------------------
# HTML emission
# --------------------------------------------------------------------------

CARD_VARIANT = {"ready": " done", "move": "", "waiting": " waiting", "done": " done", "upcoming": ""}
GROUP_META = [
    ("ready", "Ready to close (confirm)", "var(--good)"),
    ("move", "Your move", "var(--accent)"),
    ("waiting", "Waiting, no clear action", "var(--wait)"),
    ("done", "Done today", "var(--good)"),
]


def links_html(promise):
    parts = []
    source = promise.get("source") or {}
    url = source.get("url")
    if url:
        hint = " (note)" if promise.get("noteOnly") else ""
        parts.append('<a href="%s" target="_blank">source%s</a>' % (esc(url), hint))
    note_ref = promise.get("noteRef") or {}
    if note_ref.get("url"):
        parts.append('<a class="task" href="%s">record</a>' % esc(note_ref["url"]))
    if not parts:
        parts.append('<span class="since">no link on record</span>')
    return '<div class="links">%s</div>' % "".join(parts)


def card_html(promise, state, config, now):
    chips = []
    if promise.get("context"):
        chips.append('<span class="chip c-cust">%s</span>' % esc(promise["context"]))
    if promise.get("_flagged"):
        flag = "overdue" if promise["_overdue"] else "high stakes"
        chips.append('<span class="chip c-flag">%s</span>' % esc(flag))
    chips.append(
        '<span class="chip c-task">%s</span>'
        % esc(VERIFY_LABELS.get(promise.get("verifyStatus"), promise.get("verifyStatus")))
    )
    if promise.get("_dismissed"):
        # on the board despite a dismissal because a draft outranks it; say so,
        # and `board_note` carries the matching count
        chips.append('<span class="chip c-need">dismissed</span>')
    return (
        '<div class="big%s">\n'
        '  <span class="step">%s</span>\n'
        "  <h3>%s</h3>\n"
        '  <div class="chips" style="margin-bottom:6px">%s</div>\n'
        '  <div class="do"><b>First action:</b> %s</div>\n'
        "  %s\n"
        "</div>"
    ) % (
        CARD_VARIANT[state],
        esc(step_text(promise, state, now)),
        esc(promise.get("what") or promise.get("title")),
        "".join(chips),
        esc(action_text(promise, state, config)),
        links_html(promise),
    )


def board_groups_html(board, config, now):
    blocks = []
    for key, label, dot in GROUP_META:
        items = board[key]
        if not items:  # omit an empty section entirely
            continue
        cards = "\n".join(card_html(p, key, config, now) for p in items)
        blocks.append(
            '<div class="today-group">\n'
            '  <div class="group-label"><span class="dot" style="background:%s"></span> %s</div>\n'
            '  <div class="today-grid">\n%s\n  </div>\n'
            "</div>" % (dot, esc(label), cards)
        )
    if not blocks:
        return '<p class="pane-note">Nothing actionable today.</p>'
    return "\n".join(blocks)


def waiting_html(rows, now):
    if not rows:
        return '<p class="pane-note">Nothing outstanding from anyone else.</p>'
    out = []
    for promise in rows:
        expect_by = promise["_expectBy"]
        if expect_by:
            since = "%s - %s waiting" % (
                promise.get("owner") or "unknown",
                plural(max((now.date() - expect_by).days, 0), "day"),
            )
        else:
            since = "%s - no date, %s untouched" % (
                promise.get("owner") or "unknown",
                plural(promise["_staleDays"], "business day"),
            )
        url = (promise.get("source") or {}).get("url")
        link = '<a href="%s">source</a>' % esc(url) if url else "no link"
        out.append(
            '<div class="waitrow"><span class="ww">%s</span>'
            '<span class="since">%s</span><span class="wl">%s</span></div>'
            % (esc(promise.get("what") or promise.get("title")), esc(since), link)
        )
    return "\n".join(out)


def shipped_html(rows):
    if not rows:
        return '<p class="pane-note">Nothing closed in the last %d days.</p>' % SHIPPED_WINDOW_DAYS
    out = []
    for promise in rows:
        url = (promise.get("source") or {}).get("url")
        link = '<a href="%s">source</a>' % esc(url) if url else ""
        out.append(
            '<div class="win"><span class="wd">%s</span><span>%s</span>'
            '<span class="wc">%s</span>%s</div>'
            % (
                esc(promise["_completed"].isoformat() if promise["_completed"] else ""),
                esc(promise.get("what") or promise.get("title")),
                esc(promise.get("context") or ""),
                link,
            )
        )
    return "\n".join(out)


def history_html(rows):
    if not rows:
        return '<p class="pane-note">Nothing closed yet.</p>'
    out = []
    for promise in rows:
        summary = (
            promise.get("verifyReason")
            or (promise.get("appliedMarkMet") or {}).get("reason")
            or (promise["history"][-1]["note"] if promise.get("history") else "")
            or "Closed."
        )
        url = (promise.get("source") or {}).get("url")
        link = '<a href="%s" target="_blank">source</a>' % esc(url) if url else ""
        out.append(
            '<details class="hist"><summary><span class="hdate">%s</span>'
            '<span class="htitle">%s</span><span class="chip c-cust">%s</span></summary>\n'
            '  <div class="hbody"><div class="lbl">What happened</div><p>%s</p>\n'
            '    <div class="links">%s</div></div></details>'
            % (
                esc(promise["_completed"].isoformat() if promise["_completed"] else ""),
                esc(promise.get("what") or promise.get("title")),
                esc(promise.get("context") or ""),
                esc(summary),
                link,
            )
        )
    return "\n".join(out)


def tomorrow_html(rows, config, now):
    if not rows:
        return '<p class="pane-note">Nothing scheduled in the next %d days.</p>' % TOMORROW_WINDOW_DAYS
    return "\n".join(card_html(p, "upcoming", config, now) for p in rows)


def board_note(board, failures, collapsed, config):
    parts = []
    ready, move = len(board["ready"]), len(board["move"])
    if ready:
        parts.append(
            "%s ready to close - confirm %s before the record drifts."
            % (plural(ready, "item"), "it" if ready == 1 else "them")
        )
        revived = sum(1 for p in board["ready"] if p.get("_dismissed"))
        if revived:
            parts.append(
                "%s of those %s dismissed from the board but still %s an unapplied draft."
                % (
                    plural(revived, "item"),
                    "was" if revived == 1 else "were",
                    "carries" if revived == 1 else "carry",
                )
            )
    if move:
        parts.append("%s %s your move." % (plural(move, "item"), "needs" if move == 1 else "need"))
    elif not ready:
        parts.append("Nothing slipping.")
    if failures:
        names = ", ".join(sorted(f["file"] for f in failures))
        parts.append(
            "%s could not be parsed and %s not on this board: %s. Fix the frontmatter by hand."
            % (plural(len(failures), "note"), "is" if len(failures) == 1 else "are", names)
        )
    if collapsed:
        # a scheduled run's stdout recap reaches nobody, so the count belongs on
        # the durable artifact too: it explains why N inputs became fewer cards
        parts.append(
            "%s folded into the note that already owns its source."
            % plural(len(collapsed), "ledger promise")
        )
    if ready and not config.readwrite:
        parts.append("Backend is read-only, so these accumulate until you apply them.")
    return " ".join(parts)


def counts_line(board, waiting_tab, shipped):
    return (
        "<b>%d</b> ready to close, <b>%d</b> need your move, "
        "<b>%d</b> waiting, <b>%d</b> shipped"
        % (len(board["ready"]), len(board["move"]), len(waiting_tab), len(shipped))
    )


def render(config, promises, failures, collapsed, state, now, template_text):
    board, tomorrow, waiting_tab, shipped, history = group_promises(promises, now)
    out = template_text
    tokens = {
        "{{LAST_SWEPT}}": esc(humanize_since(state.get("lastSwept"), now)),
        "{{COUNTS}}": counts_line(board, waiting_tab, shipped),
        "{{N_SHIPPED}}": str(len(shipped)),
        "{{N_WAITING}}": str(len(waiting_tab)),
        "{{N_TOMORROW}}": str(len(tomorrow)),
        "{{N_HISTORY}}": str(len(history)),
        "{{BOARD_NOTE}}": esc(board_note(board, failures, collapsed, config)),
    }
    for token, value in tokens.items():
        out = out.replace(token, value)

    injections = [
        (r"<!-- RENDER today color groups here:.*?-->", board_groups_html(board, config, now)),
        (r"<!-- RENDER \.win rows here -->", shipped_html(shipped)),
        (r"<!-- RENDER \.waitrow rows here -->", waiting_html(waiting_tab, now)),
        (r"<!-- RENDER upcoming \.big cards here -->", tomorrow_html(tomorrow, config, now)),
        (r"<!-- RENDER \.hist details cards here -->", history_html(history)),
    ]
    for pattern, replacement in injections:
        out, hits = re.subn(pattern, lambda _m, r=replacement: r, out, count=1, flags=re.S)
        if not hits:
            raise SystemExit("template is missing an injection point: %s" % pattern)
    return out, (board, tomorrow, waiting_tab, shipped, history)


def write_atomic(target, text):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent), prefix=".render-board-", suffix=".tmp",
        delete=False,
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        # a temp file is 0600; give the board the mode a plain write would produce
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(handle.name, 0o666 & ~umask)
        os.replace(handle.name, target)  # same directory, so never cross-device
    except BaseException:
        handle.close()
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render the ADHDecoder board from the ledger.")
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--now", default=None, help="ISO 8601 clock override (determinism/tests)")
    parser.add_argument("--out", default=None, help="override config.schedule.boardPath")
    parser.add_argument("--template", default=None, help="override the shipped template")
    parser.add_argument("--quiet", action="store_true", help="suppress the stdout recap")
    args = parser.parse_args(argv)

    config = Config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()

    template_path = (
        Path(args.template)
        if args.template
        else Path(__file__).resolve().parent.parent / "assets" / "dashboard-template.html"
    )
    template_text = template_path.read_text(encoding="utf-8")

    promises, failures, state, collapsed = load_ledger(config, now)
    text, groups = render(config, promises, failures, collapsed, state, now, template_text)
    board, tomorrow, waiting_tab, shipped, history = groups

    target = args.out or config.board_path
    if target:
        write_atomic(target, text)

    if not args.quiet:
        summary = (
            "ready-to-close %d | your-move %d | waiting-group %d | done-today %d | "
            "waiting-tab %d | tomorrow %d | shipped %d | history %d | parse-failures %d"
            % (
                len(board["ready"]), len(board["move"]), len(board["waiting"]),
                len(board["done"]), len(waiting_tab), len(tomorrow), len(shipped),
                len(history), len(failures),
            )
        )
        print(summary)
        for failure in sorted(failures, key=lambda f: f["file"]):
            print("  parse failure: %s (%s)" % (failure["file"], failure["symptom"]))
        for item in sorted(collapsed, key=lambda c: c["id"]):
            print("  deduped: state.json %s collapsed into %s" % (item["id"], item["into"]))
        print("board: %s" % (target if target else "(boardPath unset, nothing written)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
