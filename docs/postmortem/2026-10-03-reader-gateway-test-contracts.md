# Existing gateway assertions lagged the new reader feature

- Date: 2026-10-03.
- Symptom: the combined suite ran 134 tests with two failures: the exact intent bitmask expected only guild/messages, and manual sync expected seven commands.
- Impact: final regression verification was blocked; the other 132 tests passed. No live bot was changed.
- Evidence: expected bitmask 513 versus actual 1537, and expected seven commands versus actual eight.
- Root cause: the new feature intentionally adds the ordinary guild-reaction intent and `/cap_reader`; old exact-contract assertions were not updated with these requirements.
- Resolution: update the exact intent expectation to include only guild reactions in addition to the existing intents, and require `/cap_reader` in the eight-command registration. Privileged intents remain off.
- Status: resolved. The final suite passed 136 tests, including the exact intent and eight-command assertions plus guild reaction routing. Pyright reported zero errors/warnings; all commands exited 0. See [verification](../../plans/unreacted-tweet-jump.md).
- Follow-up: include existing registration and intent expectations in feature-scope reviews.
