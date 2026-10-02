Build a lightweight standalone Discord message-cap bot in /home/kevin/coding/twitter-cap-bot within 60 minutes, including setup and verification. Follow active repository instructions.

Architecture:
- One runtime file: bot.py.
- Only third-party runtime dependency: discord.py. Use standard-library sqlite3, asyncio, zoneinfo, and configuration handling.
- No Red dependency, cog system, web server, ORM, or deployment infrastructure.
- Keep tests separate from the runtime file.

Plug-and-play initialization:
- Reproduce auction-bot's configure-once experience, not its Red implementation.
- `python bot.py --setup` prompts for token, channel ID, daily cap, and timezone, then saves a local config.json with owner-only permissions.
- Hide token input. Never print tokens or include them in errors.
- Default cap to 50 and timezone to America/Toronto.
- Subsequent `python bot.py` runs load saved configuration without prompting.
- Setup reruns preserve existing settings unless explicitly changed and never reset message data.
- Gitignore config.json, the SQLite database and sidecars, .venv, and caches.
- Supply requirements.txt and a small scripts/setup.sh that creates .venv, installs dependencies, and invokes setup. Supply scripts/run.sh for startup.
- Do not read or copy auction-bot's credentials.

Behavior:
- Monitor one configured guild text channel.
- Count each human message once per local calendar day. Ignore bots, webhooks, DMs, other channels, and edits.
- Allow the first 50 messages. For every additional message, uniformly choose and delete one of that user's existing tracked messages from today, including the newest.
- Never delete other users' messages or previous-day messages.
- Sent count continues increasing after deletions; retained count reflects remaining tracked messages.
- Manual deletions reduce retained count, never sent count.
- Track only messages observed while running; document no historical backfill or offline accounting.

Sticky counter:
- Display every user who posted today:
  Alice: 53 sent · 50 retained · cap 50
- Replace the previous status batch after activity so it stays near the bottom.
- Coalesce updates to at most once every five seconds. Ignore the bot's own messages.
- Split only when Discord's message limit requires it.
- Persist status IDs for restart cleanup.
- Reset at local midnight even without activity; leave yesterday's human messages untouched.

Performance and reliability:
- Use an in-memory current-day index backed by SQLite; no history scan per message.
- Serialize channel processing and use one background refresh/reset task.
- Persist counters and message IDs across restarts; prune previous-day tracking.
- Deduplicate observed events using message IDs.
- Remove stale deletion candidates and retry selection.
- Log permission/API failures without claiming success. Respect library rate-limit handling.
- Store IDs, timestamps, and counts, not message bodies.
- Validate configuration on startup and exit with actionable instructions if invalid.

Time budget:
- 0–10 minutes: prerequisite checks, compact plan, setup scaffold, defining failing tests.
- 10–35 minutes: counting, random deletion, persistence, and sticky display.
- 35–45 minutes: regression and setup verification.
- 45–60 minutes: documentation and live smoke test if credentials are available.

Use standard-library unittest with injectable time and randomness. Test cap boundaries, user/day isolation, duplicates, edits, manual deletions, restart, midnight rollover, concurrency, stale candidates, sticky throttling, and setup reruns preserving state.

Deliver bot.py, requirements.txt, setup/run scripts, README, relevant plan, and docs/smoke-tests.md. Include Discord application creation, invite permissions/intents, and exact setup/start instructions.

Start with a short checklist. Finish with verification evidence, unresolved work, and a suggested Conventional Commit subject. Mark live testing unverified if credentials are unavailable. Do not commit, push, or deploy.

Before delivery, check cap correctness, minimal dependencies, restart safety, and setup simplicity. Make one targeted revision if needed and report evidence for each.
