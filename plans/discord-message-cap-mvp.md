# Standalone Discord daily cap MVP

## Goal and defaults
Build a configure-once local bot within one hour. One runtime Python file, discord.py only, SQLite persistence. One monitored text channel, cap 50, America/Toronto calendar days. Random replacement after the cap, sent counts never refunded, sticky batch refreshed at most every five seconds. No Red, backfill, hosting, commits, or pushes.

## Atomic implementation checklist
- [x] Read workspace and applicable guidance. Workspace initially empty, not a Git repository; no pre-existing tracked changes.
- [x] Write defining tests and observe RED: 19 tests failed because standalone implementation was absent.
- [x] Implement validated hidden-token setup, owner-only config, root-anchored setup/run wrappers.
- [x] Implement serialized counting, current-day deduplication, random replacement, raw deletion accounting, SQLite restart state.
- [x] Implement coalesced sticky batches, persisted status cleanup, midnight reset, minimal Discord intents.
- [x] Run full automated suite, offline configuration check, dependency/runtime import and shell checks.
- [x] Review runtime adapter, permissions, shutdown, and persistent state with independent reviewer.
- [x] Finalize README, smoke tests, accepted Cursor prompt, exact verification evidence and limitations.

## Interfaces and data flow
`python bot.py --setup [--cap N] [--config PATH]` initializes or updates settings; blank keeps existing values. `python bot.py [--config PATH]` runs. `--check` validates configuration/database offline. Config path's parent owns data.sqlite3. SQLite schema version 1 stores counts, dedup/retained IDs, scope, status IDs. A channel/timezone/day scope change prunes quota state but does not touch human Discord messages.

## Verification
`.venv/bin/python -m unittest discover -s tests -v`; `bash -n scripts/setup.sh scripts/run.sh`; compile runtime/tests; install requirements into .venv and verify the real Discord client adapter offline. CLI checks use temporary credentials/config only. Live smoke tests are in docs/smoke-tests.md; require a real token and test channel.

## Risks and rollback
Single-process MVP. No message history scans. Messages missed offline are not counted; offline deletions can leave stale retained counts until selected. Discord HTTP deletion and local SQLite updates are not atomic across abrupt termination. Failed deletes can leave more than cap visible and do not refund sent counts. Stop the process to roll back moderation; configuration/data remain intact. Restore bot code with matching schema for restart. A channel change leaves the old bot status for manual cleanup, without deleting in a different channel. SQLite work is tiny synchronous transactions in the event loop, suitable for this MVP rather than very high traffic.

## Review notes
Independent read-only review found an Important network/worker recovery gap, plus schema-check and wrapper-doc inconsistencies. All were fixed; network recovery, timeout translation, failed-worker shutdown, raw-delete DB failure, and schema mismatch have RED-to-GREEN regressions. Pyright also identified pre-ready optional channel access; regression added and guards verified. No deferred implementation findings.

Fresh evidence:
- `.venv/bin/python -m unittest discover -s tests -v`: 30 tests passed, including actual discord.py client integration without network login. Defining core suite was RED before implementation; recovery and schema regressions were RED before fixes.
- `UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx pyright bot.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python`: 0 errors, 0 warnings.
- `bash -n scripts/setup.sh scripts/run.sh`: exit 0.
- `.venv/bin/python -m compileall -q bot.py tests`: exit 0.
- `.venv/bin/python -m pip check`: no broken requirements; installed discord.py 2.7.1.
- Real `./scripts/setup.sh --config /tmp/messagecap-smoke/config.json --cap 3` completed through a PTY with hidden dummy token; `./scripts/run.sh --config /tmp/messagecap-smoke/config.json --check` reported channel 123, cap 3, America/Toronto. Config/database both mode 0600. No real token read, stored, or used.
- Tests emit the upstream discord.py audioop deprecation warning on Python 3.12 and occasional asyncio debug slow-callback notices; neither is a failure.

Live Discord testing remains unverified because no real token/test-channel configuration was supplied. See docs/smoke-tests.md. Single-process, missed-offline-event, API/SQLite atomicity and failed-delete limits are accepted MVP constraints, not verified production guarantees. README and accepted prompt saved together with implementation. Suggested commit: `feat: add standalone Discord daily message cap bot`. No Git repository was initialized; no commit/push/deployment performed.
