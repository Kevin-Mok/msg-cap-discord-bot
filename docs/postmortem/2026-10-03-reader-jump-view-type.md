# Optional jump view rejected by Discord send type contract

- Date: 2026-10-03.
- Symptom and evidence: Pyright reported two errors at `TextChannel.send`: `View | None` is not accepted for the `view` argument.
- Impact: runtime checks for the jump passed, but the new summary adapter did not satisfy the installed discord.py public type contract. No live bot was changed.
- Root cause: the helper returns `None` when no reader is selected; the send API expects the argument to be omitted in that case.
- Resolution: send without the view argument when no reader is configured; pass a concrete View otherwise.
- Status: resolved.
- Verification: the final full suite passed 136 tests; Pyright reported zero errors/warnings, both exit 0. Exact commands are in [the plan](../../plans/unreacted-tweet-jump.md).
- Follow-up: preserve both reader-selected and reader-disabled coverage.
