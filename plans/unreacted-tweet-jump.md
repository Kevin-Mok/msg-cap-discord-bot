# Direct jump to today's oldest unreacted tweet

## Purpose and observable outcome

The bottom sticky summary contains a URL button that opens the oldest surviving message from today without the selected reader's reaction. Clicking opens the Discord message directly; there is no intermediate private reply. The user explicitly requested the bottom summary and a direct jump.

The user also requested accurate today counts across restarts, alongside this button. Restore saved totals and reconcile surviving offline posts without double counting or retroactive deletions.

## Context and scope

The summary is periodically replaced by `Dashboard` in `bot.py`; `guild_bot.py` routes one connection to separate server controllers. Daily quota records omit messages sent offline and reset-excluded messages, so use Discord history. Put the reader/search/view logic in a separate module to avoid expanding the already large bot module. No message bodies or new dependency are needed.

## Decisions and assumptions

- One reader per server, selected once by a moderator with `/cap_reader user:@member`. A public URL button has the same destination for everyone; the intended reader is the user's wife.
- Today uses the server's configured timezone. Search oldest first from local midnight, inclusive, across surviving posts from the explicitly selected source account (`/cap_source user:@member`, including bots). With no source selected, hide the button; never fall back to all authors. Exclude the selected reader's own messages, this bot, unrelated bots, webhooks, system messages, and setup/sync requests. Existing app behavior treats channel posts as tweets; content intent stays off.
- Any normal or super reaction by the selected reader marks the message seen. Other people's reactions do not. Removing all their reactions makes it eligible again.
- Refresh with summary activity and reaction changes, with periodic reconciliation for missed events. No eligible message means a disabled caught-up button; failed lookup means a disabled unavailable button, never a stale target presented as current.
- Persist the reader and source IDs separately from daily accounting; restart, resets, and rollover preserve the selection.

## Ordered implementation

- [x] Capture initial status and inspect summary, routing, state, and existing tests.
- [x] Define failing tests for oldest/current-day selection, reader reactions, direct button, persistence, and restart reconciliation.
- [x] Implement the reader module, moderator setup, dashboard integration, and reaction events.
- [x] Add atomic restart history reconciliation, with timezone/reset boundaries, saved-count preservation, and retries.
- [x] Run focused and full regression checks and a type check; review the final diff.
- [x] Update README and shared smoke checks; record evidence and handoff.

## Risks, protected state, and rollback

Pre-existing changes: modified README.md; untracked docs/postmortem/2026-10-03-prompt-save-sandbox-initialization.md, docs/tweet-sharing-quick-wins.md, prompts/tweet-sharing-quick-wins.md. Preserve all of them. Add only relevant README edits without overwriting earlier work. No commit, push, credentials, or running bot changes requested. No worktree. Revert this feature's code/doc changes to roll back; the optional stored reader metadata is ignored by old code. Discord updates and deletions can race a click; document refresh delay and validate before publishing. History scans must have a time budget and avoid breaking quota refresh on API failures.

## Verification and evidence

Automated: `.venv/bin/python -m unittest discover -s tests -p 'test_reader_jump.py' -v`, `.venv/bin/python -m unittest discover -s tests -p 'test_restart.py' -v`, then `.venv/bin/python -m unittest discover -s tests -v`; `UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx --offline pyright bot.py guild_bot.py reader_jump.py restart_recovery.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python`; `git diff --check`.

RED: nine defining jump tests failed because `/cap_reader` was missing. Additional expected RED/GREEN regressions cover deleting an untracked target, midnight within the throttle window, changing reader during a scan, and excluding setup/sync requests. Restart tests observed 12 initial expected RED failures, then added repaired-channel, reconnect, and command-exclusion regressions.

Final independent verification on 2026-10-03: `.venv/bin/python -m unittest discover -s tests -q` — **136 tests passed**, exit 0, including 16 jump tests, 17 restart tests, and real controller routing across two guilds. The Pyright command above reported **0 errors, 0 warnings, 0 informations**, exit 0. `git diff --check` passed, exit 0. The suite prints expected fake invite/recovery logs and asyncio slow-task notices; no failing tests remain. Initial verification issues and resolutions: [optional view type](../docs/postmortem/2026-10-03-reader-jump-view-type.md), [recovery block indentation](../docs/postmortem/2026-10-03-reader-recovery-indentation.md), and [updated intent/command contracts](../docs/postmortem/2026-10-03-reader-gateway-test-contracts.md).

Manual: restart via `./scripts/run.sh`; set `/cap_reader user:@wife`; post ordered messages today; react as the selected reader to the oldest; tap the summary button and confirm a direct jump to the next oldest. Exercise other-user reactions, unreacting, deleted targets, all caught up, restart, and another server. Live Discord verification pending.

