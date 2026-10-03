# Restart review file inventory named a nonexistent file

- Date: 2026-10-03.
- Symptom: A read-only `rg` command included `pyproject.toml`, which does not exist, and returned exit 2 after printing useful matches from the other paths.
- Impact: Inspection only; no application, configuration, database, or test behavior changed.
- Evidence: `rg` reported `pyproject.toml: No such file or directory (os error 2)`; project requirements are in `requirements.txt`.
- Root cause: The review assumed a Python project metadata filename before checking the repository inventory.
- Resolution and verification: Subsequent reads used existing source, test, requirements, and lesson files and exited successfully. Restart recovery's defining tests subsequently passed (12 tests at this point).
- Status: Resolved. Follow-up: use the discovered file inventory before naming optional project files in searches.

## Duplicate postmortem cleanup

During parallel review, both agents recorded the same temporary channel-repair indentation failure. The canonical record is `2026-10-03-reader-recovery-indentation.md`. Removing this agent's newly created duplicate with `apply_patch` failed with `Failed to delete file`; the tool did not expose a more specific cause. An approved escalated Python `Path.unlink()` then removed only that duplicate successfully (exit 0). No application files were changed by the cleanup. Status: resolved; use the shared canonical incident record for the indentation fix and verification.
