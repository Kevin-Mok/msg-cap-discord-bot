# Cap empty-candidate patch context mismatch

- Symptom: a multi-file patch failed to match a README sentence and was rejected.
- Impact: the rejected patch made no changes; only the already-added failing regression test remained modified.
- Evidence: `apply_patch` returned a context mismatch. Inspection showed README called the setting a "personal cap," while the attempted context said "new cap."
- Current status: resolved; edits were applied against the inspected file contents.
- Next steps: none.

## Resolution and verification

- The empty-candidate regression failed before implementation with `retained=0` instead of `retained=1`, then passed after the tracker skipped replacement when the incoming message was the sole candidate.
- Focused checks for lone-candidate retention, ordinary random replacement, and manual deletion passed.
- `.venv/bin/python -m unittest discover -s tests -q` passed all 102 tests; `git diff --check` passed.
- Status: resolved; no live Discord messages or runtime configuration were changed.
