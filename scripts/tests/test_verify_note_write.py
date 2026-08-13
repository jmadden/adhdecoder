#!/usr/bin/env python3
"""Tests for scripts/verify_note_write.py, the write-side guard.

Run: python3 scripts/tests/test_verify_note_write.py

This is the check meant to catch the exact bug that motivated it: a write-back
that appends a new frontmatter key without checking whether one already exists,
producing a note that parses cleanly but silently discarded a value. Cases here
reproduce that bug directly (not just a synthetic analogue) and prove the
restore path leaves no damaged file behind.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "verify_note_write.py"

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


GOOD_NOTE = """---
title: Example task
status: todo
priority: medium
due: 2026-08-20
dateCreated: 2026-08-01T09:00:00-07:00
dateModified: 2026-08-01T09:00:00-07:00
customer: Acme Corp
requester:
  - A. Contact
tags:
  - task
---

> **Summary:** An example note used only by the test suite.
"""


def run(note_path, extra=()):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--note", str(note_path), *extra],
        capture_output=True, text=True,
    )


def main():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)

        # --- the well-formed case: a clean write passes -----------------
        clean = tmp / "clean.md"
        clean.write_text(GOOD_NOTE)
        result = run(clean)
        check(result.returncode == 0 and "OK" in result.stdout, "a well-formed note passes")

        # --- the exact bug: a write-back appends a key that already exists
        backup = tmp / "backup.md"
        shutil.copy2(clean, backup)
        broken = tmp / "broken.md"
        broken.write_text(
            GOOD_NOTE.replace(
                "tags:\n  - task\n---",
                "tags:\n  - task\ndateModified: 2026-08-13T09:00:00-07:00\n---",
            )
        )
        result = run(broken)
        check(
            result.returncode == 1 and "duplicate frontmatter key" in result.stdout
            and "dateModified" in result.stdout,
            "a write-back that appends an already-present key is caught, naming it",
        )

        # --- restore-on-failure actually restores, byte for byte --------
        victim = tmp / "victim.md"
        shutil.copy2(broken, victim)
        result = run(victim, ["--backup", str(backup), "--restore-on-failure"])
        check(result.returncode == 1 and "RESTORED" in result.stdout, "restore reports success")
        check(
            victim.read_text() == backup.read_text(),
            "the note is byte-identical to the pre-write backup after restore",
        )

        # --- a write that drops the closing fence ------------------------
        no_fence = tmp / "no_fence.md"
        no_fence.write_text(GOOD_NOTE.replace("---\n\n> **Summary", "\n\n> **Summary"))
        result = run(no_fence)
        check(
            result.returncode == 1 and "frontmatter block is broken" in result.stdout,
            "a write that damages the frontmatter fence is caught",
        )

        # --- a write that drops the task tag -----------------------------
        no_tag = tmp / "no_tag.md"
        no_tag.write_text(GOOD_NOTE.replace("tags:\n  - task\n", "tags:\n  - work\n"))
        result = run(no_tag)
        check(
            result.returncode == 1 and "task` tag is missing" in result.stdout,
            "a write that drops the required tag is caught (the note would go "
            "invisible to the adapter, same class of harm as a parse failure)",
        )

        # --- restore requires a backup that actually exists --------------
        before_restore_attempt = broken.read_text()
        result = run(broken, ["--backup", str(tmp / "nonexistent.md"), "--restore-on-failure"])
        check(
            result.returncode == 1 and "backup not found" in result.stderr,
            "a missing backup fails loudly rather than silently leaving damage",
        )
        check(
            broken.read_text() == before_restore_attempt,
            "the damaged note is left exactly as-is when restore cannot find its backup",
        )

        # --- usage errors --------------------------------------------------
        missing = run(tmp / "does-not-exist.md")
        check(missing.returncode == 2, "a missing note is a usage error, not a silent pass")

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
