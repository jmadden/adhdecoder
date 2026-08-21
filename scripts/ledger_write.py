#!/usr/bin/env python3
"""THE write path for `state.json`. Stdlib only.

Every promise a sweep records goes through here. It exists because sweep runs
unattended three times a day and, until now, hand-wrote JSON from prose
instructions - the one place in ADHDecoder where a subtle bug could corrupt the
ledger with nobody watching. A malformed `direction`, a rewritten `history`, a
duplicate record, a half-written file: all silent, all only visible much later
as counts that stopped making sense.

What this guarantees, on every operation:

1. **The reality gate holds.** No promise is written without a named `owner`, a
   concrete `what`, and an `expectBy`. That rule is what keeps the ledger from
   filling with vague "go find out X" phantoms.
2. **The schema holds.** Field names and enum values are checked against
   `ledger_schema.py`, the same module the read-side validator uses, so a field
   can never be legal to write but unknown to `doctor`.
3. **Dedup is checked against the FULL union, not just state.json.** A candidate
   whose `source.url` an Obsidian note already owns is refused, because writing
   it creates a record the Query silently collapses on every read - a duplicate
   that never appears on the board but accumulates in the file forever.
4. **History is append-only.** No operation can rewrite or drop a prior entry.
5. **The write is atomic and checked afterwards.** Temp file then `os.replace`,
   then the whole file is re-validated; if the result would be invalid it is
   rolled back from the backup rather than left in place.
6. **Concurrent writers are detected.** The file is hashed before the mutation
   and re-hashed immediately before the replace; if another session (a desktop
   run, a scheduled run) wrote in between, this refuses rather than clobbering.

Usage:
    ledger_write.py --config CFG capture --confirmed --title T [--customer C]
                                                [--due YYYY-MM-DD] [--summary S]
    ledger_write.py --config CFG promote --confirmed --id ID
    ledger_write.py --config CFG add            [--promise-json JSON] [--dry-run]
    ledger_write.py --config CFG enrich --id ID --note TEXT [--expect-by DATE]
                                                [--verify-status S] [--verify-reason R]
    ledger_write.py --config CFG record-verify --id ID --status S [--reason R]
                                                [--source-url URL]
    ledger_write.py --config CFG draft-mark-met --id ID --reason R
    ledger_write.py --config CFG snooze --id ID --until YYYY-MM-DD --reason R
    ledger_write.py --config CFG snooze --id ID --unsnooze
    ledger_write.py --config CFG suppress --ref REF --reason R [--source S]
                                                [--context C] [--record-id ID]
    ledger_write.py --config CFG suppress --ref REF --unsuppress
    ledger_write.py --config CFG record-sweep   [--sources-json JSON] [--now ISO]
    ledger_write.py --config CFG mark-seen --id ID [--id ID ...]

`add` and `record-sweep` read their JSON payload from stdin when the flag is
omitted. Exit 0 on success, 1 on a refused write (with the reason), 2 on usage.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_query as lq  # noqa: E402
import verify_note_write  # noqa: E402
from ledger_schema import (  # noqa: E402
    SCHEMA_VERSION,
    SUPPRESSED,
    SWEEP_LOG_CAP,
    VERIFY_STATUSES,
    PROJECT_STATUSES,
    reality_gate,
    validate_project,
    validate_promise,
    validate_state,
)


class Refused(Exception):
    """A write that must not happen. The message is shown to the caller."""


# --------------------------------------------------------------------------
# file handling
# --------------------------------------------------------------------------

def digest(path):
    """Content hash, or None when the file does not exist."""
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_state(path):
    path = Path(path)
    if not path.is_file():
        raise Refused("no ledger at %s - run `setup` first" % path)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise Refused(
            "the ledger did not parse: %s\nRefusing to write on top of a file I "
            "cannot read; if another session is mid-write, re-run in a moment." % error
        )


def backup(path, instance_path):
    """Copy the pre-write file somewhere visible, and return its path."""
    backups = Path(instance_path) / "ledger-backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    target = backups / ("state.%s.json" % stamp)
    shutil.copy2(path, target)
    return target


def write_atomic(path, state, expected_digest):
    """Serialise, verify the file has not changed under us, then replace.

    The digest re-check is the concurrency guard: two ADHDecoder sessions can be
    live at once (a desktop app and a scheduled run have already overlapped in
    practice), and last-writer-wins would silently discard the other's work.
    """
    path = Path(path)
    if digest(path) != expected_digest:
        raise Refused(
            "another session wrote the ledger while this operation was preparing.\n"
            "Nothing was changed. Re-run to pick up their write and apply this on top."
        )
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=".ledger-write-",
        suffix=".tmp", delete=False,
    )
    try:
        json.dump(state, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(handle.name, 0o666 & ~umask)
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise


def commit(path, state, expected_digest, backup_path, problems_before):
    """Write, then re-validate; roll back if the write made things WORSE.

    Deliberately a delta check, not an absolute one. A real ledger carries
    legacy baggage - deprecated field names from before the schema was pinned,
    for instance - and refusing to write until the whole file is pristine would
    make this script unusable on exactly the data it exists to protect. The
    contract is "this write introduces no new problem", which is enforceable
    today; "the file is perfect" is a migration, and a separate decision.
    """
    write_atomic(path, state, expected_digest)
    try:
        written = read_state(path)
    except Refused:
        shutil.copy2(backup_path, path)
        raise Refused("the written ledger did not parse; restored from %s" % backup_path)
    introduced = [p for p in validate_state(written) if p not in problems_before]
    if introduced:
        shutil.copy2(backup_path, path)
        raise Refused(
            "the write would have introduced %d new schema problem(s), so it was "
            "rolled back from %s:\n  %s"
            % (len(introduced), backup_path, "\n  ".join(introduced[:10]))
        )


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

def existing_union(config, now):
    """Every promise the system can currently see, notes included.

    Deliberately the Query and not just state.json: a candidate whose source url
    a note already owns must be refused here, or it becomes a state.json record
    the Query collapses on every read - invisible on the board, permanent in the
    file. That accumulation bug has already happened once.
    """
    promises, _meta = lq.query(config, now)
    return promises


def op_add(args, config, now):
    payload = args.promise_json if args.promise_json else sys.stdin.read()
    try:
        record = json.loads(payload)
    except json.JSONDecodeError as error:
        raise Refused("the promise payload is not valid JSON: %s" % error)
    if not isinstance(record, dict):
        raise Refused("the promise payload must be a single JSON object")

    record.setdefault("status", "pending")
    record.setdefault("created", now.isoformat(timespec="seconds"))
    record.setdefault("lastVerified", now.isoformat(timespec="seconds"))
    record.setdefault("history", [])
    if not record["history"]:
        record["history"] = [{"ts": now.isoformat(timespec="seconds"), "note": "Promise captured."}]

    problems = validate_promise(record)
    if problems:
        raise Refused("refusing to add this promise:\n  " + "\n  ".join(problems))

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    # Checked first among the state-dependent gates: "this must never exist at
    # all" outranks "this already exists". `suppress` used to be advisory - the
    # sweep plan reported the refs and obeying them was the sweeping model's job -
    # which meant a suppression held only for as long as something remembered to
    # look. Enforcing it HERE makes it structural: `add` is the only way a promise
    # is born, so no sweep, skill or unattended run can resurrect a suppressed ref
    # whatever it read or skipped.
    #
    # Matched on `source.ref` only, case-folded and exact - never a substring, and
    # never by scanning `source.url` for an id it happens to contain. Same reason
    # stated in _find_suppression: a missed suppression is recoverable noise on one
    # sweep, a wrongly-matched one silently hides a real ask.
    #
    # `capture` is deliberately NOT gated the same way: it runs with the user
    # present, asking for this task by name, and refusing an explicit human ask
    # would be answering the wrong question.
    add_ref = (record.get("source") or {}).get("ref")
    if add_ref:
        entries = state.get("suppressed") or []
        found = _find_suppression(entries, add_ref) if isinstance(entries, list) else None
        if found is not None:
            entry = entries[found]
            raise Refused(
                "source ref %r is suppressed, so it must never become a promise "
                "again:\n  %s\n"
                "If that is now wrong, clear it first:\n"
                "  ledger_write.py --config CFG suppress --ref %s --unsuppress"
                % (add_ref, entry.get("reason") or "no reason recorded", add_ref)
            )

    if any(p.get("id") == record["id"] for p in state.get("promises") or []):
        raise Refused(
            "a promise with id %r already exists - use `enrich` to update it, "
            "never a second record" % record["id"]
        )

    url = (record.get("source") or {}).get("url")
    if url and not record.get("noteOnly"):
        for existing in existing_union(config, now):
            existing_url = (existing.get("source") or {}).get("url")
            if existing_url == url and not existing.get("noteOnly"):
                raise Refused(
                    "source.url is already owned by %r (%s).\n"
                    "Enrich that record instead: a second record under a different "
                    "id is collapsed by the Query on every read, so it would never "
                    "show on the board but would live in the file forever."
                    % (existing.get("id"), existing.get("_origin", "state"))
                )

    seen = ((state.get("dedup") or {}).get("seen")) or []
    if record["id"] in seen:
        raise Refused(
            "id %r is already in dedup.seen - it was decoded before. Enrich the "
            "existing record rather than re-adding it." % record["id"]
        )

    if args.dry_run:
        print("DRY RUN: would add %s" % record["id"])
        return 0

    state.setdefault("promises", []).append(record)
    state.setdefault("dedup", {}).setdefault("seen", []).append(record["id"])
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("added %s" % record["id"])
    return 0


def op_enrich(args, config, now):
    if not args.note:
        raise Refused("`enrich` requires --note: every change leaves a history line")

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    target = None
    for record in state.get("promises") or []:
        if record.get("id") == args.id:
            target = record
            break
    if target is None:
        raise Refused("no promise with id %r in state.json" % args.id)

    if target.get("status") == "promoted":
        raise Refused(
            "%r is `promoted` (collapsed into %r). Enrich the record it points at, "
            "never the collapsed one." % (args.id, target.get("promotedTo"))
        )

    history_before = list(target.get("history") or [])

    updated = dict(target)
    updated["lastVerified"] = now.isoformat(timespec="seconds")
    if args.expect_by:
        updated["expectBy"] = args.expect_by
    if args.verify_status:
        updated["verifyStatus"] = args.verify_status
    if args.verify_reason:
        updated["verifyReason"] = args.verify_reason
    if args.status:
        updated["status"] = args.status
    updated["history"] = history_before + [
        {"ts": now.isoformat(timespec="seconds"), "note": args.note}
    ]

    problems = validate_promise(updated, enforce_reality_gate=False)
    if problems:
        raise Refused("refusing to enrich %r:\n  %s" % (args.id, "\n  ".join(problems)))

    # append-only, checked rather than assumed
    if updated["history"][: len(history_before)] != history_before:
        raise Refused("internal error: history would not be append-only; refusing")

    if args.dry_run:
        print("DRY RUN: would enrich %s (+1 history line)" % args.id)
        return 0

    target.clear()
    target.update(updated)
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("enriched %s" % args.id)
    return 0


def op_record_sweep(args, config, now):
    payload = args.sources_json if args.sources_json else sys.stdin.read()
    payload = payload.strip()
    sources = {}
    if payload:
        try:
            sources = json.loads(payload)
        except json.JSONDecodeError as error:
            raise Refused("the sources payload is not valid JSON: %s" % error)
    if not isinstance(sources, dict):
        raise Refused("the sources payload must be a JSON object of {source: result}")

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    stamp = now.isoformat(timespec="seconds")
    state["lastSwept"] = stamp
    log = state.setdefault("sweepLog", [])
    log.append({"ts": stamp, "sources": sources})
    # a log, not a store: keep the tail so it cannot grow without bound
    if len(log) > SWEEP_LOG_CAP:
        del log[: len(log) - SWEEP_LOG_CAP]

    if args.dry_run:
        print("DRY RUN: would set lastSwept=%s and append 1 sweepLog entry" % stamp)
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("recorded sweep at %s (%d sources)" % (stamp, len(sources)))
    return 0


ILLEGAL_FILENAME = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


TITLE_MAX = 120


def _note_filename(title):
    """A safe filename from a title. Refuses rather than inventing one.

    A too-long title is refused, not truncated. The title becomes the filename,
    the note's headline in the sidebar, and the promise id - truncating a
    paragraph to 120 characters produces a bad value for all three, silently.
    Promoting a `what` written as a paragraph should stop and ask for a real
    headline instead.
    """
    cleaned = ILLEGAL_FILENAME.sub("", str(title)).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise Refused("the title contains no usable filename characters: %r" % title)
    if len(cleaned) > TITLE_MAX:
        raise Refused(
            "the title is %d characters; a note title is a headline, and it also "
            "becomes the filename and the promise id.\nPass --title with something "
            "under %d characters. The full text is kept in the summary.\n  got: %s..."
            % (len(cleaned), TITLE_MAX, cleaned[:80])
        )
    return cleaned + ".md"


_YAML_RESERVED = {
    "y", "n", "yes", "no", "true", "false", "on", "off", "null", "~", "",
}


def _yaml_scalar(value):
    """Emit a value that a REAL YAML parser reads back as this exact string.

    Load-bearing, and not obvious. `frontmatter.py` is permissive about a plain
    scalar containing ": ", but PyYAML and Obsidian both reject it outright
    ("mapping values are not allowed here"). Writing an unquoted title like
    "Acme Corp: explain the options" would therefore produce a note THIS system
    reads happily and the user's own editor cannot open at all - the worst
    possible failure, because nothing here would report it.

    Also quotes the values YAML would coerce to a non-string: a title of "yes"
    becomes a boolean, "#tag" becomes a comment, "2026" becomes an int.
    """
    text = str(value)
    if "\n" in text or "\r" in text:
        raise Refused("a frontmatter value may not contain a newline: %r" % text)
    needs_quoting = (
        text.strip() != text
        or text.lower() in _YAML_RESERVED
        or text[:1] in "#&*!|>%@`[]{},\"'?-"
        or ": " in text
        or text.endswith(":")
        or re.fullmatch(r"-?\d+(\.\d+)?", text) is not None
    )
    if not needs_quoting:
        return text
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"')


def _note_body(title, summary, requester, source_url):
    lines = ["> **Summary:** %s" % (summary or title)]
    if requester and requester.strip().lower() != "self":
        lines.append("> Report to: %s" % requester)
    lines.append("")
    if source_url:
        lines.append("- Source: [link](%s)" % source_url)
        lines.append("")
    return "\n".join(lines)


def _note_text(fields, body):
    """Canonical TaskNotes frontmatter, in the field order real notes use.

    Written line-wise rather than serialised from a dict: `frontmatter.py` reads
    a subset and does not emit YAML, and hand-building the block keeps the output
    byte-predictable and identical in shape to what TaskNotes itself writes.
    """
    out = ["---"]
    for key in ("title", "status", "priority", "due", "scheduled",
                "dateCreated", "dateModified"):
        value = fields.get(key)
        if value:
            out.append("%s: %s" % (key, _yaml_scalar(value)))
    projects = fields.get("projects") or []
    if projects:
        out.append("projects:")
        out.extend("  - %s" % _yaml_scalar(p) for p in projects)
    else:
        out.append("projects: []")
    if fields.get("customer"):
        out.append("customer: %s" % _yaml_scalar(fields["customer"]))
    requester = fields.get("requester")
    if requester:
        out.append("requester:")
        out.append("  - %s" % _yaml_scalar(requester))
    out.append("tags:")
    out.append("  - task")
    out.append("---")
    out.append("")
    out.append(body)
    return "\n".join(out) + "\n"


def _write_note(config, now, fields, body, source_url, exclude_id=None):
    """Create ONE new note in tasksDir. Shared by `capture` and `promote`.

    Deliberately writes no `state.json`: the Query enumerates tasksDir on the
    next read, so a captured task simply appears. That keeps note creation off
    the contended ledger file entirely.
    """
    if not config.readwrite:
        raise Refused(
            "creating a note needs `writeMode: readwrite` AND "
            "`cutover.singleWriterConfirmed: true` (see reference/cutover.md).\n"
            "Under readonly, ADHDecoder writes nothing to the vault by design."
        )
    if not config.tasks_dir.is_dir():
        raise Refused("the notes directory does not exist: %s" % config.tasks_dir)

    filename = _note_filename(fields["title"])
    target = config.tasks_dir / filename
    if target.exists():
        raise Refused(
            "a note named %r already exists - refusing to overwrite it.\n"
            "Give the task a different title, or enrich the existing note."
            % filename
        )

    if source_url:
        for existing in existing_union(config, now):
            # `promote` carries the promise's OWN url onto the new note, so the
            # record being collapsed must not count as a collision with itself
            if exclude_id and existing.get("id") == exclude_id:
                continue
            existing_url = (existing.get("source") or {}).get("url")
            if existing_url == source_url and not existing.get("noteOnly"):
                raise Refused(
                    "source.url is already owned by %r - enrich that instead of "
                    "creating a second record for the same item"
                    % existing.get("id")
                )

    text = _note_text(fields, body)

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(config.tasks_dir), prefix=".capture-",
        suffix=".tmp", delete=False,
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(handle.name, 0o666 & ~umask)
        os.replace(handle.name, target)
    except BaseException:
        handle.close()
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise

    # same post-write gate the write-back rule requires; a bad write leaves no
    # debris behind rather than a half-formed note nobody notices
    problems = verify_note_write.check(target)
    if problems:
        target.unlink()
        raise Refused(
            "the note failed its post-write check and was removed:\n  %s"
            % "\n  ".join(problems)
        )
    return target


def _route(state, promise_id):
    """Where does ADHDecoder-owned metadata for this id belong?

    A promise that lives in `state.json` keeps it on the record. Anything else -
    a note-backed record - keeps it in the `itemMeta` companion, keyed by id.
    This branch is the one that keeps a read-only backend read-only, so it is
    decided here rather than restated in prose at each call site.
    """
    for record in state.get("promises") or []:
        if record.get("id") == promise_id:
            return "record", record
    return "itemMeta", state.setdefault("itemMeta", {}).setdefault(promise_id, {})


def op_record_verify(args, config, now):
    if args.status not in VERIFY_STATUSES:
        raise Refused(
            "--status must be one of %s" % [s for s in VERIFY_STATUSES if s]
        )

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    where, target = _route(state, args.id)

    if where == "itemMeta" and not any(
        p.get("id") == args.id for p in existing_union(config, now)
    ):
        raise Refused(
            "no promise or note with id %r - refusing to create an itemMeta entry "
            "for something the Query cannot see (that is how orphaned overlay "
            "records accumulate)" % args.id
        )

    target["verifyStatus"] = args.status
    if args.reason:
        target["verifyReason"] = args.reason
    target["lastVerified"] = now.isoformat(timespec="seconds")

    if args.source_url:
        # the link reconcile actually found, kept rather than discarded; on a
        # note-backed record this upgrades the overlay, never the note
        target["source"] = {
            "type": args.source_type or "unknown",
            "ref": args.source_ref,
            "url": args.source_url,
        }
        target["noteOnly"] = False

    if where == "record":
        problems = validate_promise(target, enforce_reality_gate=False)
        if problems:
            raise Refused("refusing to record verify on %r:\n  %s"
                          % (args.id, "\n  ".join(problems)))

    if args.dry_run:
        print("DRY RUN: would record %s on %s (%s)" % (args.status, args.id, where))
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("recorded %s for %s -> %s" % (args.status, args.id, where))
    return 0


def op_draft_mark_met(args, config, now):
    """Park a 'the source says this is done' decision the user has not seen yet.

    Only ever a draft: a record ADHDecoder cannot write (a read-only note) must
    not be closed on its behalf. The board renders these in Ready to close until
    the user acts, which is the only thing keeping the note store and reality
    from drifting apart.
    """
    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    if not any(p.get("id") == args.id for p in existing_union(config, now)):
        raise Refused("no promise or note with id %r" % args.id)

    where, target = _route(state, args.id)
    if where == "record":
        raise Refused(
            "%r lives in state.json, which ADHDecoder can write directly - use "
            "`enrich --status met` rather than parking a draft. Drafts exist for "
            "records this cannot write." % args.id
        )

    entry = state.setdefault("itemMeta", {}).setdefault(args.id, {})
    if entry.get("appliedMarkMet"):
        raise Refused(
            "%r already has an appliedMarkMet audit entry - it was closed. "
            "Refusing to park a new draft over a completed close." % args.id
        )
    entry["markMetDraft"] = {
        "status": "done",
        "completedDate": args.completed_date or now.date().isoformat(),
        "reason": args.reason,
    }

    if args.dry_run:
        print("DRY RUN: would park a markMetDraft on %s" % args.id)
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("parked markMetDraft for %s (renders in Ready to close until applied)" % args.id)
    return 0


def _clear_overlay_snooze(state, promise_id):
    """Strip the snooze keys from the `itemMeta` companion, pruning an emptied entry.

    Called on BOTH branches, which is not symmetry for its own sake. On the
    itemMeta branch this IS the unsnooze. On the record branch it is what makes
    an unsnooze take effect at all: the Query overlays `itemMeta` ON TOP of the
    record, so a record whose `snoozedUntil` was set to None while a stale
    overlay value survived still reads as snoozed - the op reports success and
    changes nothing.

    An entry left holding only a cleared snooze is an orphan, which is how stale
    overlay records accumulate (`reference/ledger-schema.md`), so an emptied one
    is removed. This is the only place in this file that deletes an itemMeta key.
    """
    item_meta = state.get("itemMeta") or {}
    entry = item_meta.get(promise_id)
    if not isinstance(entry, dict):
        return
    for field in ("snoozedUntil", "snoozeReason"):
        entry.pop(field, None)
    if not entry:
        del item_meta[promise_id]


def op_snooze(args, config, now):
    """Park a promise until a date: still owed, deliberately quiet until then.

    `snoozedUntil` was readable everywhere at promise level and writable nowhere.
    The Query overlays it, derives `_snoozed`, suppresses on it and serves a
    `snoozed` selector - but the only writer was `project-set`, which quiets a
    project's ROLLUP and deliberately leaves its members surfacing
    (`reference/projects.md`). That left hand-editing `state.json` as the only
    route, the one write method the schema doc names as the source of every
    stale overlay entry in the wild.

    Routed through `_route`, so a note-backed record snoozes in the `itemMeta`
    companion and NO note is written in any write mode: a snooze is
    ADHDecoder-owned bookkeeping, not task truth, and stays in the companion even
    post-cutover (`adapters/obsidian/reference.md`).

    History is appended on the record branch only - `ITEM_META` has no `history`
    field, so on the overlay branch `snoozeReason` IS the audit trail. That
    asymmetry is why --reason is required rather than optional.
    """
    if not args.unsnooze:
        if not args.until:
            raise Refused(
                "snooze needs --until YYYY-MM-DD, or --unsnooze to clear an existing one"
            )
        if not args.reason:
            raise Refused(
                "`snooze` requires --reason: an unexplained hold is indistinguishable "
                "from a bug three weeks later, and on a note-backed record the reason "
                "is the only audit trail there is"
            )
        # checked explicitly rather than left to a downstream validator the way
        # `project-set` leaves it: the itemMeta branch has NO schema gate on the
        # write path (`validate_state` only type-checks the container, never the
        # entries), so a malformed date there would be written successfully and
        # surface days later as a `doctor` gap
        until = lq.as_date(args.until)
        if not until:
            raise Refused("--until expects YYYY-MM-DD, got %r" % args.until)
        if until <= now.date():
            raise Refused(
                "--until %s is not in the future; it would read as an applied "
                "off-switch while changing nothing." % args.until
            )

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    # checked BEFORE _route, because _route's itemMeta branch creates an empty
    # entry as a side effect of asking the question, and an overlay entry for an
    # id the Query cannot see is exactly how orphaned records accumulate
    match = None
    for promise in existing_union(config, now):
        if promise.get("id") == args.id:
            match = promise
            break
    if match is None:
        raise Refused(
            "no promise or note with id %r - refusing to snooze something the "
            "Query cannot see" % args.id
        )
    if not match.get("_open"):
        raise Refused(
            "%r is `%s`, not open. Snoozing a closed promise is a no-op that "
            "looks like success." % (args.id, match.get("status"))
        )

    where, target = _route(state, args.id)
    # snapshotted BEFORE the mutation, because this has to be a delta check for
    # the same reason commit() is one: a real ledger carries legacy baggage (a
    # pre-schema `createdAt`, say), and an absolute gate would refuse to snooze
    # exactly the old records most likely to need parking
    record_problems_before = (
        validate_promise(target, enforce_reality_gate=False) if where == "record" else []
    )

    if args.unsnooze:
        if where == "record":
            target["snoozedUntil"] = None
            target["snoozeReason"] = None
        _clear_overlay_snooze(state, args.id)
        line = "snooze cleared"
        said = "cleared the snooze on"
    else:
        if where == "record":
            target["snoozedUntil"] = args.until
            target["snoozeReason"] = args.reason
            # a stale overlay date would shadow the one just written
            _clear_overlay_snooze(state, args.id)
        else:
            target["snoozedUntil"] = args.until
            target["snoozeReason"] = args.reason
        line = "snoozed until %s - %s" % (args.until, args.reason)
        said = "snoozed"

    if where == "record":
        # a snooze is a human moving this, so it leaves history and counts as
        # movement; `lastVerified` is deliberately NOT bumped - that field means
        # "when the system last looked" (see last_touched() in ledger_query.py)
        history_before = list(target.get("history") or [])
        target["history"] = history_before + [
            {"ts": now.isoformat(timespec="seconds"), "note": line}
        ]
        if target["history"][: len(history_before)] != history_before:
            raise Refused("internal error: history would not be append-only; refusing")

        introduced = [
            problem for problem in validate_promise(target, enforce_reality_gate=False)
            if problem not in record_problems_before
        ]
        if introduced:
            raise Refused("refusing to snooze %r:\n  %s"
                          % (args.id, "\n  ".join(introduced)))

    if args.dry_run:
        print("DRY RUN: would have %s %s (%s)" % (said, args.id, where))
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("%s %s -> %s" % (said, args.id, where))
    return 0


def _fields_from(args, now):
    stamp = now.isoformat(timespec="seconds")
    return {
        "title": args.title,
        "status": "todo",
        "priority": args.priority or "medium",
        "due": args.due,
        "dateCreated": stamp,
        "dateModified": stamp,
        "projects": list(args.project or []),
        "customer": args.customer,
        "requester": args.requester or "Self",
    }


def op_capture(args, config, now):
    """Capture a task straight into the note store, where the user actually works.

    No `expectBy` is required, and that is deliberate rather than a hole in the
    reality gate: the gate governs `state.json` promises, which must be chaseable.
    A note legitimately has no `due` - on real data most do not - and drift
    staleness surfaces those instead. Forcing a date on every quick capture would
    put friction on exactly the thing that has to be frictionless.
    """
    if not args.confirmed:
        raise Refused(
            "`capture` writes a note, so it needs --confirmed: an explicit human "
            "action. Sweeps and scheduled runs never create notes, in any write mode."
        )
    if not str(args.title or "").strip():
        raise Refused("--title is required: it is the concrete thing to be done")

    fields = _fields_from(args, now)
    body = _note_body(args.title, args.summary, fields["requester"], args.source_url)

    if args.dry_run:
        print("DRY RUN: would create %s\n" % (config.tasks_dir / _note_filename(args.title)))
        print(_note_text(fields, body))
        return 0

    target = _write_note(config, now, fields, body, args.source_url)
    print("captured: %s" % target)
    print("(no state.json write - the Query picks it up on the next read)")
    return 0


def op_promote(args, config, now):
    """Turn a state.json promise into a real note, then collapse the original.

    Per reference/promotion.md: the record is kept (history is append-only),
    marked `promoted`, and given `promotedTo` so a later sweep enriches the note
    rather than resurrecting the collapsed record.
    """
    if not args.confirmed:
        raise Refused("`promote` creates a note, so it needs --confirmed")

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    source_record = None
    for record in state.get("promises") or []:
        if record.get("id") == args.id:
            source_record = record
            break
    if source_record is None:
        raise Refused("no state.json promise with id %r" % args.id)
    if source_record.get("status") == "promoted":
        raise Refused(
            "%r is already promoted into %r" % (args.id, source_record.get("promotedTo"))
        )

    title = args.title or source_record.get("title") or source_record.get("what")
    fields = _fields_from(args, now)
    fields["title"] = title
    fields["customer"] = args.customer or source_record.get("context")
    fields["due"] = args.due or source_record.get("expectBy")
    # `requester` means "who asked for this". On an i-owe-them promise `owner` is
    # the user themselves, so copying it across produces "Report to: <the user>".
    # Only a they-owe-me promise has a counterparty worth carrying over, and even
    # then owner is often prose; --requester overrides when it matters.
    if args.requester:
        fields["requester"] = args.requester
    elif source_record.get("direction") == "they-owe-me":
        fields["requester"] = source_record.get("owner") or "Self"
    else:
        fields["requester"] = "Self"

    url = args.source_url or (source_record.get("source") or {}).get("url")
    body = _note_body(title, args.summary or source_record.get("note"),
                      fields["requester"], url)

    if args.dry_run:
        print("DRY RUN: would create %s and collapse %s\n"
              % (config.tasks_dir / _note_filename(title), args.id))
        print(_note_text(fields, body))
        return 0

    # the note is created FIRST; only a real note earns the collapse
    target = _write_note(config, now, fields, body, url, exclude_id=args.id)
    note_id = str(target.relative_to(config.knowledge_path))

    source_record["status"] = "promoted"
    source_record["promotedTo"] = note_id
    source_record.setdefault("history", []).append({
        "ts": now.isoformat(timespec="seconds"),
        "note": "Promoted into %s; this record collapses to a cross-reference." % note_id,
    })

    try:
        backup_path = backup(config.state_file, config.instance_path)
        commit(config.state_file, state, before, backup_path, problems_before)
    except Refused:
        # the note exists but the ledger could not be updated; say so plainly
        # rather than leaving the user to discover a duplicate later
        raise Refused(
            "the note was created at %s, but collapsing %r in state.json failed.\n"
            "Re-run `promote` after resolving that, or the item will show twice."
            % (target, args.id)
        )
    print("promoted %s -> %s" % (args.id, note_id))
    return 0


def _find_suppression(entries, ref):
    """Index of the entry suppressing `ref`, or None. Case-folded exact match.

    Case-folding and whitespace are the only normalisation, deliberately: no
    substring match, no scanning a url for an id it happens to contain. A missed
    suppression is recoverable noise on one sweep; a wrongly-matched one silently
    hides a real ask, which is the failure this whole field exists to prevent.
    """
    wanted = str(ref or "").strip().casefold()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ref") or "").strip().casefold() == wanted:
            return index
    return None


def op_suppress(args, config, now):
    """Stop the sweep from ever turning a source ref into a promise again.

    `suppressed[]` was documented, schema-declared and doctor-validated, and had
    no writer - so the only route was hand-editing `state.json`, the one write
    method `reference/ledger-schema.md` names as the source of every stale entry
    in the wild. The single live entry in the wild got there exactly that way.

    NOT routed through `_route`, unlike `snooze`. A suppression is not per-promise
    metadata that has to follow a record into the `itemMeta` companion; it is a
    top-level list about a SOURCE ref, so there is one place for it whatever
    backend is active. No note is written in any write mode, and there is no
    `--confirmed`: that flag exists for ops that create files in the user's vault
    and diluting it weakens the one place it matters.

    `--reason` is required because `validate-state.py` already treats a reasonless
    entry as a gap, so writing one would emit a `doctor` failure by construction -
    and because a suppressed ref that cannot explain itself becomes permanent by
    default.

    The entry is built from `ledger_schema.SUPPRESSED` field names only. That
    matters here more than elsewhere: `validate_state` type-checks the container
    and never the entries, so `commit()`'s delta check cannot catch a malformed
    suppression. The gate has to be on this side, the same reason `op_snooze`
    validates its date inline.
    """
    ref = str(args.ref or "").strip()
    if not ref:
        raise Refused("suppress needs a non-empty --ref: the source ref to stop raising")
    if not args.unsuppress and not args.reason:
        raise Refused(
            "`suppress` requires --reason: an unexplained suppression is "
            "indistinguishable from a bug, `validate-state.py` reports one as a gap, "
            "and a ref nothing can justify silencing becomes permanent by default"
        )

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    entries = state.setdefault("suppressed", [])
    if not isinstance(entries, list):
        raise Refused(
            "`suppressed` is a %s, not a list; refusing to write over it by hand"
            % type(entries).__name__
        )
    found = _find_suppression(entries, ref)

    if args.unsuppress:
        # The only operation that may shorten this list. Deliberately asymmetric
        # with a duplicate `suppress`, which is a benign no-op because the end
        # state it asked for already holds: un-suppressing a ref that is not
        # suppressed means the caller's model of the file is wrong, and reporting
        # success would hide a typo while a real suppression stayed in place.
        if found is None:
            raise Refused(
                "%r is not suppressed, so there is nothing to clear. Run `doctor` "
                "to see what is." % ref
            )
        removed = entries[found]
        if args.dry_run:
            print("DRY RUN: would un-suppress %s (%s)"
                  % (ref, removed.get("reason") or "no reason recorded"))
            return 0
        del entries[found]
        backup_path = backup(config.state_file, config.instance_path)
        commit(config.state_file, state, before, backup_path, problems_before)
        print("un-suppressed %s - the sweep may raise it again" % ref)
        return 0

    if found is not None:
        # Benign duplicate: print and return 0 rather than erroring or appending,
        # as `mark-seen` does for an id already in dedup.seen. Append-only means
        # the existing entry and its original reason are left exactly as they are.
        print("already suppressed (%s)"
              % (entries[found].get("reason") or "no reason recorded"))
        return 0

    entry = {"ref": ref, "reason": args.reason.strip(),
             "ts": now.isoformat(timespec="seconds")}
    for field, value in (("recordId", args.record_id), ("source", args.source),
                         ("context", args.context)):
        if value:
            entry[field] = value
    unknown = set(entry) - SUPPRESSED
    if unknown:
        raise Refused("internal error: suppression carries undeclared field(s) %s"
                      % ", ".join(sorted(unknown)))

    if args.dry_run:
        print("DRY RUN: would suppress %s - %s" % (ref, entry["reason"]))
        return 0

    entries.append(entry)
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("suppressed %s - %s" % (ref, entry["reason"]))
    return 0


def op_mark_seen(args, config, now):
    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)
    seen = state.setdefault("dedup", {}).setdefault("seen", [])
    added = [i for i in args.id if i not in seen]
    if not added:
        print("nothing to add; all %d id(s) already in dedup.seen" % len(args.id))
        return 0
    if args.dry_run:
        print("DRY RUN: would add %d id(s) to dedup.seen" % len(added))
        return 0
    seen.extend(added)
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("marked seen: %s" % ", ".join(added))
    return 0


def _edit_list(current, added, removed, replace=False, fold=False):
    """Add/remove entries on one of a project's rule lists, order preserved."""
    out = [] if replace else list(current or [])
    key = (lambda v: lq.canonical(v)) if fold else (lambda v: v)
    for entry in added or []:
        if key(entry) not in {key(e) for e in out}:
            out.append(entry)
    for entry in removed or []:
        out = [e for e in out if key(e) != key(entry)]
    return out


