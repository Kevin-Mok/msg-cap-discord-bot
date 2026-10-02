# One monitored channel per Discord server

- [x] Define failing tests for two-server setup, same-user counter/cap isolation, restart persistence, legacy import and command authorization.
- [x] Add one Gateway router with per-guild controllers/stores under ignored guild_data/. Reuse existing tested accounting; no extra network connection/dependency.
- [x] Register /cap_channel channel:#channel per guild and support @bot channel here before slash discovery. Require Manage Server/Admin, same-guild target and bot permissions.
- [x] Import existing state only into the legacy channel's verified guild. Keep failed guild setup from blocking other guilds. Guard retired state when switching channels.
- [x] Update README and smoke checks; run full regressions, type checks and review.

Decisions: one channel and daily default per guild. Global config retains login token and initial defaults; per-guild config/database are owner-only and ignored. A channel switch resets only that guild's daily scope; no old messages deleted. Existing local database is retained as legacy backup. The user subsequently authorized commit-dirty publication to origin/main.

## Verification and review

Defining seven-guild test suite initially failed because the router was absent. Final suite: `.venv/bin/python -m unittest discover -s tests -q` — 95 tests passed, including 16 guild tests covering same-user isolation, default caps, resets, raw deletions, restart, one-time import, setup permissions, retained /cap_channel during sync, and failed replacement rollback. `uvx pyright bot.py guild_bot.py --pythonpath .venv/bin/python` — zero errors/warnings (run with the absolute interpreter path and temporary cache dirs). Compileall, Bash syntax, and git diff --check pass.

Independent review reproduced a replacement-construction failure, then verified the fix both before and after Store.scope mutation: old config, database rows and active tracker survive, and subsequent counting works. The incident record documents the failure and fix. README and smoke checks describe the per-server setup, persistence and upgrade path. No live bot process or credentials were changed during implementation; real two-server smoke test remains manual.

Rollback: stop the process and restore the previous release plus the pre-upgrade backup. The legacy data.sqlite3 is retained, but does not contain messages counted after migration. Preserve guild_data before rollback. This follow-up is included in the authorized commit and push.

Suggested commit: `feat: isolate message caps and channel setup per guild`
Cursor handoff: Read this plan and docs/smoke-tests.md; run unittest discovery and pyright above, then follow the Multiple servers and channel setup smoke checks in two test servers. Do not expose credentials or mark live tests passed without observing the results.

Commit gate: fresh 95-test suite, Pyright, compileall and Bash syntax passed. README audit passed after clarifying per-server command registration. Matching plan, incident record and smoke tests ship with the implementation; live two-server smoke remains pending.
