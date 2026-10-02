# Reset confirmation could become stale while queued

- Symptom: review found reset authorization/deadline was checked before waiting for the quota lock. An in-flight Discord delete can hold that lock while the 30-second window expires or moderator permissions change.
- Impact: a queued reset could mutate counters after it was no longer valid. No live Discord instance was used during development.
- Evidence: focused tests hold the tracker lock, queue confirmation, expire the deadline or revoke permission, then release the lock.
- Status: reproducer added; fix will validate deadline and current channel permissions inside the same lock as the reset mutation.
- Next steps: observe focused RED, implement locked validation, rerun full suite/type check, and record results.

## Persistence review findings
The same independent review found migration changes committed before validation and permissive SQLite comparisons accepting text IDs in the overrides table. The fix must wrap DDL, schema version and validation in an explicit transaction and check stored ID types. Regression tests verify rejected v1 migration leaves the original version/columns/data unchanged and invalid override IDs are rejected.


## Resolution
- Validation runs inside the tracker lock immediately before reset: current member roles are fetched, effective channel permissions and the original deadline are rechecked, then the accounting window is checked. Invalid/expired/revoked confirmations cannot mutate counters.
- Migration runs in one explicit SQLite transaction, including validation and schema version update. A rejected migration leaves the prior schema and records untouched.
- Override channel/user IDs require integer types; malformed stored rows fail actionably.
- Cap-clear feedback uses the previous cap returned by the locked mutation, avoiding misleading old/new values when commands queue together.
- Verification: each finding had an expected failing reproducer before its fix; final suite 51/51 passes and pyright reports 0 errors/0 warnings.
- Status: resolved in the standalone runtime. No live server was changed.
- Follow-up: run the documented live Discord command smoke checks with the user's test configuration.