def op_project_set(args, config, now):
    """Declare or amend a project. state.json only - no note is ever written.

    Deliberately ONE op rather than add/update/snooze/close: five ops would mean
    five refusal surfaces to keep consistent, and the refusals are the point.
    No `--confirmed`, unlike `capture`/`promote`: that flag exists because those
    create files in the user's vault, and diluting it weakens the one place it
    matters.
    """
    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    projects = state.setdefault("projects", [])
    target = None
    for record in projects:
        if record.get("id") == args.id:
            target = record
            break

    creating = target is None
    if creating:
        if not args.name:
            raise Refused("a new project needs --name")
        target = {
            "id": args.id, "name": args.name, "status": "active",
            "keywords": [], "aliases": [], "sources": [], "include": [], "exclude": [],
        }

    updated = dict(target)
    if args.name:
        updated["name"] = args.name
    if args.status:
        updated["status"] = args.status
    if args.note is not None:
        updated["note"] = args.note or None

    aliases = _edit_list(
        updated.get("aliases"), args.alias, args.unalias,
        replace=args.replace_aliases, fold=True,
    )
    updated["aliases"] = aliases
    keywords = _edit_list(
        updated.get("keywords"), args.keyword, args.unkeyword,
        replace=args.replace_keywords, fold=True,
    )
    for keyword in keywords:
        if not lq.canonical(keyword):
            raise Refused("a blank keyword would match nothing; drop it")
    updated["keywords"] = keywords
    updated["sources"] = _edit_list(
        updated.get("sources"), args.source, args.unsource, fold=True
    )
    include = _edit_list(updated.get("include"), args.include, args.uninclude)
    updated["include"] = include
    updated["exclude"] = _edit_list(updated.get("exclude"), args.exclude, args.unexclude)

    if args.check_in_every is not None:
        updated["checkInEvery"] = args.check_in_every or None
        if not args.check_in_every:
            updated["lastCheckIn"] = None
    if args.checked_in:
        if not updated.get("checkInEvery"):
            raise Refused(
                "%r has no check-in rhythm to reset. Set one with "
                "--check-in-every <days> first." % args.id
            )
        stamp = args.checked_in if args.checked_in != "today" else now.date().isoformat()
        if not lq.as_date(stamp):
            raise Refused("--checked-in expects YYYY-MM-DD (or no value for today)")
        updated["lastCheckIn"] = stamp

    if args.target_date is not None:
        updated["targetDate"] = args.target_date or None
    if args.unsnooze:
        updated["snoozedUntil"] = None
    elif args.snooze:
        if lq.as_date(args.snooze) and lq.as_date(args.snooze) <= now.date():
            raise Refused(
                "--snooze %s is not in the future; it would read as an applied "
                "off-switch while changing nothing." % args.snooze
            )
        updated["snoozedUntil"] = args.snooze
    updated["updated"] = now.isoformat(timespec="seconds")

    # an alias another project already claims would make membership depend on
    # the order of the projects array - a silent, order-dependent bug
    for other in projects:
        if other.get("id") == args.id:
            continue
        clash = {lq.canonical(a) for a in (other.get("aliases") or [])} & {
            lq.canonical(a) for a in aliases
        }
        if clash:
            raise Refused(
                "alias %r is already claimed by project %r. One alias belongs to "
                "one project, or membership depends on array order."
                % (sorted(clash)[0], other.get("id"))
            )

    problems = validate_project(updated)
    if problems:
        raise Refused("refusing to write project %r:\n  %s" % (args.id, "\n  ".join(problems)))

    # a pinned id nothing can see is a member that will never appear
    if include:
        visible = {p.get("id") for p in existing_union(config, now)}
        missing = [i for i in include if i not in visible]
        if missing:
            raise Refused(
                "--include names %d id(s) the Query cannot see: %s\n"
                "A pinned id that matches no promise is a member that never "
                "appears. Check the id, or drop the pin."
                % (len(missing), ", ".join(sorted(missing)[:5]))
            )

    # THE PREVIEW. A project's rules are a lossy translation of a sentence the
    # user said, and the words they say are often not the words in their ledger
    # ("tech writing" appears nowhere; "doc" and "playbook" do). Without showing
    # what the rules actually claim, a project can be declared, look correct, and
    # sit empty forever. So membership is always computed and shown BEFORE the
    # write, with the reason each member matched.
    union = existing_union(config, now)
    member_ids, reasons = lq.project_members(updated, union)
    by_id = {p.get("id"): p for p in union}
    print("%s would claim %d item(s):" % (args.id, len(member_ids)))
    for member_id in member_ids[:25]:
        promise = by_id.get(member_id) or {}
        print("  %s\n      %s" % (
            (promise.get("what") or promise.get("title") or member_id)[:88],
            reasons.get(member_id, "?"),
        ))
    if len(member_ids) > 25:
        print("  ... and %d more" % (len(member_ids) - 25))
    if not member_ids:
        print(
            "  NOTHING MATCHES. This project would be declared and stay empty.\n"
            "  The words in a ledger are rarely the words we say out loud - check\n"
            "  what the items are actually called and adjust --keyword, or pin ids\n"
            "  with --include."
        )

    if args.dry_run:
        print()
        print(json.dumps(updated, indent=2, sort_keys=True))
        print("dry run: nothing written")
        return 0

    if creating:
        projects.append(updated)
    else:
        projects[projects.index(target)] = updated

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print(
        "%s project %s (%d alias(es), %d pinned)"
        % ("declared" if creating else "updated", args.id, len(aliases), len(include))
    )
    return 0


