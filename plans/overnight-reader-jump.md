# Overnight reader jump timeout repair

## Purpose and scope
Restore eventual discovery of an unreacted source post when Discord reaction requests exhaust a ten-second scan. Scope: reader_jump.py, focused tests, README, smoke checks, incident record and local lesson. No day-window, quota, runtime-process, credential or deployment changes. Initial git status was clean.

## Decisions
Keep the ten-second budget. Retain confirmed reacted message IDs only across failed attempts, clearing them after a successful scan, reader/source/day changes, or reaction invalidation. New posts do not erase completed checks. This lets retries advance despite Discord pacing while periodic completed scans still check missed reactions. Log exception type and completed progress. Maintain the existing retry cadence.

## Checklist
- [x] Inspect overnight logs and read-only live history/reactions.
- [x] Observe RED for interrupted-scan starvation and missing diagnostic cause; verify reaction invalidation and existing day-rollover regressions.
- [x] Implement bounded retry progress and diagnostic logging.
- [x] Run reader tests, full suite, type check, diff check and read-only live verification.
- [x] Reconcile documentation, postmortem, lessons and review.

## Evidence
Warnings repeated every eleven seconds from at least 21:44:43 to 00:00:09. Live Oct 3 history had 67 surviving messages and 28 source posts. First unreacted source post was 19:22:22 Toronto time, ID 1556084024466997279; several preceding reaction queries took 4.27–4.66 seconds. Oct 4 history had one message and no source posts.

## Risks and rollback
Retained results can miss an unobserved reaction removal during an incomplete scan until the next completed periodic rescan. Observed reader reaction events clear progress immediately on the next refresh. Selection changes during awaits must not leak progress into new selection. Roll back only this change; no stored schema changes. Keep the running process untouched.

## Verification and handoff
Automated: .venv/bin/python -m unittest discover -s tests -p test_reader_jump.py -v; .venv/bin/python -m unittest discover -s tests -q; UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx --offline pyright bot.py guild_bot.py reader_jump.py restart_recovery.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python; git diff --check.
Manual: restart updated bot with ./scripts/run.sh and exercise slow reacted history plus an unreacted post in a test server; eventual link must target the unreacted post. Reader reaction removal must rewind progress. Live deployment not requested. Cursor prompt: Read this plan and incident record; run automated checks and reader smoke checks, preserving the today-only window and quota behavior. Suggested commit: fix: resume interrupted unreacted tweet scans.

## Final verification and review
RED: the two interrupted-scan tests failed as expected (exit 1): five retries could not reach the target, and timeout cause was absent from logs. GREEN: the focused suite passed 25 tests before the final reader-selection regression; full final suite passed 147 tests, exit 0. Cached Pyright reported zero errors/warnings/informations, exit 0. git diff --check passed, exit 0.

Read-only live verification against October 3 history: attempt 1 timed out after ten seconds with nine reacted posts checked; attempt 2 timed out with eighteen checked; attempt 3 returned the verified unreacted 19:22:22 post after 30.64 seconds total (including two five-second pauses). Exit 0. Credentials were not printed, no Discord messages changed, and SQLite was opened read-only.

Independent review confirmed generation and local set references prevent selection changes leaking progress; added a partial-progress reader-change regression. Remaining limitation: one individually stalled request can still block progress. No persistent state/config changes, no refresh-config requirement. The existing running process has not loaded this change; stop with Ctrl+C and run ./scripts/run.sh to activate it. The subsequent commit-dirty request authorizes one commit and push of all seven related dirty files.

## Commit verification
Fresh .venv/bin/python -m unittest discover -s tests -q passed 147 tests, exit 0. Cached Pyright again reported zero errors, warnings and informations, exit 0. README recruiter-sync outcome: pass_no_change after inspecting the root README, wrapper source, requirements and actual bot.py --help output; install, daily use, flags, stack rationale and opening hook match repository behavior. Commit includes implementation, tests, README, smoke checks, lessons, incident record and this plan. Push target: main to origin/main at Kevin-Mok/msg-cap-discord-bot. Activation still requires a bot restart.
