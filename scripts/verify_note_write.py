#!/usr/bin/env python3
"""Verify a note is well-formed immediately AFTER a write-back, before the
write is considered successful.

This exists because a duplicate `dateModified` key reached a real note in the
wild: a write-back appended a new `dateModified:` line without checking whether
one already existed, and nothing checked the result. PyYAML (and this plugin's
own `frontmatter.py`) both parse a duplicate key silently and keep the last
value, so the damage produced no error - it just sat in the vault, undetected,
until this session's read-side work happened to surface it as a lint.

`reference/ledger-schema.md`'s write rule was already "round-trip the
frontmatter line-wise, touch only the changed lines." That is a correct rule
that a session can still get wrong under the same conditions that produced the
bug it is meant to prevent. This script is the check that catches it anyway:
mechanical, and run every time, because a rule that is only prose is a rule a
tired session skips.

Usage:
    verify_note_write.py --note <path> [--backup <path>] [--restore-on-failure]

Exit status:
    0  the note is well-formed: parses, no duplicate keys, carries `task` in
       tags, and the body's fenced frontmatter block is intact.
    1  it is not. With --backup and --restore-on-failure, the original is
       restored and the damaged version is reported, never left in place.
    2  usage error (bad arguments, note or backup missing).

This is a POST-write check, not a pre-write validator: it has no opinion about
what the write should have contained, only about whether the result is a note
every other script in this plugin can still read. Stdlib only, matching every
other script here.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter import FrontmatterError, duplicate_frontmatter_keys, parse_frontmatter  # noqa: E402


def split_frontmatter(text):
    """Same contract as ledger_query.split_frontmatter: (frontmatter, body) or
    raises ValueError. Duplicated rather than imported to keep this script
    runnable standalone with only frontmatter.py as a dependency - the write
    path and the read path should not have to deploy in lockstep.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("no opening --- on frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    raise ValueError("no closing --- on frontmatter")


def check(note_path):
    """Return a list of problems. Empty means the note is well-formed."""
    problems = []
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError as error:
        return ["cannot read the note: %s" % error]

    try:
        frontmatter_text, body = split_frontmatter(text)
    except ValueError as error:
        return ["frontmatter block is broken: %s" % error]

    duplicates = duplicate_frontmatter_keys(frontmatter_text)
    if duplicates:
        problems.append(
            "duplicate frontmatter key(s) introduced by this write: %s"
            % ", ".join(duplicates)
        )

    try:
        frontmatter = parse_frontmatter(frontmatter_text)
    except FrontmatterError as error:
        problems.append("frontmatter no longer parses: %s" % error)
        frontmatter = {}

    tags = frontmatter.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if "task" not in [str(t).strip() for t in tags]:
        problems.append("the `task` tag is missing after this write")

    if not body.strip():
        problems.append("the note body is empty after this write")

    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--note", required=True, help="the note just written")
    parser.add_argument("--backup", help="the pre-write copy, for --restore-on-failure")
    parser.add_argument(
        "--restore-on-failure", action="store_true",
        help="on any problem, replace --note with --backup (requires --backup)",
    )
    args = parser.parse_args(argv)

    note_path = Path(args.note).expanduser()
    if not note_path.is_file():
        print("no such note: %s" % note_path, file=sys.stderr)
        return 2
    if args.restore_on_failure and not args.backup:
        print("--restore-on-failure requires --backup", file=sys.stderr)
        return 2

    problems = check(note_path)
    if not problems:
        print("OK: %s" % note_path.name)
        return 0

    for problem in problems:
        print("PROBLEM: %s" % problem)

    if args.restore_on_failure:
        backup_path = Path(args.backup).expanduser()
        if not backup_path.is_file():
            print(
                "cannot restore: backup not found at %s. The damaged write is "
                "still in place at %s - fix it by hand." % (backup_path, note_path),
                file=sys.stderr,
            )
            return 1
        shutil.copy2(backup_path, note_path)
        print("RESTORED from backup: %s" % backup_path)
    else:
        print(
            "the write introduced a problem and was NOT rolled back "
            "(pass --backup PATH --restore-on-failure to auto-restore)."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
