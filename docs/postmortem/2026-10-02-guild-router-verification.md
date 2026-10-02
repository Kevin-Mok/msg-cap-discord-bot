# Guild router verification findings

During multi-guild development, 86 runtime tests passed but Pyright rejected sharing a Gateway connection state with a channel controller because discord.py parameterizes that state by the concrete Client subclass. It also rejected a replacement sync callback whose parameter name differed. No live bot state was modified.

Resolution in progress: make the shared Gateway binding explicit inside controller construction with a narrow ConnectionState type cast (controllers never connect independently), and preserve callback signatures. A review-only command also referenced nonexistent tests/test_channel.py; the actual recovery file is tests/test_recovery.py and was inspected afterward. This had no runtime impact.

Next: rerun type checks and multi-server regression tests, including connection ownership and guild-local command persistence.

The first cast named CapClient directly, but discord.py uses Self for subclass-safe state typing; the explicit binding now preserves ConnectionState[Self].

A new isolation test initially expected reset to remove a member row. Existing reset semantics deliberately retain the member with zero counters; the assertion was corrected to verify zero counts and the other guild unchanged. Review also identified rollback gaps if legacy backup or controller construction fails; setup now snapshots the target database and rolls back before leaving the previous controller active.

Final status: resolved. ConnectionState[Self] and matching callback signatures pass Pyright. Setup snapshots and restores SQLite state on construction/save failure, retires the previous controller only after success, and cleans newly created stores after failed migration. Independent review verified rollback with an injected failure after real scope mutation and confirmed subsequent counting. All 95 tests pass, including 16 guild-specific regressions; compilation and shell checks pass. Live multi-server verification remains the documented follow-up.
