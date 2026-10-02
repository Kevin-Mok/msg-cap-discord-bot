# Dashboard format patch context mismatch

- Symptom: an edit patch could not match the dashboard formatter after a partial patch had already changed its empty-state wording.
- Impact: no source change was made by the rejected patch; the formatter remained in its previous format.
- Evidence: `apply_patch` returned a context mismatch; inspection confirmed the old header and row formatter were intact and only the empty-state line had changed.
- Current status: resolved. The formatter patch context and stale assertions are corrected.
- Next steps: none.

## Resolution and verification

- Replaced the dashboard title and rows with a concise tweet summary that omits date, timezone, account name, and ID while preserving sent, retained, cap, and reset information.
- Updated dashboard tests, README, and smoke-test expectations.
- Focused dashboard tests passed. Initial full-suite runs identified stale assertions for regular, plural, and empty-state wording; all were updated.
- Final verification: `.venv/bin/python -m unittest discover -s tests -q` passed all 101 tests; `git diff --check` passed.
- Status: resolved; no runtime configuration or live Discord messages were changed.
