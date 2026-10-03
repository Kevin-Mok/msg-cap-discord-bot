# Count other bot accounts

- [x] Format the sticky daily scoreboard as a concise tweet summary with sent, retained, and cap counts; omit date, timezone, display name, and account ID.
- [x] Preserve an over-cap message when it is the account's only remaining tracked message; cover this after an external deletion.

Latest verification (2026-10-02): `.venv/bin/python -m unittest discover -s tests -q` passed 102 tests, including the empty-candidate regression. `git diff --check` passed.

- [x] RED: bot targets accepted; other bot messages counted and capped; own messages excluded.
- [x] Allow bot members in cap/status/reset commands, excluding this bot itself. Keep webhook messages excluded and bootstrap control commands human-only.
- [x] Update README and smoke checks; run full regression suite and type checks.
- [x] SaucyBot replies preserve the human source message and its original tweet URL; both authors still follow separate caps.

No new dependency/config. Existing bot messages are not backfilled. Live verification uses a second bot in the configured channel.

Verification: defining tests failed on bot-target rejection and missing bot counters before implementation. Full unittest discovery now passes 79 tests. Pyright: zero errors/warnings. Compileall passes. Coverage includes over-cap deletion of another bot’s messages, own-message and own-target exclusion, webhook exclusion, and human-only bootstrap handling. README and grouped smoke checks updated. Live bot-message test remains pending.

Reply-preservation regressions verify source messages remain after SaucyBot replies. A deterministic cap regression verifies that both originals and SaucyBot posts remain eligible for ordinary same-author cap deletion. The actual Discord workflow remains a manual smoke check.

Suggested commit: `feat: support message caps for bot accounts`
Cursor handoff: Read this plan and docs/smoke-tests.md; run `.venv/bin/python -m unittest discover -s tests -q`, then perform the documented OtherBot cap-three smoke check without exposing credentials. Record actual live outcomes only.

## 2026-10-03 — Preserve originals until quota deletion

Scope: remove SaucyBot reply cleanup; preserve original message bodies/URLs in Discord. Keep existing per-author quota deletion, including SaucyBot. No configuration or schema changes.

- [x] Observe RED: both original-preservation tests fail because reply cleanup calls Discord deletion.
- [x] Remove only reply cleanup and its obsolete bot-ID constant.
- [x] Update regression coverage, README, smoke checks, and dependent feature ideas.
- [x] Run full suite and diff validation; record exact evidence.

Risk: normal cap deletion and manual deletion can still remove original links, as requested. Live verification requires restarting the bot and running the SaucyBot smoke checks. Rollback: restore the prior bot code; no persisted-data migration is involved.
Suggested commit: `fix: preserve original tweets after SaucyBot replies`
Cursor handoff: Read this plan, run `.venv/bin/python -m unittest discover -s tests -q` and `git diff --check`, then run the original-preservation and separate cap-2 checks in docs/smoke-tests.md. Record observed results; do not expose tokens.

Verification (2026-10-03): `.venv/bin/python -m unittest discover -s tests -q` passed all 143 tests; `.venv/bin/python -m compileall -q bot.py tests/test_bot.py tests/test_reader_jump.py` and `git diff --check` passed. README accuracy reviewed with readme-recruiter-sync; reply-cleanup text corrected in the same change. Live Discord checks remain pending a restart. Pyright is not installed in this environment; no public signatures or persisted types changed.
