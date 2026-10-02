# Count other bot accounts

- [x] RED: bot targets accepted; other bot messages counted and capped; own messages excluded.
- [x] Allow bot members in cap/status/reset commands, excluding this bot itself. Keep webhook messages excluded and bootstrap control commands human-only.
- [x] Update README and smoke checks; run full regression suite and type checks.

No new dependency/config. Existing bot messages are not backfilled. Live verification uses a second bot in the configured channel.

Verification: defining tests failed on bot-target rejection and missing bot counters before implementation. Full unittest discovery now passes 79 tests. Pyright: zero errors/warnings. Compileall passes. Coverage includes over-cap deletion of another bot’s messages, own-message and own-target exclusion, webhook exclusion, and human-only bootstrap handling. README and grouped smoke checks updated. Live bot-message test remains pending.

Suggested commit: `feat: support message caps for bot accounts`
Cursor handoff: Read this plan and docs/smoke-tests.md; run `.venv/bin/python -m unittest discover -s tests -q`, then perform the documented OtherBot cap-three smoke check without exposing credentials. Record actual live outcomes only.
