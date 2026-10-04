# Overnight reader jump investigation — 2026-10-04

## Symptom and impact
User reported an unreacted tweet and repeated `Could not refresh unreacted tweet jump` warnings starting at 00:00:09 in channel 443954787038265344. The link can remain disabled while refresh retries.

## Evidence and current status
Initial git status was clean. Bot process started October 3 at 19:32 and remains running. The original reader refresh hid the underlying exception and retried failed scans every five seconds with a ten-second scan timeout. Investigation and code repair are complete; the running process has not been restarted.

The initial read-only commands could not start because the sandbox failed with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. Read-only checks succeeded with reviewed escalation. A later optional plan-path lookup exited 2 because one candidate did not exist; the canonical plan contract was found and read.

## Next steps
Restart the updated bot with ./scripts/run.sh after Ctrl+C, then follow the direct-jump smoke checks. Investigation, regression coverage and read-only live verification are recorded below.

## Root cause and resolution
Discord pacing caused individual reaction checks to pause for over four seconds. The full scan exceeded its ten-second budget before reaching the first unreacted post; every failed attempt restarted from midnight and repeated the same checks. TimeoutError was caught as OSError and its cause was hidden.

Retain confirmed reacted message IDs across failed attempts, clear progress on successful completion or day/selection/reaction invalidation, and include exception type, HTTP status and progress in warnings. The today-only search still intentionally excludes yesterday after midnight.

## Verification and current status
Live October 3 history contained 67 messages, 28 by SaucyBot. First unreacted source post: 19:22:22 Toronto, ID 1556084024466997279. October 4 had no source posts. Updated read-only scan progressed from nine to eighteen checked posts across two timeouts and found that exact target on attempt three in 30.64 seconds, exit 0.

Two expected RED regression failures preceded implementation. Final unittest suite passed 147 tests (exit 0); cached Pyright reported zero issues (exit 0); git diff --check passed (exit 0). Independent review verified scan generation/set isolation; partial-progress reader-change and missed-event reconciliation are covered.

Code repair verified; activation pending restart of the existing bot using ./scripts/run.sh after Ctrl+C. No runtime process, message, credential, schema or saved config was changed. A single request repeatedly exceeding ten seconds remains a limitation. The subsequent commit-dirty request authorizes committing and pushing the verified repair with its companion documentation.
