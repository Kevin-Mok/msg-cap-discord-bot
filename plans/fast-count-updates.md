# Fast count and reader updates

Make daily counts and the unreacted jump respond promptly by retaining reaction results, applying live events, and keeping Discord scans outside accounting and routing locks. Edit summaries promptly and relocate them at most every five seconds for new posts.

## Context and settled decisions

Initial git status was clean on main. Work stays in this checkout without a worktree, credential change or live restart. The subsequent commit-session request authorizes scoped commits and upstream pushes. Approved brief: prompts/fast-count-updates.md. Relevant modules: bot.py, guild_bot.py, reader_jump.py, restart_recovery.py; tests and README/smoke checks travel with implementation.

- Counts and the jump both matter; fast edits retain sticky relocation. Healthy visible updates coalesce at one second; Discord pacing may extend this.
- Use existing SQLite meta storage for versioned, scoped ID-only reader cache, avoiding a quota-schema migration. Validate cache on load; offline reaction state is provisional.
- Cache membership across successful scans; direct reader-add events mark seen, removal/emoji-clear makes only that message uncertain, clear-all marks known posts unseen. No new privileged intents.
- Keep periodic missed-event reconciliation at 60 seconds, in a background task. Reconciliation may take longer under rate limits, retains completed checks, and never blocks count publication. Warm ordinary updates make no history/membership requests.
- Selection/day/channel generation and per-message mutation versions protect stale scan results. Bootstrap requires complete history before exact caught-up claims.
- Extract Dashboard into its own module to avoid expanding the already oversized bot.py. Keep compatibility for callers without an edit adapter.

## Ordered checklist

- [x] Inspect current locks, repeated reaction work, previous rate-limit incident and regression contracts.
- [x] Confirm both updates and fast/sticky summary preference with user.
- [x] Save the approved prompt and current incident evidence.
- [x] Observe defining RED tests for warm cache, targeted events, offline changes and nonblocking reader work.
- [x] Implement scoped persistent cache and race-safe event updates.
- [x] Implement tested fast dashboard edits, unchanged-write suppression and sticky throttle.
- [x] Schedule reader, recovery and dashboard work outside runtime/router locks; cancel retired tasks before store replacement/closure. Preserve reset/backfill races.
- [x] Run focused/full tests, type check and diff check; independent review and fix important findings.
- [x] Update README, smoke checks, lessons, incident knowledge and final evidence.

## Verification

Defining cases: warm reuse makes zero reads; add makes zero membership requests; removal rechecks one post with normal/burst/multiple-emoji coverage; background held fetch does not block counts/another guild; generation changes and mid-request events cannot publish stale results; restart detects offline reader changes even when aggregate counts match; failure retains progress and never claims caught up. Dashboard cases: edit at one second, replace at most five seconds only for posts, no identical writes, partial batches/missing messages recover.

Automated: .venv/bin/python -m unittest discover -s tests -p test_reader_cache.py -v; .venv/bin/python -m unittest discover -s tests -p test_dashboard_fast.py -v; .venv/bin/python -m unittest discover -s tests -v; UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx --offline pyright bot.py guild_bot.py reader_jump.py restart_recovery.py dashboard.py --pythonpath /home/kevin/coding/twitter-cap-bot/.venv/bin/python; git diff --check. Manual checks are maintained in docs/smoke-tests.md. Live activation requires an operator restart; automated timings are simulated, not live Discord benchmarks.

## Risks and rollback

REST buckets remain controlled by discord.py; do not hardcode Discord quotas. Persisted cache cannot prove offline reader membership. Reconciliation must not erase live additions/deletions or restart from already verified work after timeout. Retired tasks must not mutate a replacement controller's shared store. Rollback restores prior modules and removes only this change's cache meta key; quota data remains compatible. Keep all matching plan updates with implementation in any subsequently requested commit.

## Progress and review notes

Ruling: implement the approved compiled brief directly in the current checkout, as required by the user's no-worktree policy. The saved prompt serves as the reviewed spec; execution-mode go authorizes implementation. No separate skill-only branch/spec commit.

Prior lookup: query discord reaction count slow rate limit cache matched ext-reader-retry-progress (activation_pending); applicable evidence is the October 4 incident's repeated membership requests and interrupted-scan starvation. Query bwrap loopback Failed RTM_NEWADDR matched ext-sandbox-loopback/local-sandbox-loopback-approved-route (verified_workaround); exact pre-command initialization error and successful reviewed reads confirm applicability. Incident/knowledge recording deferred while Plan Mode prohibited writes; record now.

