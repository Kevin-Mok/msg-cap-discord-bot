# Discord slash commands

## Accepted scope
Add /cap_user, /cap_default, /cap_clear, /cap_status, /cap_reset, /cap_help to the standalone bot. Keep one runtime file and discord.py-only runtime dependency. All commands operate in the monitored text channel; management requires effective Manage Messages or Administrator. Responses are ephemeral. Reset uses requester-only Confirm/Cancel with 30-second expiry, rechecks permissions/window, and never deletes existing human messages.

## Atomic steps
- [x] Write defining tests for caps, resets, migration, command registration, permissions and confirmation lifecycle; observe RED.
- [x] Migrate SQLite v1 to v2: retained/dedup events gain active-window flag; persistent channel/user overrides and current-scope reset markers. Preserve existing counts and status IDs.
- [x] Add locked runtime cap/reset methods, config default persistence, since-reset labels and effective cap display.
- [x] Add native slash commands, guarded guild synchronization, ephemeral errors, confirmation view, and prompt acknowledgment.
- [x] Verify full suite, type checking, compilation and script syntax; independent review.
- [x] Update README/smoke checks and record exact evidence and limitations.

## Decisions
Default cap remains in config.json, shared by CLI setup and /cap_default. Overrides are scoped by channel and survive midnight. Reset marks existing events inactive (dedup retained) and starts a fresh window; old messages are neither counted nor deletion candidates. Midnight prunes all daily events/reset markers but keeps overrides. Registration occurs once after valid channel resolution, with no global sync. All mutating commands defer before acquiring the tracker lock. Invalid permissions/channel/day or repeated/expired confirmation causes no mutation.

## Acceptance
Run `.venv/bin/python -m unittest discover -s tests -v`, type checker, compilation, and shell syntax checks. Test migration of an actual v1 fixture, cap/default persistence, replay of reset IDs, midnight, per-user/channel isolation, actual registered names/options, no-op and error feedback, permission enforcement, confirmation ownership/cancel/expiry/replay, and reconnect sync-once. Manual slash tests live in docs/smoke-tests.md; real Discord remains unverified without credentials.

## Risks / rollback
Schema v2 is forward-only for this change; back up the SQLite file with the bot stopped before reverting to old code. One process, no offline backfill, API/SQLite non-atomic limitations remain. No commit, push, or deployment requested. No live secret configuration was read or created for development.


## Verification and review evidence — 2026-10-02
- Defining core tests: five expected RED failures for missing personal caps/reset APIs and v1-to-v2 migration, then GREEN.
- Defining slash tests: seven expected RED failures for missing command interface, then GREEN.
- Full suite: `.venv/bin/python -m unittest discover -s tests -v` — 51 tests passed; original 30 regressions remain green.
- Type checker: `UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx pyright bot.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python` — 0 errors, 0 warnings.
- Independent review: reset queue race, non-atomic migration validation, invalid override ID types, and stale cap-clear feedback reproduced with RED tests, fixed, and verified GREEN. No deferred findings.
- Confirmations now fetch current member roles and recheck effective channel permissions and deadline inside the quota mutation lock. Failed verification leaves counters unchanged.
- Migration now uses explicit BEGIN through DDL, data validation and version update, committing only when valid; rejected migration rolls back the version, columns and data.
- README and smoke checks explain all six commands, application-command authorization, scope/permissions, native options, private replies, reset lifecycle, and upgrade/restart behavior.
- Runtime remains one Python file; dependency list unchanged. New tests are separate from runtime.
- Live registration, deletion and UI interactions remain unverified: no live token/channel was configured or used. User can restart `./scripts/run.sh`, check registration log, and use `/cap_help` in the monitored channel.

Suggested Conventional Commit: `feat: add Discord cap management slash commands`.
Accepted paste-ready handoff: [slash command prompt](../prompts/discord-cap-slash-commands.md).
