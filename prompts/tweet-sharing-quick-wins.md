Inspect /home/kevin/coding/twitter-cap-bot and recommend fun, useful features I can implement individually in one Astra Ultra session.

I’m the main user posting “tweets” in Discord. My wife reads them and adds reactions. Optimize for our shared experience: making posting more satisfying and reading, reacting, and revisiting posts easier.

Read the repository instructions, README, relevant plans, implementation, and tests before recommending anything. This pass is read-only: do not implement features, read credentials or private message data, create worktrees, commit, or push.

Current context to verify:
- Python, discord.py, SQLite; one monitored channel per server.
- Daily caps can randomly delete posts; SaucyBot replies can also trigger cleanup.
- Accounting survives restarts, but daily event records are cleared at rollover.
- Message bodies are not stored, Message Content intent is off, and reaction handling is not implemented.

Produce:
1. Six ranked ideas: four quick wins and two slightly larger natural next steps. For each, give the concrete experience for me or my wife, repository evidence, smallest useful version, relative effort, dependencies, and confidence that one session can finish it.
2. Explore possibilities such as reaction-based favorites, catch-up lists, favorite-post jump links, reaction summaries, and posting feedback. These are starting points; choose stronger ideas where warranted.
3. Flag meaningful tradeoffs. A reaction does not automatically mean “read.” Links can break after deletion. Preserving reacted posts changes cap behavior. Content-based digests may require new permissions or storage. Distinguish explicit choices from assumptions.
4. For the best three ideas, write separate, self-contained implementation prompts I can paste into Cursor or Codex with Astra Ultra. Each must specify the bounded MVP, command or reaction behavior, non-goals, defining tests, exact verification commands, documentation updates, and completion criteria. Handle applicable reaction removal, duplicate events, wrong users/channels, deletion, restart, and midnight cases.
5. End with the single best first task and explain its immediate benefit in two sentences.

Prefer native Discord interactions, minimal configuration, and the existing stack. Avoid external services unless the benefit clearly justifies them. Keep each implementation prompt independently usable; disclose shared prerequisites. Follow active repository instructions, protect existing dirty work, use RED-to-GREEN tests for behavior changes, and keep matching plans and documentation with implementation. Implementation prompts must not authorize commits, pushes, or live deployment.

Treat your first complete answer as a draft floor, not the submission. Before you deliver, name the single biggest weakness of the draft against the goal, then fix it. Apply this to the whole response, not just the first part. Show only the final version.
