#!/usr/bin/env python3
"""Render the ADHDecoder board from the ledger.

Implements `reference/dashboard.md`. Pure function of (config, ledger, now):
same inputs in, byte-identical HTML out. Writes only `config.schedule.boardPath`.

**The read lives in `ledger_query.py`**, which is the one implementation of the
Query every read-side skill calls. This file owns only what is board-specific:
grouping into the five tabs and the four colour groups, card copy, and the HTML.
Derived state (`overdue`, staleness, snooze, ready-to-close) is not recomputed
here, so the board and every chase agree about the same ledger.

Reconcile is NOT done here either. A deterministic offline script cannot reach
live sources, so it renders the verdicts already in the ledger; the `board` and
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
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# the shared Query sits beside this script; make it importable whether this file
# is executed directly or loaded by a test harness
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_query as lq  # noqa: E402

VERIFY_LABELS = {
    "verified-open": "verified open",
    "resolved": "resolved",
    "reassigned": "reassigned",
    "mis-attributed": "mis-attributed",
    "unverifiable": "unverified - confirm",
    None: "unverified",
}
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
    if promise.get("_pronouns"):
        # recorded pronouns travel with the name, at the point copy gets written.
        # owner strings often carry their own parenthetical ("Name (Org)"), so the
        # pronouns go directly after the name rather than trailing the whole string
        name, sep, rest = owner.partition(" (")
        owner = "%s (%s)%s%s" % (name, promise["_pronouns"], sep, rest)
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
    related = promise.get("relatedRefs") or []
    if isinstance(related, list) and related:
        # refs, not urls: show them so a superseding ticket is visible on the card
        parts.append(
            '<span class="since">also: %s</span>'
            % esc(", ".join(str(r) for r in related if str(r).strip()))
        )
    if not parts:
        parts.append('<span class="since">no link on record</span>')
    return '<div class="links">%s</div>' % "".join(parts)


def context_html(promise):
    """The `.ctx` block: deadline-override reason, then the latest-state `note`.

    Both are fields a run can write, so both must render (ledger-schema.md's
    no-write-only-overlay-field invariant). Empty when neither is present.
    """
    parts = []
    reason = promise.get("deadlineTypeReason")
    if reason and (promise.get("deadlineType") or "hard") != "hard":
        parts.append("<b>Soft date:</b> %s" % esc(reason))
    if promise.get("note"):
        parts.append(esc(promise["note"]))
    if not parts:
        return ""
    return '\n  <div class="ctx">%s</div>' % " ".join(parts)


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
        '  <div class="do"><b>First action:</b> %s</div>%s\n'
        "  %s\n"
        "</div>"
    ) % (
        CARD_VARIANT[state],
        esc(step_text(promise, state, now)),
        esc(promise.get("what") or promise.get("title")),
        "".join(chips),
        esc(action_text(promise, state, config)),
        context_html(promise),
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


def board_note(board, failures, collapsed, warnings, config):
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
    if warnings:
        names = ", ".join(sorted(w["file"] for w in warnings))
        parts.append(
            "%s %s a frontmatter warning: %s."
            % (
                plural(len(warnings), "record"),
                "carries" if len(warnings) == 1 else "carry",
                names,
            )
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


def render(config, promises, failures, collapsed, warnings, state, now, template_text):
    board, tomorrow, waiting_tab, shipped, history = group_promises(promises, now)
    out = template_text
    tokens = {
        "{{LAST_SWEPT}}": esc(humanize_since(state.get("lastSwept"), now)),
        "{{COUNTS}}": counts_line(board, waiting_tab, shipped),
        "{{N_SHIPPED}}": str(len(shipped)),
        "{{N_WAITING}}": str(len(waiting_tab)),
        "{{N_TOMORROW}}": str(len(tomorrow)),
        "{{N_HISTORY}}": str(len(history)),
        "{{BOARD_NOTE}}": esc(board_note(board, failures, collapsed, warnings, config)),
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

    config = lq.Config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()

    template_path = (
        Path(args.template)
        if args.template
        else Path(__file__).resolve().parent.parent / "assets" / "dashboard-template.html"
    )
    template_text = template_path.read_text(encoding="utf-8")

    promises, query_meta = lq.query(config, now)
    failures = query_meta["failures"]
    collapsed = query_meta["collapsed"]
    state = query_meta["state"]
    warnings = query_meta["warnings"]
    text, groups = render(
        config, promises, failures, collapsed, warnings, state, now, template_text
    )
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
        for warning in warnings:
            print("  frontmatter warning: %s (%s)" % (warning["file"], warning["warning"]))
        for item in sorted(collapsed, key=lambda c: c["id"]):
            print("  deduped: state.json %s collapsed into %s" % (item["id"], item["into"]))
        print("board: %s" % (target if target else "(boardPath unset, nothing written)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