OPS = {
    "capture": op_capture,
    "project-set": op_project_set,
    "promote": op_promote,
    "add": op_add,
    "enrich": op_enrich,
    "record-verify": op_record_verify,
    "draft-mark-met": op_draft_mark_met,
    "snooze": op_snooze,
    "suppress": op_suppress,
    "record-sweep": op_record_sweep,
    "mark-seen": op_mark_seen,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--now", default=None, help="ISO 8601 clock override (tests)")
    parser.add_argument("--dry-run", action="store_true", help="validate, write nothing")
    sub = parser.add_subparsers(dest="op", required=True)

    p_add = sub.add_parser("add", help="record a new promise (reality gate enforced)")
    p_add.add_argument("--promise-json", default=None, help="JSON object; stdin if omitted")

    def _note_args(parser_obj, title_required):
        parser_obj.add_argument("--title", required=title_required)
        parser_obj.add_argument("--customer", default=None)
        parser_obj.add_argument("--requester", default=None, help="defaults to Self")
        parser_obj.add_argument("--due", default=None, help="YYYY-MM-DD; omit when unknown")
        parser_obj.add_argument("--priority", default=None, choices=("high", "medium", "low"))
        parser_obj.add_argument("--project", action="append", default=None)
        parser_obj.add_argument("--summary", default=None)
        parser_obj.add_argument("--source-url", default=None)
        parser_obj.add_argument("--confirmed", action="store_true",
                                help="required: a note write is an explicit human action")

    p_capture = sub.add_parser("capture", help="create a task note in the note store")
    _note_args(p_capture, title_required=True)

    p_promote = sub.add_parser(
        "promote", help="turn a state.json promise into a note, then collapse it")
    p_promote.add_argument("--id", required=True)
    _note_args(p_promote, title_required=False)

    p_enrich = sub.add_parser("enrich", help="update an existing promise, append-only")
    p_enrich.add_argument("--id", required=True)
    p_enrich.add_argument("--note", required=True, help="the history line for this change")
    p_enrich.add_argument("--expect-by", default=None)
    p_enrich.add_argument("--verify-status", default=None)
    p_enrich.add_argument("--verify-reason", default=None)
    p_enrich.add_argument("--status", default=None)

    p_verify = sub.add_parser(
        "record-verify",
        help="persist a reconcile verdict, routed to the record or itemMeta")
    p_verify.add_argument("--id", required=True)
    p_verify.add_argument("--status", required=True)
    p_verify.add_argument("--reason", default=None)
    p_verify.add_argument("--source-url", default=None, help="the link reconcile found")
    p_verify.add_argument("--source-type", default=None)
    p_verify.add_argument("--source-ref", default=None)

    p_draft = sub.add_parser(
        "draft-mark-met",
        help="park a 'looks done' decision for a record this cannot write")
    p_draft.add_argument("--id", required=True)
    p_draft.add_argument("--reason", required=True)
    p_draft.add_argument("--completed-date", default=None)

    p_snooze = sub.add_parser(
        "snooze", help="park a promise until a date, or clear an existing snooze")
    p_snooze.add_argument("--id", required=True)
    p_snooze.add_argument("--until", default=None, help="quiet until YYYY-MM-DD")
    p_snooze.add_argument("--reason", default=None, help="required unless --unsnooze")
    p_snooze.add_argument("--unsnooze", action="store_true")

    p_suppress = sub.add_parser(
        "suppress", help="stop the sweep raising a source ref, or clear that")
    p_suppress.add_argument("--ref", required=True, help="the source ref to silence")
    p_suppress.add_argument("--reason", default=None, help="required unless --unsuppress")
    p_suppress.add_argument("--source", default=None, help="source type, e.g. issues")
    p_suppress.add_argument("--context", default=None, help="customer/context name")
    p_suppress.add_argument("--record-id", default=None,
                            help="the SOURCE system's record id, not a promise id")
    p_suppress.add_argument("--unsuppress", action="store_true")

    p_sweep = sub.add_parser("record-sweep", help="stamp lastSwept + append a sweepLog entry")
    p_sweep.add_argument("--sources-json", default=None, help="JSON {source: result}; stdin if omitted")

    p_project = sub.add_parser(
        "project-set", help="declare or amend a project (state.json only)"
    )
    p_project.add_argument("--id", required=True, help="stable slug")
    p_project.add_argument("--name", default=None)
    p_project.add_argument("--status", default=None, choices=PROJECT_STATUSES)
    p_project.add_argument("--alias", action="append", help="a context spelling to match")
    p_project.add_argument("--unalias", action="append")
    p_project.add_argument(
        "--replace-aliases", action="store_true", help="drop existing aliases first"
    )
    p_project.add_argument("--include", action="append", help="pin a promise id")
    p_project.add_argument("--uninclude", action="append")
    p_project.add_argument(
        "--keyword", action="append",
        help="a word or phrase; matched on a title/what word boundary",
    )
    p_project.add_argument("--unkeyword", action="append")
    p_project.add_argument("--replace-keywords", action="store_true")
    p_project.add_argument(
        "--source", action="append",
        help="narrow to items from here; matched against source.type or source.url",
    )
    p_project.add_argument("--unsource", action="append")
    p_project.add_argument("--exclude", action="append", help="kick a promise id out")
    p_project.add_argument("--unexclude", action="append")
    p_project.add_argument(
        "--check-in-every", type=int, default=None, metavar="DAYS",
        help="check-in rhythm in calendar days; 0 clears it",
    )
    p_project.add_argument(
        "--checked-in", nargs="?", const="today", default=None, metavar="YYYY-MM-DD",
        help="reset the check-in clock (defaults to today)",
    )
    p_project.add_argument("--target-date", default=None, help="YYYY-MM-DD, or '' to clear")
    p_project.add_argument("--snooze", default=None, help="quiet until YYYY-MM-DD")
    p_project.add_argument("--unsnooze", action="store_true")
    p_project.add_argument("--note", default=None)

    p_seen = sub.add_parser("mark-seen", help="add decoded ids to dedup.seen")
    p_seen.add_argument("--id", action="append", required=True)

    args = parser.parse_args(argv)

    try:
        config = lq.Config(args.config)
    except (OSError, json.JSONDecodeError) as error:
        print("cannot read config: %s" % error, file=sys.stderr)
        return 2

    now = datetime.fromisoformat(args.now) if args.now else datetime.now()

    try:
        return OPS[args.op](args, config, now)
    except Refused as error:
        print("REFUSED: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
