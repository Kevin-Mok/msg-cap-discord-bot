# Unlimited cap status rendering failure

- Symptom: The initial focused slash-command test run failed when `/cap_status` rendered an exempt user with `TypeError: 'str' object is not callable`. A stale assertion also expected `/cap_clear` to restore the default. The subsequent full-suite run had one failure because the dashboard test had not assigned an explicit personal cap under the new display rule.
- Impact: Unlimited `/cap_status` replies failed, and affected regression tests encoded either a code defect or old scoreboard semantics.
- Evidence: `.venv/bin/python -m unittest discover -s tests -p 'test_slash.py' -v` initially ran 23 tests with one error and one failure; after fixes it passed all 24, including v2-to-v3 migration. The first full run had one dashboard test failure because default-only users are now hidden. Final full verification is recorded below.
- Root cause: Adjacent formatted strings were followed by a parenthesized conditional string without `+`, so Python treated the result as a call. The stale clear assertion and dashboard setup both assumed prior behavior.
- Resolution: Added string concatenation, updated the clear assertion, and gave the dashboard refresh regression an explicit personal cap.
- Verification: `.venv/bin/python -m unittest discover -s tests -v` passed all 97 tests. `UV_CACHE_DIR=/tmp/messagecap-uv-cache PYRIGHT_PYTHON_CACHE_DIR=/tmp/messagecap-pyright-cache uvx pyright bot.py guild_bot.py --pythonpath .venv/bin/python` reported zero errors, warnings, or informations. Python compilation with SyntaxWarnings as errors, Bash syntax checks, and `git diff --check` passed.
- Status: Resolved.
- Follow-up: none.
