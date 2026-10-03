# Source command registration count in regression tests

- Date: 2026-10-03.
- Symptom/evidence: full offline suite ran 142 tests and failed `test_manual_sync_keeps_channel_command_and_parent_dispatcher`: expected 8 commands, observed 9.
- Impact: verification blocked by a stale expected count; source-filter reader tests passed and Pyright reported zero issues.
- Root cause: adding `/cap_source` intentionally adds one command; the guild sync regression still asserted the previous total.
- Resolution: update the registration contract to nine and explicitly verify `/cap_source` remains registered with `/cap_channel` and `/cap_reader`.
- Status: resolved.
- Verification: `.venv/bin/python -m unittest discover -s tests -q` passed all 142 tests, exit 0.
- Follow-up: update command registration counts alongside new command registration. No Discord runtime failure was observed.
