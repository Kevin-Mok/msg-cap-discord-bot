Add useful Discord slash commands to the existing standalone bot in /home/kevin/coding/twitter-cap-bot. Follow active repository instructions and preserve the one-file bot.py runtime, discord.py-only dependency, configure-once token storage, SQLite persistence, and existing moderation behavior. No Red, dashboard, extra infrastructure, or commit/push/deployment. Keep this scoped to the original one-hour MVP budget; prioritize the working command set over extras.

Read bot.py, tests, README, the active plan, and applicable lessons before changing code. Use discord.py's built-in app_commands and UI buttons, not another slash-command library.

Command set:
- /cap_user user limit: moderator sets a persistent personal daily cap for a human member in the monitored channel. Positive integer; show previous and new effective cap. Do not reset their count or delete messages immediately.
- /cap_default limit: moderator changes the channel's fallback daily cap immediately and saves it in the existing configuration cap field. Personal overrides remain unchanged.
- /cap_clear user: moderator removes a personal override and restores the channel default. Clearly report a no-op if there was no override.
- /cap_status user?: anyone can privately inspect their own status by default or a selected member. Show monitored channel, effective cap and its source, sent/retained counts, remaining allowance, accounting-window label, timezone, and next local-midnight reset. Zero remaining means subsequent messages trigger random replacement, not that Discord prevents sending.
- /cap_reset user?: moderator starts fresh accounting for the selected user; omitting user resets the monitored channel's current accounting. Both scopes require an ephemeral Confirm/Cancel view explaining the target and effect before mutation.
- /cap_help: anyone gets a concise private command guide with examples, random-replacement semantics, reset meaning, and the permission needed for moderator commands.

Reset semantics:
- Reset counters and deletion eligibility for the chosen scope, leaving existing Discord messages untouched. Pre-reset messages remain deduplicated but are excluded from the new accounting window and future deletion candidates.
- Preserve caps, personal overrides, token, channel, and timezone. Other users are unaffected by a user reset.
- After a manual reset, label counters as 'since reset' rather than falsely presenting them as the complete day's total. The next local midnight resumes normal daily accounting.
- Confirmation is usable only by its requester, expires after 30 seconds, and cannot execute twice. Cancel/timeout performs no mutation. Recheck permissions and day/window at confirmation; if the accounting day changed, require a fresh reset request.

Discord UX and registration:
- Commands work only in the monitored guild text channel. Give an actionable private response elsewhere; reject DMs.
- Use native member-picker and integer options with short descriptions, readable defaults, and explicit validation. Reject bot targets and unsupported selections.
- Moderator commands require effective Manage Messages permission in the monitored channel, or Administrator. Set discovery defaults and enforce authorization at runtime; do not rely on Discord visibility alone. Status/help remain available to ordinary members.
- Use ephemeral responses for all command feedback, disable mentions, and report old/new values and where the change applies. No public command-response clutter.
- Acknowledge or defer before potentially slow work so requests do not display 'interaction failed'. Provide short actionable errors without tracebacks, secrets, or raw internals.
- Register commands for the configured channel's guild and sync once after valid channel resolution per process. Reconnects must not repeatedly sync or create duplicate workers. Log registration failure clearly; do not pretend commands are available.
- Update invite instructions for bot/application-command authorization. Preserve counting without Message Content intent.
- Successful mutations invalidate the sticky display and refresh through its existing five-second throttle.

Persistence and correctness:
- Per-user overrides survive restart and midnight; retain them separately from pruned daily counters. Reset windows and deduplication survive restart until midnight.
- Default precedence is personal override, then the existing configured channel cap. CLI setup and slash default changes must share that same source of truth.
- Serialize mutations with incoming messages and rollover. Lowering a cap causes no immediate or bulk deletion; subsequent over-cap messages still trigger exactly one same-user/window random deletion.
- Migrate existing version-1 SQLite data non-destructively if needed. Preserve counts/status IDs and extend schema validation consistently; do not weaken checks to permit invalid data.

Verification and delivery:
Start with a short numbered checklist and an atomic plan. Write defining tests first, observe expected RED, then implement and verify GREEN. Cover actual registered command names/options, authorization and wrong-channel/DM rejection, overrides/default precedence, restart/midnight persistence, status/no-op UX, reset isolation and deduplication, confirmation ownership/cancel/timeout/replay, rollover during confirmation, interactions acknowledged promptly, sync-once reconnect behavior, and v1 migration. Keep existing regressions green.
Run .venv/bin/python -m unittest discover -s tests -v, relevant type checking, shell syntax and compilation checks. Update README, docs/smoke-tests.md, and matching plan in the same change. Document exact live slash-command checks, permissions, and expected responses. Do not claim live testing without credentials.
Finish with command examples, verification evidence for each checklist item, unresolved/live checks, and a Conventional Commit suggestion.

When choosing an approach, commit to it unless new evidence contradicts it. Before delivery assess permission safety, command discoverability/feedback, persistent reset semantics, and preservation of the lightweight runtime. Make one targeted revision if needed; show only the finished deliverable plus one evidence line per dimension.
