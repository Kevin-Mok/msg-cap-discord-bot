# Reader fixture depended on cleanup constant — 2026-10-03

Symptom: full unittest discovery ran 143 tests with one error: `test_midnight_is_inclusive_and_reader_own_and_service_posts_are_skipped` referenced removed `bot.REPLY_CLEANUP_BOT_ID`.
Impact: the test fixture could not construct its SaucyBot message. The reply-preservation and cap-deletion regressions passed.
Evidence: AttributeError at tests/test_reader_jump.py:100 after removal of the unused cleanup constant.
Root cause: a reader-jump fixture reused a production constant for an unrelated deleted behavior.
Resolution: use a literal synthetic SaucyBot account ID in the reader fixture; reader production behavior is unchanged.
Verification: `.venv/bin/python -m unittest discover -s tests -q` passed all 143 tests, including the previously failing reader case. Compileall and `git diff --check` passed.
Status: resolved.
Follow-up: fixtures should use explicit account IDs rather than unrelated feature constants.
