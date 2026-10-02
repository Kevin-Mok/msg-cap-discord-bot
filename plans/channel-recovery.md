# Recover inaccessible channel configuration

- [x] Reproduce fatal startup and missing Discord setup in tests.
- [x] Keep client online while unconfigured; prompt on an interactive terminal without blocking Discord or shutdown.
- [x] Accept @bot channel here (or channel ID/mention) from Manage Server/Admin in the target server; validate text channel and bot permissions before saving. Only repair while the configured channel is unavailable, avoiding active-channel migration races.
- [x] Persist replacement with existing token/cap/timezone, rebuild channel-scoped tracking, register slash commands, and cancel stale terminal input.
- [x] Update README, smoke tests, incident and lessons; run tests/type check.

Assumptions: one monitored channel; switching scope uses existing daily-state reset semantics. No new dependency or privileged intent. Invalid input stays recoverable. A valid configured channel cannot be claimed by another server. Live Discord verification is manual.

## Verification and delivery

Defining recovery tests first failed on the closed Gateway and missing setup handler. Full suite now passes 77 tests with `.venv/bin/python -m unittest discover -s tests -q`. Pyright reports 0 errors/warnings; compileall and Bash syntax checks pass. Tests cover persistence, permissions, wrong server, bad inputs, save failure, command registration failure, concurrent requests, new-channel routing, single prompt across reconnects, cancellation and reader cleanup. No live config/token was changed. Live Discord verification is still required after restarting the updated program.

README, smoke tests, incident report and engineering lesson updated together. One runtime Python file, no added dependency. Rollback restores the prior fatal channel check; saved valid configuration remains compatible.

Suggested commit: `fix: keep bot online for channel setup recovery`

Optional Cursor handoff prompt: Read this plan and docs/smoke-tests.md, rerun the full unittest suite and pyright, then verify terminal and Discord channel repair using a dedicated test bot. Preserve real tokens and existing unrelated work; record only observed live outcomes.
