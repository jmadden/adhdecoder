#!/usr/bin/env python3
"""Fixture test for scripts/ledger_query.py.

Run: python3 scripts/tests/test_ledger_query.py

The Query is what every read-side skill calls, so what it selects IS what gets
chased. These checks pin the selectors against the shared invented fixture
ledger: that `slipping` never contains a soft or dateless item (a false overdue
chase aimed at a real person), that `drifting` catches the dateless items date
chasing misses, and that suppression and ready-to-close hold across all of them.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "ledger_query.py"
FIXTURES = HERE / "fixtures"
NOW = "2026-08-12T09:15:00"
SELECTORS = (
    "all", "open", "closed", "ready-to-close", "slipping", "drifting",
    "waiting", "owed", "upcoming", "snoozed",
)

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def build_instance(tmp):
    vault = tmp / "vault"
    instance = tmp / "instance"
    shutil.copytree(FIXTURES / "vault", vault)
    instance.mkdir()
    shutil.copyfile(FIXTURES / "ledger" / "fixture-state.json", instance / "state.json")
    config_path = tmp / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "identity": {"name": "Test User", "email": "test@example.com"},
                "storage": {
                    "adapter": "filesystem",
                    "instancePath": str(instance),
                    "knowledgePath": str(vault),
                    "overrides": {"stateFile": "state.json", "tasksDir": "Tasks"},
                },
                "ledger": {"backend": "obsidian", "writeMode": "readonly"},
                "schedule": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return config_path, vault


def q(config_path, selector, extra=()):
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--config", str(config_path),
            "--now", NOW, "--select", selector, "--json", *extra,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stdout, result.stderr)
        raise SystemExit("ledger_query.py --select %s exited %d" % (selector, result.returncode))
    return json.loads(result.stdout)


def whats(payload):
    return {p.get("what") or p.get("title") for p in payload["promises"]}


def project_rollups(config_path, extra=()):
    """`--projects --json` through the CLI, exactly as a skill would call it."""
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--config", str(config_path),
            "--now", NOW, "--projects", "--json", *extra,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stdout, result.stderr)
        raise SystemExit("ledger_query.py --projects exited %d" % result.returncode)
    return json.loads(result.stdout)["projects"]


def check_keyword_matching():
    """Unit-check the keyword matcher directly.

    This is the one piece of text classification that decides project
    membership, and the repo has already been burned once by keyword search
    (reference/sweep.md). The hostile cases cannot be expressed as fixture
    notes, so they are asserted against the function.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("ledger_query", SCRIPT)
    lq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lq)

    def hit(keyword, text):
        return lq.keyword_hit(lq.canonical(text), keyword)

    cases = [
        # (keyword, text, expected, why this case exists)
        ("head", "Answer the Omicron header question", False,
         "a keyword must not match inside a longer word"),
        ("header", "Answer the Omicron header question", True, "the whole word matches"),
        ("sso", "Follow up on the SSO answer", True, "matching folds case"),
        ("sso", "Answer the SSO? question", True, "punctuation is a word boundary"),
        ("tech writing", "Writing the tech spec", False,
         "a multi-word keyword is a PHRASE, not a bag of tokens"),
        ("tech writing", "Draft the tech writing update", True, "the phrase itself matches"),
        ("integration", "Maintain the integrations inventory", False,
         "no stemming: a plural is a real miss, made visible by the preview "
         "rather than guessed at"),
        (".net", "Port the .net service", True,
         "a keyword with regex metacharacters is escaped, not compiled as a pattern"),
        ("c++", "Review the c++ bindings", True, "same, for ++"),
        ("q3/q4", "Plan q3/q4 coverage", True, "same, for a slash"),
        ("", "anything at all", False, "an empty keyword matches nothing"),
        ("doc", "", False, "an empty haystack matches nothing"),
    ]
    for keyword, text, expected, why in cases:
        check(hit(keyword, text) == expected, "keyword: %s" % why)


