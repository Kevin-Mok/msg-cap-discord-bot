# Engineering lessons

## 2026-10-02 — REST transport failures and persistent-state checks
- discord.py can propagate OSError/TimeoutError and aiohttp transport failures in addition to HTTPException. Normalize these at the REST boundary so a transient failure cannot permanently terminate the sticky-counter/midnight worker. Keep a retry-and-recovery regression and ensure a failed worker cannot block shutdown.
- A database schema version alone does not validate the database. Check expected columns, integrity, and persisted counter/ID consistency before reporting a successful offline check.
- discord.py exposes cached_messages as a sequence proxy. Verify emptiness through the public sequence contract rather than equality with a list.


## 2026-10-02 — Confirmations and SQLite migration boundaries
- Recheck expiring confirmation state and current permissions inside the same lock as mutation, after any queued/network wait; checking before lock acquisition can authorize stale actions.
- SQLite's Python connection context does not begin DDL-only transactions. Use explicit BEGIN for schema migration and validate before COMMIT; verify rejection rolls back schema version and columns as well as records.
- SQLite affinity does not guarantee numeric IDs. Validate stored ID types explicitly rather than relying on comparisons with zero.
- Report old/new values captured by the locked mutation; pre-lock reads can produce incorrect moderator feedback.

## 2026-10-02 — Recoverable channel onboarding
- Channel access failure must leave the Gateway online for mention-based setup. Route setup before the configured-channel filter, validate permissions before persistence, and cancel terminal readers without executor threads. Serialize recovery with message and dashboard work.

## 2026-10-03 — Direct links and restart history
- A public Discord URL button needs a selected reader known before clicking. Rebuild dependent reader/recovery objects when replacing a tracker; invalidate links at local midnight and discard scans if the selected reader changes during an await.
- Restart backfill must merge a complete snapshot atomically, preserve saved sent totals and reset windows, and deduplicate gateway events. Exclude setup/sync requests just as live counting does. Discord history cannot recover messages created and deleted entirely offline.

## 2026-10-03 — Reply preservation and independent fixtures
- SaucyBot reply arrival must preserve the human source and tweet URL; quota deletion remains per author for humans and SaucyBot. Reader fixtures should use explicit synthetic account IDs rather than a constant owned by an unrelated cleanup feature.

## 2026-10-04 — Bounded scans must retain progress
- A timeout around a multi-request Discord scan can starve forever if retries restart from the same reacted posts. Retain completed checks across incomplete attempts, invalidate on reader/source/day/reaction changes, and clear on success for periodic reconciliation. Log exception type and progress so timeout and HTTP failures are distinguishable.

## 2026-10-06 — Event-driven cache and background publication
- Preserve confirmed reader reactions across successful warm updates; invalidate only affected posts. Normal/super/multiple emoji removals require a membership check, while reader additions can apply directly. Persisted state is provisional after offline gaps; use generation and per-message versions to reject stale network results.
- Keep reaction/history reads and status publication outside Gateway/accounting locks. Merge complete recovery snapshots atomically with deletion tombstones, live-post protection and reset-window checks. Controller tasks must be cancelled before scope replacement or shared SQLite closure.
- Separate one-second summary edits from five-second post-driven sticky relocation and suppress identical payloads. Benchmark read counts with synthetic data; offline evidence never proves live activation.
