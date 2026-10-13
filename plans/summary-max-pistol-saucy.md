# Maximum Pistol/Saucy summary

Use one summary row for the two user-selected accounts, showing the larger sent counter and the larger retained counter while retaining independent accounting and caps. Add regression coverage, implement the rendering change, and update the usage and smoke checks together.

## Scope and assumptions

- Pistol: 142822767497052161; SaucyBot: 647368715742216193 (confirmed by the user).
- Use max of existing current-day/reset message counters, not a sum or deduplicated tweet union. Existing counters include ordinary messages.
- When either account has a personal cap, show one row: take the maximum retained count independently; prefer SaucyBot's cap, otherwise use Pistol's. Include both accounts in the sent maximum even if only one has a personal cap. With neither capped, omit the pair as before.
- Leave other rows, per-author quota deletion, resets, persisted schema, server isolation, and jump behavior intact.
- A reset of either source changes only that account's input; the maximum can remain unchanged until both are reset. Mark since reset if either input was reset.
- Commit and upstream push authorized by the commit-session follow-up. No live restart or remote deployment requested. No tracked configuration changes.

## Atomic implementation

- [x] Add tests for both maximum directions, equality, absent inputs, personal-cap selection, independent deletion, resets, restart and midnight.
- [x] Observe the defining RED; change only summary rendering in bot.py.
- [x] Add a credential-free preview using the actual Tracker/render_dashboard path; update README.md and docs/smoke-tests.md.
- [x] Run full unittest discovery, compile validation, whitespace checks and three preview scenarios; review final diff.

## Risks and rollback

Max is the requested approximation and can undercount distinct streams; it is not a logical tweet union. Retained is a separate maximum, not a union; the cap is for the chosen row account. Revert the rendering and associated documentation to restore independent summary rows; no data migration is required. Pre-existing README changes and untracked prompt/incident files must be preserved.

## Initial implementation verification and review

Defining RED: seven expected assertion failures across six tests, including both maximum directions and equal counts; corrected reset timestamps and distinct fixture message IDs before GREEN. Focused GREEN: all six tests pass. Full suite: .venv/bin/python -m unittest discover -s tests -q passed 193 tests (exit 0). Compileall for bot.py, tests/test_bot.py and scripts/preview_summary.py and git diff --check passed. Three previews returned 5 sent/3 retained, 5 sent/5 retained, and 1 sent/1 retained; ASCII output passed. Pyright is unavailable in this environment; no public types or schema changed. Independent reviewer reran all 193 tests and directly verified cap clearing/fallback/omission; no correctness findings. Minor suggestion: persist cap-clear transition as a dedicated regression. README behavior and CLI options reviewed under readme-recruiter-sync; existing unrelated README content preserved. Canonical sandbox incident ledger updated with no-new-learning decision, and targeted memory check passed. Live Discord verification requires restarting the existing deployment and exercising the documented smoke checks.

## Cursor handoff

Read this plan and docs/smoke-tests.md. Preserve the user-confirmed account IDs and independent caps. Run .venv/bin/python -m unittest discover -s tests -q and the scripts/preview_summary.py scenarios; perform the live summary smoke checks after restarting the bot. Record real live outcomes separately from offline fixtures.

Suggested commit: fix: use maximum Pistol and Saucy summary counts

## Follow-up: maximum retained count

The user reported 48 sent/44 retained because the retained display used only SaucyBot. Apply max(Pistol retained, SaucyBot retained) independently from max sent. Keep cap selection and enforcement unchanged. The exact 48/44 fixture must show 48 retained; after five Pistol deletions it must show SaucyBot's 44, then 43 and 0 as remaining posts are removed, while sent stays 48.

- [x] Observe RED on the reported 48/44 discrepancy and missing/uncapped-account cases.
- [x] Update retained rendering, README, smoke checks and preview expectations.
- [x] Run full suite, previews, syntax/whitespace validation and final review.

Follow-up evidence: the exact 48/44 retained mismatch and uncapped/missing-input expectations failed before the one-line renderer change. .venv/bin/python -m unittest discover -s tests -q passed all 194 tests (exit 0). Compileall and git diff --check passed. Actual previews 48/44 and 44/48 each returned 48 sent/48 retained; 1/0 returned 1 sent/1 retained. Independent follow-up review found no correctness issues, reran all 44 test_bot.py tests successfully, and confirmed the 48/44 ASCII preview. README and smoke checks describe both maxima; tasks/lessons.md records the local shared-summary lesson. The original 5/3 preview result above is historical; the revised renderer returns 5 sent/5 retained for that input. No schema/config change or commit; activation and live Discord checks still require restarting the deployment.

## Session delivery milestone

Milestone 1 — `fix: use maximum Pistol and Saucy summary counts`: implementation, regression coverage, preview, README, smoke checks, lesson and sandbox incident are verified and ready for one focused commit on main, then a push to origin/main. Fresh pre-commit verification passed 194 tests, all three previews, and README CLI-option review. No code blockers remain; live activation still requires a deployment restart and documented Discord smoke checks. Rollback requires reverting this rendering change; no persisted data migration.

Scope: session 01a13791-e098-70c3-a6e3-2de7ad1b6953. Installed commit-session scope helper returned unsafe because it detected no writing actions through this tool runner. Direct-write fallback uses the initial clean status for bot.py, tests/test_bot.py, docs/smoke-tests.md and tasks/lessons.md, plus the observed creation of scripts/preview_summary.py, this plan and the October 13 summary sandbox incident. Include only the current session's shared-summary README hunk; leave its pre-existing outage-prompt link and the pre-existing October 7 incident/prompt uncommitted. Canonical memory ledger edits live in the separate linux-config repository and remain outside this repository's commit.