## Review and handoff

Keep this plan with the implementation if later committed. Suggested commit: `feat: add direct unreacted tweet jump to summary`.

Independent review found and verified fixes for midnight cache invalidation, reader changes during an awaited lookup, repaired-channel wiring, and setup/sync exclusions. Final review has no unresolved correctness findings. Long histories/rate limits may exceed the reader scan's ten-second budget, leaving the button temporarily unavailable; caching is deferred until measured need. README sync outcome: updated in this change for the new command, restart recovery, and module description, preserving the pre-existing quick-wins link and established hierarchy. No live Discord check was performed.

Restart recovery fetches a complete snapshot under the accounting lock with a ten-second limit, commits once, and retries transient failures after 30 seconds. Previously saved sent totals remain authoritative for deleted posts. Messages created and deleted entirely while offline cannot be reconstructed. No schema change or configuration file change is required. Existing README work is one unrelated link at the end; all feature edits preserve that paragraph.

Cursor handoff: Read this plan, `tasks/lessons.md`, and `docs/smoke-tests.md`. Run the automated commands above and the direct-jump smoke section in a test server. Preserve pre-existing dirty docs and never report a live Discord check as passed without observing it.

## Source filter follow-up (2026-10-03)

Purpose: only jump to posts by an explicitly slash-selected account, such as SaucyBot. Reader remains a separate human account. `/cap_source` without a user clears the source and hides the button. Both settings are per server and survive restarts/reset. Bot sources are allowed; own bot, webhooks, system messages, and reader posts remain excluded. No quota or cleanup behavior changes.

Initial state: clean `git status --short`; no protected dirty files. Scope: reader module, command/help registration, defining reader and guild tests, README, smoke checks, this plan, and existing sandbox incident record. Rollback: revert this source-filter change; saved source metadata is harmless to the previous reader implementation.

- [x] Inspect current selection and persistence.
- [x] Observe RED for explicit source filtering and absent-source behavior.
- [x] Implement source persistence, strict author filter, moderator command, cache invalidation.
- [x] Verify reader/source changes during scans, clear/restart, permissions, and server isolation.
- [x] Update README and smoke checks; run full regression, type check, and diff check.

Manual: restart with `./scripts/run.sh`; `/cap_reader user:@reader`; `/cap_source user:@SaucyBot`; post human messages before SaucyBot messages, react as reader, verify direct target always belongs to SaucyBot. Clear `/cap_source` and verify the button disappears. Re-select and restart; selections persist. Live Discord checks pending.

Cursor handoff: Read this plan and source-filter smoke entries, run the commands in Verification, then exercise source selection in a test server. Suggested commit: `fix: restrict unreacted jumps to selected source`.

RED evidence: `.venv/bin/python -m unittest discover -s tests -p test_reader_jump.py -k source -v` exited 1 with two expected failures: an unset source still displayed a link, and `/cap_source` was absent. After implementation the 18 reader tests passed, exit 0.

Source-filter verification: full offline suite passed **142 tests**, exit 0; cached Pyright reported **0 errors, 0 warnings, 0 informations**, exit 0. `git diff --check` passed, exit 0. Full-suite registration-count mismatch was fixed and recorded in [the postmortem](../docs/postmortem/2026-10-03-source-command-test-contract.md). README/smoke-test skills applied: source/reader setup, nine-command registration, and clear/restart procedures now match implementation. No tracked configuration was changed; refresh-config does not apply. Live Discord validation remains pending.

Final source review: independent read-only review found no concrete bugs in filtering, persistence, per-guild wiring, clear behavior, or generation invalidation. Reader-change regression was kept independent of source changes; fresh focused verification passed 22 reader tests, exit 0.

Session commit verification: fresh `.venv/bin/python -m unittest discover -s tests -q` passed 142 tests, exit 0; the cached Pyright command above reported zero issues, exit 0; `git diff --check` passed. README recruiter-sync audit passed using script source and `bot.py --help`: opening hook and stack rationale precede setup, install/day-to-day instructions and CLI options are accurate, and the new slash command is documented.

Commit scope: session `01a103aa-5914-71e3-8424-3072a788efdd`. Installed session-scope helper returned `unsafe` (exit 0), reporting no detected shell writes or baseline. Used the skill's direct-write fallback: the conversation captured a clean pre-write status and successful edits to all ten dirty paths, including this plan, tests, README, smoke checks, and both incident docs. No pre-existing or unknown files are included. Push target is `main` → `origin/main` (`Kevin-Mok/msg-cap-discord-bot`).