Checkpoint evidence: six reader-cache tests observed RED against the original code, then GREEN; four recovery live-event tests observed RED then GREEN; dashboard delegated tests observed RED then 14 GREEN. Additional 13 cache edge cases found invalid JSON version true/1.0 acceptance (RED); exact-int validation fixed it. Latest full suite: 184 tests pass, exit 0. Cached Pyright: zero errors/warnings/informations, exit 0. git diff --check: exit 0. Independent final review is underway.

Benchmark: .venv/bin/python scripts/benchmark_updates.py, exit 0. Synthetic 49 reacted posts plus two unread posts, 4ms simulated membership wait: baseline warm refresh 1 history + 1 fetch + 49 membership calls (219.456ms), baseline reader-add 1 + 1 + 50 (219.261ms); working-tree warm and reader-add both zero reads (0.013ms/0.016ms). Cold work remains 1 + 1 + 49 on both implementations. Counts/summary edit timing is separately pinned by controlled one-second/five-second clock tests. No live API or activation evidence.

Ruling: history recovery now publishes saved counts before backfill completes; this is necessary to avoid blocking publication. Tests explicitly wait for recovery before asserting repaired totals and preserve the original dedup/reset expectations.

Final review: two Important findings fixed in one pass with new defining RED-to-GREEN regressions (held-history removal/emoji-clear and completion-based cooldown). A next-tick targeted removal regression also observed RED then GREEN. Fresh suite passed 187 tests, exit 0; cached Pyright covering all changed runtime modules and benchmark reported zero errors/warnings/informations, exit 0; git diff --check passed, exit 0. No deferred minor findings. Declined-to-judge rulings: live latency remains unverified; documentation was independently reconciled by root; pre-existing quota enforcement is preserved and covered by the broader suite.

README recruiter-sync: update_in_same_change for stale five-second-only publication and foreground scan wording; repaired in this change. Install/bootstrap, wrapper flags, everyday use, stack rationale and opening recruiter hook are grounded in README, scripts, requirements and actual --help output. Benchmark flags also verified using --help. No tracked configuration edits: refresh-config is not applicable.

Handoff: use the saved prompt at prompts/fast-count-updates.md with this plan. Automated commands above and docs/smoke-tests.md contain the exact reusable verification. Commit subject: perf: cache reader reactions and decouple count updates. Commit-session now authorizes shipping this plan, prompt, tests and documentation in the implementation commit. Activation: stop the current bot with Ctrl+C and run ./scripts/run.sh once; do not run a second process for the token. No sudo.

Learning record: reviewed report SHA-256 e20c6026f8664c033c118df292e2d6064251176700dc233ff05adb458f9d3aa6 registered with ext-reader-event-cache-latency (activation_pending, code evidence) and ext-sandbox-loopback (verified_workaround). Scoped tracked updates: /home/kevin/linux-config/dot_agents/skills/postmortem-memory/sources.json plus references/operational-drift.md and references/execution-environments.md; captured pre-existing dirty status and preserved unrelated entries. Required check --postmortem /home/kevin/coding/twitter-cap-bot/docs/postmortem/2026-10-06-count-update-latency.md passed, exit 0, no errors/missing sources/changed hashes/unregistered aliases. Installed copies untouched.

Session shipping: scope helper returned unsafe because nested tool writes were not detected (no successful repo-writing actions detected). Use the captured clean bot baseline and directly observed edits for all 18 bot files. In linux-config, stage only the directly written reader-cache finding/report, the sandbox source alias, and the new operational-drift section; exclude all pre-existing dirty hunks. Session ID: 01a11364-e3d8-7b10-a0dd-f10f8b6d2f86. Both repositories use main -> origin/main. Fresh shipping suite: 187 tests passed; Pyright: zero errors/warnings/informations. README gate: bot coverage/CLI/source manually verified; canonical dotfiles gate returned pass_no_change before staging. Isolated staged knowledge check passed with zero errors, changed hashes, missing sources or unregistered aliases; only the three intended additions are staged. Baseline for repeatable before/after comparison: 40bc537f024a0b20fb37e0771da41b68fbefe1dd; use .venv/bin/python scripts/benchmark_updates.py --baseline 40bc537f024a0b20fb37e0771da41b68fbefe1dd after shipping. Runtime activation remains pending.