def main():
    check_keyword_matching()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config_path, vault = build_instance(tmp)
        mtimes_before = {p: p.stat().st_mtime_ns for p in sorted(vault.rglob("*.md"))}

        # --- slipping: only real, passed hard dates ------------------------
        slipping = whats(q(config_path, "slipping"))
        check(
            "Deliver the staging redirect fix to Acme" in slipping,
            "slipping includes an overdue hard-deadline item",
        )
        check(
            "Maintain the Nu integration inventory" not in slipping,
            "slipping excludes a past SOFT date (a false overdue chase at a real person)",
        )
        check(
            {"Answer the Omicron header question", "Provide the Omicron domain list"} <= slipping,
            "slipping includes both notes that share one ticket (neither was deduped away)",
        )
        check(
            "Spec the header passthrough for Gamma" not in slipping,
            "slipping excludes ready-to-close items",
        )
        check(
            "Answer the Eta capacity question" not in slipping,
            "slipping excludes a snoozed item",
        )
        check(
            "Configure the Zeta test tenant" not in slipping,
            "slipping excludes a dismissed item with no draft",
        )
        check(
            "Provide the Mu quarterly summary" not in slipping,
            "slipping excludes a future-dated item",
        )

        # --- drifting: the dateless items date-chasing misses --------------
        drifting = whats(q(config_path, "drifting"))
        check(
            "Spec the header passthrough for Gamma" not in drifting,
            "drifting excludes ready-to-close items",
        )
        check(
            "Answer the Eta capacity question" not in drifting,
            "drifting excludes a snoozed item",
        )
        check(
            "Wait on Tau Bank for the SSO answer" not in drifting,
            "a blocked, high-stakes item untouched only 4 business days does NOT "
            "drift (the actual bug: blocked used to share the 2-day high-stakes "
            "threshold, so a note correctly parked as 'waiting on someone else' "
            "surfaced exactly as fast as something genuinely stuck on the user)",
        )
        check(
            "Wait on Upsilon Bank for the vendor contact" in drifting,
            "a blocked item DOES eventually drift once untouched >= 10 business "
            "days - the fix is patience, not silence forever",
        )

        # --- an ABSENT optional field must not take a selector down ---------
        # `stakes` is optional in the schema, so a record without it is legal and
        # `doctor` calls it clean. `drifting` subscripted it directly, so the
        # first such record crashed the selector outright - killing the whole
        # drift skill for every other item, from one missing key on one promise.
        # Every fixture promise happened to carry `stakes`, which is why the
        # suite passed while a real ledger was broken.
        for selector in SELECTORS:
            payload = q(config_path, selector)
            check(
                isinstance(payload.get("promises"), list),
                "selector %r survives a promise with no `stakes` key" % selector,
            )
        check(
            "Exercise a record whose optional `stakes` field is simply absent"
            in whats(q(config_path, "open")),
            "and that record is still served, not quietly dropped",
        )

        # --- ready-to-close matches the board's rule -----------------------
        ready = whats(q(config_path, "ready-to-close"))
        check(
            {"Spec the header passthrough for Gamma", "Review the Delta labeling recommendation"}
            <= ready,
            "ready-to-close holds both a markMetDraft and an updateDraft item",
        )
        check(
            "Spec the header passthrough for Gamma" in ready,
            "a draft outranks a dismissal in the Query, exactly as on the board",
        )

        # --- direction and context filters ---------------------------------
        waiting = whats(q(config_path, "waiting"))
        check(
            "Follow up with Beta Co on the SSO answer" in waiting,
            "waiting selects they-owe-me items",
        )
        check(
            "Deliver the staging redirect fix to Acme" not in waiting,
            "waiting excludes i-owe-them items",
        )
        scoped = q(config_path, "open", ["--context", "beta co"])
        check(
            scoped["count"] == 1 and "Beta Co" in str(whats(scoped)),
            "--context filters case-insensitively",
        )

        # --- context derived from `projects` (wikilinks) --------------------
        # The Rho note has an EMPTY customer, so its context falls back to
        # `projects: ["[[Rho Mutual]]"]`. Until this fixture existed that branch
        # had no coverage, and it returned the literal "[[Rho Mutual]]" - which
        # silently fails every exact match downstream: this filter, the board
        # chip, reconcile's roster lookup.
        rho = [
            p for p in q(config_path, "open")["promises"]
            if "Rho onboarding" in str(p.get("what") or p.get("title"))
        ]
        check(
            len(rho) == 1 and rho[0]["context"] == "Rho Mutual",
            "a context derived from a `projects` wikilink is stripped to the "
            "plain name, never left as [[...]]",
        )
        by_link = q(config_path, "open", ["--context", "Rho Mutual"])
        check(
            "Update the Rho onboarding tracker" in str(whats(by_link)),
            "and that stripped context is findable by --context",
        )
        check(
            q(config_path, "open", ["--context", "  rho   mutual "])["count"]
            == by_link["count"],
            "--context folds case and incidental whitespace (canonical())",
        )
        directed = q(config_path, "open", ["--direction", "they-owe-me"])
        check(
            all(p["direction"] == "they-owe-me" for p in directed["promises"]),
            "--direction filters",
        )

        # --- derived state is exposed, not re-derived by the caller --------
        payload = q(config_path, "open")
        sample = next(p for p in payload["promises"] if p["id"].endswith("Acme.md"))
        check(
            set(["open", "overdue", "readyToClose", "suppressed", "staleDays", "pronouns"])
            <= set(sample["derived"]),
            "each record exposes its derived state for the caller to use as-is",
        )
        check(
            not any(k.startswith("_") for k in sample),
            "private keys are not leaked into the JSON contract",
        )

        # --- what a surface must be able to report -------------------------
        check(
            {f["file"] for f in payload["parseFailures"]}
            == {"Broken frontmatter for Theta.md", "Untagged scratch note.md",
                "Summarize the Sigma rollout.md"},
            "parse failures ride along with every query",
        )
        check(
            "Draft the Xi migration summary.md"
            in {w["file"] for w in payload["frontmatterWarnings"]},
            "frontmatter warnings ride along with every query",
        )
        check(
            payload["collapsed"] and payload["collapsed"][0]["id"].startswith("ISSUE-123"),
            "cross-store collapses ride along with every query",
        )

        # --- a stored frontmatterWarning is ignored outright ---------------
        # both fixture entries carry one; neither note has anything wrong with it
        # now. A lint is a claim about the note's CURRENT content, so it is only
        # ever the live check. The stored field is deprecated: it had no writer in
        # code, and the timestamp gate that was supposed to expire it borrowed
        # `lastVerified`, which unrelated verify writes bump - so a verify seconds
        # after a note was FIXED carried a days-old warning forward as current.
        warned_files = {w["file"] for w in payload["frontmatterWarnings"]}
        check(
            "Configure the Zeta test tenant.md" not in warned_files,
            "a stored itemMeta.frontmatterWarning recorded before the note's "
            "dateModified is not shown",
        )
        check(
            "Follow up with Beta Co on the SSO answer.md" not in warned_files,
            "a stored itemMeta.frontmatterWarning recorded AFTER the note's "
            "dateModified is ALSO not shown - a fresh timestamp on a stored lint "
            "proves nothing about whether the lint still holds",
        )

        # --- projects: the rollup and both lag signals -----------------------
        rollups = {r["id"]: r for r in project_rollups(config_path)}
        check(
            rollups["upsilon"]["rollup"]["lag"] == "quiet",
            "a project whose work has not moved in the threshold goes quiet",
        )
        check(
            rollups["gamma"]["rollup"]["openCount"] == 0
            and rollups["gamma"]["rollup"]["lag"] == "quiet",
            "a project with ZERO open items still goes quiet - nothing else would "
            "ever surface it, which is the case a movement signal that required "
            "open work would miss forever",
        )
        check(
            rollups["omicron"]["rollup"]["lag"] is None
            and rollups["omicron"]["rollup"]["memberCount"] == 2,
            "a project that moved recently does not lag",
        )
        check(
            rollups["epsilon"]["rollup"]["openCount"] == 0
            and rollups["epsilon"]["rollup"]["lag"] is None,
            "a project whose last item closed TODAY is silent, not instantly "
            "reported as having nothing left",
        )
        check(
            rollups["mu"]["rollup"]["lag"] == "date-slipping"
            and rollups["mu"]["rollup"]["movementDays"] <= 2,
            "a target date closing in flags even while the work is moving",
        )
        check(
            rollups["empty"]["rollup"]["memberCount"] == 0
            and rollups["empty"]["rollup"]["lag"] is None,
            "a just-declared project with nothing tagged is silent, not lagging",
        )
        check(
            "ISSUE-321:kappa-handover" in rollups["epsilon"]["rollup"]["memberIds"],
            "an `include` id joins the project even though its context does not match",
        )
        # movement means WORK moved. `lastVerified` is when the system last
        # LOOKED, and a sweep refreshes it on everything it touches - counting it
        # would mean a swept ledger can never go quiet, so the automated pass
        # meant to catch a stalled project would be what hides it.
        gamma_member = [
            p for p in q(config_path, "all")["promises"]
            if p["id"] in rollups["gamma"]["rollup"]["memberIds"]
        ]
        check(
            gamma_member
            and str(gamma_member[0].get("lastVerified") or "")
            > rollups["gamma"]["rollup"]["lastMovement"],
            "a fresh lastVerified does NOT count as movement (its member was "
            "verified after the last real edit, and the project is still quiet)",
        )

        # --- declared rules: what a project claims, and why --------------------
        check(
            rollups["sso-work"]["rollup"]["memberCount"] == 2
            and all("keyword" in r for r in rollups["sso-work"]["rollup"]["memberReasons"].values()),
            "a keyword rule claims members, and each says which keyword claimed it",
        )
        check(
            rollups["note-probe"]["rollup"]["memberCount"] == 0
            and rollups["what-probe"]["rollup"]["memberCount"] == 1,
            "a keyword present only in a promise's `note` claims nothing, while the "
            "same promise's `what` does claim - the haystack is title+what, so "
            "membership cannot churn as a status line is rewritten",
        )
        check(
            rollups["onboarding"]["rollup"]["memberCount"] == 1
            and "Tasks/Update the Rho onboarding tracker.md"
            not in rollups["onboarding"]["rollup"]["memberIds"]
            and rollups["onboarding"]["rollup"]["excludedCount"] == 1,
            "`exclude` beats a keyword match - a correction made by hand is not "
            "overridden by a rule - and the count is reported so it has a surface",
        )
        check(
            rollups["scoped-hit"]["rollup"]["memberCount"] == 1
            and "from issues" in list(rollups["scoped-hit"]["rollup"]["memberReasons"].values())[0]
            and rollups["scoped-miss"]["rollup"]["memberCount"] == 0,
            "`sources` narrows rather than widens: the same keyword claims an item "
            "from the named source and nothing from a source it did not come from",
        )

        # --- the check-in rhythm ---------------------------------------------
        check(
            rollups["rhythm"]["rollup"]["lag"] == "due-for-check-in"
            and rollups["rhythm"]["rollup"]["nextCheckIn"] == "2026-08-08",
            "a check-in comes due on its own rhythm, independent of whether any "
            "member moved",
        )
        check(
            rollups["upsilon"]["rollup"]["lag"] == "quiet"
            and rollups["rhythm-quiet"]["rollup"]["lag"] is None,
            "a check-in rhythm REPLACES the quiet threshold: two projects share the "
            "same idle member, and only the one without a rhythm reports quiet - so "
            "the card never has to state two numbers for one silence",
        )

        # --- --project filters on the rollup's member list -------------------
        # `ISSUE-321:kappa-handover` is pinned into `epsilon` AND matches
        # `kappa`'s alias. Only one project can stamp it, so a filter keyed on
        # that stamp would return nothing for the other - while that project's
        # card visibly lists the member. Both must find it.
        for project_id in ("epsilon", "kappa"):
            members = q(config_path, "all", ["--project", project_id])
            check(
                "ISSUE-321:kappa-handover" in {p["id"] for p in members["promises"]},
                "--project %s returns a member it shares with another project"
                % project_id,
            )
        unknown = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(config_path), "--now", NOW,
             "--select", "all", "--project", "no-such-project", "--json"],
            capture_output=True, text=True,
        )
        check(
            unknown.returncode != 0 and "unknown project" in unknown.stderr,
            "--project with an undeclared id fails loudly rather than returning "
            "an empty list that reads as 'this project has no work'",
        )

        # the two off-switches, checked on a mutated copy rather than by adding
        # more permanent fixture permutations
        probe = tmp / "probe"
        shutil.copytree(tmp, probe, ignore=shutil.ignore_patterns("probe"))
        probe_state = probe / "instance" / "state.json"
        probe_config = probe / "config.json"
        raw = json.loads(probe_config.read_text())
        raw["storage"]["instancePath"] = str(probe / "instance")
        raw["storage"]["knowledgePath"] = str(probe / "vault")
        probe_config.write_text(json.dumps(raw, indent=2))
        data = json.loads(probe_state.read_text())
        for record in data["projects"]:
            if record["id"] == "upsilon":
                record["snoozedUntil"] = "2026-09-01"
            if record["id"] == "gamma":
                record["status"] = "done"
        probe_state.write_text(json.dumps(data, indent=2))
        probed = {r["id"]: r for r in project_rollups(probe_config)}
        check(
            probed["upsilon"]["rollup"]["lag"] is None
            and probed["upsilon"]["rollup"]["snoozed"],
            "a snoozed project stops lagging",
        )
        check(
            probed["gamma"]["rollup"]["lag"] is None,
            "a project marked done stops lagging (and is still returned, so a "
            "surface can render it rather than it vanishing)",
        )

        # --- a duplicate key parses cleanly but must not pass silently -----
        warned = {w["file"]: w["warning"] for w in payload["frontmatterWarnings"]}
        check(
            "Draft the Xi migration summary.md" in warned
            and "duplicate frontmatter key(s): dateModified" in warned["Draft the Xi migration summary.md"],
            "a duplicate frontmatter key is surfaced (a real YAML parser keeps the "
            "last value and discards the other, silently)",
        )
        check(
            "Draft the Xi migration summary" in whats(q(config_path, "open")),
            "the duplicate-key note still parses and still appears (a lint, not a failure)",
        )

        # --- an unsupported construct is refused, never half-read ----------
        refused = {f["file"]: f["symptom"] for f in payload["parseFailures"]}
        check(
            "block scalar (|)" in refused.get("Summarize the Sigma rollout.md", ""),
            "a construct outside the parser's subset is refused with a precise "
            "symptom, so the note is reported rather than silently misread",
        )
        check(
            "Summarize the Sigma rollout" not in whats(q(config_path, "all")),
            "a refused note produces no promise (it is reported, not guessed at)",
        )
        check(
            "Update the Rho onboarding tracker" in whats(q(config_path, "all")),
            "a note with a quoted scalar containing colons, escaped quotes and a "
            "URL fragment parses correctly",
        )

        # --- unknown selector fails loudly ---------------------------------
        bad = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(config_path), "--select", "nonsense"],
            capture_output=True, text=True,
        )
        check(bad.returncode != 0 and "unknown selector" in bad.stdout + bad.stderr,
              "an unknown selector fails loudly rather than returning nothing")

        # --- guardrail: read-only ------------------------------------------
        mtimes_after = {p: p.stat().st_mtime_ns for p in sorted(vault.rglob("*.md"))}
        check(mtimes_before == mtimes_after, "no note was written (mtimes unchanged)")
        source = SCRIPT.read_text()
        write_calls = [
            token for token in (
                '.write_text(', '.write(', '.writelines(', 'os.replace(',
                'NamedTemporaryFile', '.unlink(', '.mkdir(', 'shutil.',
                '"w"', "'w'", '"a"', "'a'",
            )
            if token in source
        ]
        check(not write_calls, "the module has no write path (found: %s)" % write_calls)

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
