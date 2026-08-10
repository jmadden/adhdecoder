---
name: conventional-commits
description: Generate, review, or enforce Conventional Commit messages from a diff, staged changes, a file summary, or a plain-language description of work. Use this skill whenever the user asks for a commit message, mentions committing code, runs or discusses git commit, asks to fix or reword a commit, wants a changelog-friendly history, mentions commitlint or semantic-release, or pastes a diff and asks "what should the commit say". Trigger even if the user does not say "conventional commit" explicitly.
---

# Conventional Commit Generator

Analyze a code diff, staged changes, file summary, or raw description of work, and produce exactly one high-quality commit message conforming to the Conventional Commits 1.0.0 specification, plus the house rules below.

## Output Contract

Output exactly one commit message in a plain code block. No markdown formatting, backticks, or fences inside the message itself. No commentary before or after the block unless flagging a problem (see Atomicity and Refusals).

Structure:

```
<type>[optional scope][!]: <description>

[optional body]

[optional footer(s)]
```

- One blank line between header and body, and between body and footers.
- Header limit: 72 characters (house rule; the spec itself sets no limit). Never exceed it.
- Body wraps at 72 characters.

## Step 1: Check Atomicity First

Before writing anything, decide whether the diff represents ONE logical change.

If the diff mixes unrelated concerns (e.g., a feature plus an unrelated bug fix, or a refactor plus new tests for different code), do NOT write a combined message. Instead:

1. Say the diff is not atomic.
2. List the distinct logical changes you see.
3. Propose a commit message for each, and suggest splitting (`git add -p` or separate commits).

Never produce headers like "feat: add X and fix Y". "And" in a description is a red flag.

Related changes stay together: a feature plus its own tests plus its own docs is one commit, typed by the primary change (usually `feat`).

## Step 2: Select Exactly One Type

| Type | Meaning | SemVer effect |
|---|---|---|
| `feat` | New user-facing capability | MINOR |
| `fix` | Bug fix affecting users | PATCH |
| `perf` | Performance improvement | PATCH (typically) |
| `refactor` | Code change that neither fixes a bug nor adds a feature | none |
| `docs` | Documentation only | none |
| `style` | Formatting, whitespace, semicolons; no meaning change | none |
| `test` | Adding or correcting tests | none |
| `build` | Build system or external dependencies (npm, gradle, docker) | none |
| `ci` | CI configuration and scripts (GitHub Actions, GitLab CI) | none |
| `chore` | Maintenance not touching src or test files | none |
| `revert` | Reverts a previous commit | varies |

### Type precedence for genuinely mixed-but-atomic changes

When one logical change plausibly fits multiple types, user-facing behavior wins:

`feat` > `fix` > `perf` > `refactor` > `build`/`ci` > `docs`/`style`/`test`/`chore`

Common trap: a change that alters behavior to correct wrong output is a `fix`, even if it reads like a refactor. If users can observe the difference, it is not `refactor`.

`chore` is a last resort, not a default. If the change touches source code, it is almost never `chore`.

## Step 3: Scope

- Format: a noun in parentheses after the type, e.g. `fix(auth):`.
- Derive the scope from the dominant directory, package, or module in the diff.
- If the repo has an allowed-scope list (commitlint `scope-enum`), use only those scopes.
- If no clear scope exists, OMIT the scope. Never guess or invent one.
- Scope is lowercase, no spaces. Use `-` for multiword scopes (e.g. `user-profile`).

## Step 4: Description (the header text)

- Imperative mood. Test: the description must correctly complete the sentence "If applied, this commit will ___". "add email validation" passes. "added email validation" and "adds email validation" fail.
- Lowercase first letter (proper nouns and code identifiers keep their casing).
- No trailing period.
- Be specific. Banned descriptions: "update code", "fix bug", "make changes", "improve stuff", "wip", "misc", any bare file list.
- Do not put filenames in the description unless the filename IS the subject (e.g. `docs: rewrite CONTRIBUTING.md`).

## Step 5: Body (optional)

Include a body when the change needs motivation or context. Skip it for self-explanatory one-liners.

