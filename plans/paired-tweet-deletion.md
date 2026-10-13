# Paired tweet deletion

Preserve complete Pistol/Saucy tweet pairs by deleting unmatched messages first; when a paired message must go, delete its matching counterpart too. Preserve per-author sent counts and existing single-message fallback.

Scope: `bot.py` integrates a focused `tweet_pairs.py` module; restart history recovers references; tests cover live pairing, recovery and failure handling. README and smoke tests describe the behavior.

Decisions: pair only account IDs 142822767497052161 and 647368715742216193 using same-channel Discord reply IDs. Both messages must remain in their current active accounting windows; explicitly exempt counterparts remain untouched. Counterpart need not be over cap. Latest user correction: prioritize Pistol originals with no surviving Saucy reply. Prefer unpaired candidates for either initiating author, then choose a complete pair if none remain; choose randomly within that pool. Delete triggering author's candidate first, then its counterpart; Discord deletion is best effort and cannot be atomic. Never fetch message bodies to infer matches. Persist only reply/source IDs in a separate validated table; clear it on daily/channel scope changes. History recovery records links without deleting anything.

- [x] Add defining tests and observe expected RED.
- [x] Implement pair persistence, candidate selection, live and recovery references.
- [x] Run focused/full regressions, review, update docs and verification evidence.

Risks: a permission/network failure between deletes can leave half a pair; fallback still enforces the triggering author's cap. Reset or exemption excludes that account's messages from paired deletion. Multiple replies to one source pair with one surviving reply at a time.
Rollback: revert source changes; the extra SQLite table is harmless to earlier versions (schema version remains 3).

Verification: full unittest discovery, compileall, whitespace checks, and offline pair demo. Live Discord activation remains pending restart and smoke checks. No commit/push requested.

Suggested commit: `feat: prefer paired tweet deletions at cap`
Cursor prompt: Read this plan and docs/smoke-tests.md. Run the automated suite, then verify matched pair cleanup, unmatched fallback and reset/exemption protections in a private Discord channel. Record actual results without exposing credentials.

Verification so far: initial pair behavior produced six assertion-level RED failures; unmatched-first correction produced three expected RED failures. All 15 focused cases pass, including adapter filtering, Store close/reopen, history ingestion, midnight, reset/exemption and partial-deletion failure. Initial full suite passed 203 tests before the priority correction; final suite pending. Newest unmatched originals are deliberately eligible for deletion to preserve existing complete pairs.

Final verification (2026-10-13): full unittest discovery passed **209 tests** in 6.101s, exit 0. Compileall and `git diff --check` passed. Independent reviewer passed all 15 pair cases and found no blocking correctness issues. Commit review confirmed the cleanup was bound to the original Store; changed it to a lambda so it closes the reopened Store. Pyright is unavailable in this environment; no type-check result is claimed.

Direct offline checks: `.venv/bin/python scripts/preview_pair_cleanup.py --scenario unmatched` reports deleted `[3]` and retained `[1, 2, 10, 11]`; `--scenario paired` reports deleted `[10, 1]`; `--scenario exempt` reports deleted `[10]`. These demos use temporary databases and never connect to Discord. Manual test plan is the Preserve Pistol/Saucy tweet pairs section in docs/smoke-tests.md. Live activation remains pending restart; no live deletes performed.

Documentation: README behavior and preview usage updated, grouped smoke checks added, execution incident recorded and canonical incident ledger check passed. Pre-existing README edits and untracked prompt/incident files preserved. No configuration changed; no refresh-config needed. Implementation turn ended without a commit; user subsequently authorized commit-session.

Cursor handoff (paste-ready): Review plans/paired-tweet-deletion.md, bot.py, tweet_pairs.py and restart_recovery.py. Run `.venv/bin/python -m unittest discover -s tests -q`, `.venv/bin/python -m compileall -q bot.py tweet_pairs.py restart_recovery.py tests/test_tweet_pairs.py scripts/preview_pair_cleanup.py`, and `git diff --check`. Run all three preview scenarios, then restart in a private Discord test channel and perform docs/smoke-tests.md's Preserve Pistol/Saucy tweet pairs checks. Confirm unmatched Pistol originals delete first, pair fallback deletes exact counterparts, exemptions/resets protect originals, and restart recovers links without retroactive deletes. Record observed live results, restore original cap settings, and preserve unrelated dirty work. Suggested commit: `feat: preserve tweet pairs during cap cleanup`.

## Delivery milestone — feat: preserve tweet pairs during cap cleanup

Session scope: `01a137a2-0d08-7be3-b80f-5995b4eca770`. Scope helper returned unsafe because it detected no successful repo writes through this execution runner. Direct-write fallback uses the pre-write Git baseline and observed source/doc/test writes. Commit includes implementation, pair tests, offline preview, this plan, smoke checks, execution incident and only the paired-cleanup README hunk. The baseline README outage-prompt addition and two pre-existing untracked prompt/incident files remain excluded. Canonical learning-ledger insertion in linux-config is outside this repository's commit scope.

README recruiter-sync review: opening hook and stack rationale precede setup; setup/day-to-day/options are documented; pair behavior and preview flags match implementation. No further README repairs required. Fresh pre-commit full suite passed all 209 tests in 5.163s, exit 0; preview help and bot help match README flags. Compileall, working/staged whitespace checks and all three previews also passed, exit 0. Pyright unavailable. Independent review found no blocking correctness concerns. Live Discord verification remains pending restart and the grouped smoke checks.

Status: implementation complete and offline verified; milestone prepared as `feat: preserve tweet pairs during cap cleanup` for main → origin/main. No implementation blocker. Delivery action: commit this milestone and push the configured upstream. Remaining work after delivery: restart and run the documented live Discord checks; pre-existing dirty work stays excluded. Rollback remains a source revert; earlier versions ignore the additional SQLite table.
