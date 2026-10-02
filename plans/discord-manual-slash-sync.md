# In-Discord slash synchronization

User clarified that synchronization must run inside Discord. Add the mention command `@Twitter Cap slash sync` (also `@Twitter Cap sync`) as a bootstrap when slash commands are absent. No CLI sync command is needed.

- [x] Write failing command-routing/permission/sync regressions.
- [x] Reuse guild-only command registration behind a shared lock. Permit Manage Server or Administrator in the monitored channel, ignore command messages for quota purposes, disable response mentions, and throttle manual requests to once per 30 seconds.
- [x] Report the actual registered command names, or an actionable authorization/network failure without claiming success.
- [x] Update README and smoke checks; run full tests, type checking, and compilation.

Message Content intent stays disabled: Discord supplies content for a message mentioning the bot. The user must restart the bot to load this handler. Live message-triggered synchronization remains a manual check.

## Verification and review

The defining six-test suite first failed because the mention handler was absent. After implementation, `.venv/bin/python -m unittest discover -s tests -q` passed all 61 tests. Pyright reported 0 errors and 0 warnings; compileall and Bash syntax checks passed. Startup and manual synchronization share one lock; permission checks precede registration, and the cooldown is reserved before network awaits. Existing startup registration and ordinary message counting regressions remain green.

README and docs/smoke-tests.md now explain the real bot mention, restart, permission, cooldown, and recovery flow. Live Discord invocation remains unverified; run the documented mention command after restarting. No dependencies or configuration changes. Rollback is removal of the mention handler and its call, restoring startup-only registration.