- The body explains WHY, not what. The diff already shows what changed. Never narrate the diff ("Changed function X to return Y").
- Good body content: the problem being solved, why this approach, tradeoffs, side effects, behavior changes, migration notes.
- Wrap at 72 characters.
- Blank line required between header and body.

## Step 6: Footers (optional)

Footers use git trailer format: `Token: value` or `Token #value`. One footer per line, after a blank line following the body (or header, if no body).

Common footers:

```
Closes #123
Fixes #456
Refs: PROJ-789
Reviewed-by: Name <email>
Co-authored-by: Name <email>
```

- Multiword tokens use `-` instead of spaces (e.g. `Reviewed-by`), EXCEPT `BREAKING CHANGE`.
- HARD RULE: Never invent issue numbers, ticket IDs, or names. Only include a `Closes`, `Fixes`, or `Refs` footer if the issue reference appears in the provided diff, branch name, or user's description. If unsure, omit it.

## Step 7: Breaking Changes

Two valid mechanisms; use both together for maximum visibility:

1. `!` immediately before the colon: `feat(api)!: drop v1 endpoints`
2. A footer: `BREAKING CHANGE: <description of the break and migration path>`

Rules:

- `BREAKING CHANGE` must be uppercase. `BREAKING-CHANGE` (hyphenated) is an accepted synonym per spec.
- The footer text must state what broke AND what the consumer must do about it.
- A breaking change can accompany ANY type, not just `feat`.
- Per spec, the footer alone (without `!`) is valid; the `!` alone (without a footer) is also valid. House rule: when the break is significant, include both.

## Step 8: Reverts

```
revert: feat(api): add rate limiting

This reverts commit 676104e due to production latency regression.

Refs: 676104e
```

Header repeats the original commit's header after `revert: `. Body states the reason. Footer references the reverted SHA.

## Full Examples

Standard feature:

```
feat(auth): add email validation to registration
```

Fix with body and footer:

```
fix(reviews): handle null review list in product render

The renderer crashed with an uncaught null pointer when a product
had no reviews. Default to an empty array so the empty state
renders instead.

Fixes #482
```

Breaking change:

```
feat(api)!: drop support for v1 endpoints

BREAKING CHANGE: The /api/v1 routes have been removed. All clients
must migrate to /api/v2. See docs/migration-v2.md for the mapping
of old to new endpoints.
```

Refactor (no behavior change):

```
refactor(payments): extract retry logic into RetryPolicy class

No behavior change. Prepares for configurable backoff in the
upcoming billing work.
```

Non-atomic diff (agent flags instead of committing):

> This diff contains two unrelated changes: a new CSV export feature in `reports/` and a fix for the session timeout in `auth/`. These should be separate commits:
>
> 1. `feat(reports): add CSV export for monthly summaries`
> 2. `fix(auth): extend session timeout to honor remember-me flag`
>
> Split with `git add -p`, or tell me to proceed with one combined message anyway.

## Refusals and Edge Cases

- Empty or trivial diff (whitespace only): use `style`, or ask what the intent was if truly empty.
- Insufficient information to determine type: ask ONE clarifying question rather than guessing between `feat` and `fix`.
- User insists on a non-atomic combined commit after being warned: comply, choose the type by precedence, and mention each change in the body.
- Never fabricate: no invented ticket numbers, no invented co-authors, no invented behavior claims not evidenced by the diff or description.

## Repo Configuration Alignment

If a `commitlint.config.*`, `.commitlintrc*`, or `semantic-release` config is visible in the repo, read it and obey it. Its rules (allowed types, scope enum, header length, case rules) override the house rules above. The goal is zero CI rejections.

## Self-Check Before Output

1. One logical change? If not, did I flag it?
2. Type correct under the precedence rule?
3. Header at or under 72 chars, imperative, lowercase, no period?
4. Scope real (from the diff or scope list), or omitted?
5. Body explains why, not what?
6. Footers in trailer format, nothing invented?
7. Breaking change flagged with `!` and/or `BREAKING CHANGE:` footer?
8. Output is one plain code block, nothing inside it but the message?
