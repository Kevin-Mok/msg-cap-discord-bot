# Count-update latency investigation — 2026-10-06

## Symptom and impact

User reports slow daily counts and unreacted-jump advancement, requesting caching without recurring Discord rate-limit failures. The dashboard awaits a reader scan allowing 120 seconds while server/runtime routing locks are held. Completed scans discard confirmed reacted IDs, causing repeated membership reads.

## Evidence and current status

Initial git status was clean on main. Source inspection confirms Dashboard.prepare awaits ReaderJump.refresh; guild refreshes run sequentially inside guild locks. The October 4 incident measured individual reaction-query waits of 4.27–4.66 seconds and required progress preservation. No live API, credential, runtime or user-message change has been made. Implementation and defining reproductions are in progress.

Four initial read commands failed before executing with bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted. Reviewed require_escalated read-only commands succeeded (exit 0). An exploratory agent lookup named nonexistent tests/test_core.py; subsequent reads use discovered paths. No repo state was changed by those diagnostic failures.

Lookup: discord reaction count slow rate limit cache matched ext-reader-retry-progress, activation_pending; relevant source establishes prior timeout starvation, not this change's correctness. bwrap loopback Failed RTM_NEWADDR matched ext-sandbox-loopback and local-sandbox-loopback-approved-route, verified_workaround; identical initialization error plus successful reviewed execution confirms the scoped alternate route. Host sandbox remains unresolved. Recording was deferred during read-only Plan Mode.

## Next steps

Write defining failures, implement persistent scoped cache/event updates and nonblocking scheduling, verify rate-limit/race cases and fast sticky edits, reconcile docs and reviewed incident knowledge. Actual runtime activation will remain separate from code evidence unless explicitly performed.

## Integration verification checkpoint

Six defining reader-cache regressions failed on the original code, then passed after cache/background integration. The same discovery imported the old ReaderJumpTests class and ran 27 legacy cases; 14 failures and three errors exposed their synchronous-dashboard assumptions and missing async partial-message edit fixture. Root cause: the newly authorized background workflow returns before hydration, and edits now call the actual adapter. Update fixtures to wait on reader work explicitly and model PartialMessage.edit; keep all destination and failure assertions. This is a test-contract change, not evidence of live activation.

Reader integration follow-up: six cache tests pass, and 25/27 reader tests pass. The two held-fetch selection races correctly rejected old results but the existing background task did not schedule the new selection until the next tick. Resume once within the same worker when generation changes, retaining single-flight ownership and bounded work.

Broader checkpoint: full offline suite ran 171 tests with three legacy synchronous-worker failures and one incomplete channel fixture error. Cached Pyright found two nullable-reader arguments and one nullable scope access. Defining recovery tests passed 4/4 after observing RED: snapshots now merge outside network waits and preserve live sends/deletes/resets. Resolve fixture contracts without weakening destination/count assertions; capture narrowed reader/scope types before awaits.

## Current resolution and evidence

Persistent reader state and targeted events replace repeated foreground checks. Controller-owned single-flight jobs keep scans/status writes outside routing locks. Recovery reads without the tracker lock, then atomically merges a complete snapshot with tombstones/live-ID protection/reset guards. Fast summary edits are independent from sticky relocation.

Latest offline suite passed 184 tests, exit 0; cached Pyright zero issues, exit 0; git diff --check exit 0. Six cache RED tests and four recovery RED tests preceded GREEN; 14 dashboard tests passed after defining RED. Thirteen independent edge tests caught JSON cache versions true and 1.0 being accepted; exact-int validation corrected them.

Offline benchmark (49 reacted plus two unread posts, 4ms simulated waits): baseline warm update used 51 reads and reader-add 52 reads, both about 219ms; working tree used zero reads in both (0.013/0.016ms). Cold scans retain the same necessary work. This is synthetic code evidence; live Discord latency and runtime activation are not verified. Independent review remains underway.

## Independent review

Fresh read-only review identified two material cache issues: a removal during held history could be overwritten by a stale positive reaction snapshot because its version was captured too late; a successful scan longer than 60 seconds used its start time as cooldown and could immediately trigger another full scan. An isolated in-memory reproducer confirmed the first. Add defining tests for held-history remove/emoji-clear, completion-based cooldown and prompt targeted-removal handling before correcting them. Review found no additional material lifecycle/dashboard/recovery blocker. Live API behavior was explicitly untested; docs were being updated independently.

## Final verification and activation boundary

Both independent review findings are fixed with defining RED-to-GREEN tests: history-start mutation versions force fresh membership after intervening removal/emoji-clear; reconciliation cooldown uses successful completion time. A targeted removal also rechecks on the next one-second tick instead of inheriting a five-second retry pause.

Fresh final full suite: 187 tests pass, exit 0. Cached Pyright including the offline benchmark: zero errors, warnings and informations, exit 0. git diff --check passed, exit 0. README and smoke checks now describe fast edits, sticky relocation, background/offline reconciliation and the benchmark; CLI help and wrapper sources match documented options. No runtime restart or live API was performed; code activation remains pending an operator restart. Host sandbox startup remains unresolved, with the reviewed scoped route verified as a workaround.

Root cause is confirmed by source and executable reproductions: repeated successful scans erased positive membership checks, and shared foreground coordination awaited the scans. The replacement retains scoped membership, applies live events and performs bounded reconciliation outside routing/accounting locks. Cache and recovery race protections were tested; no quota schema change or tracked configuration change is required.
