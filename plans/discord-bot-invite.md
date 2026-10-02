# Discord bot invite flow

- [x] Reproduce missing invite guidance with four failing regressions.
- [x] Add --invite using saved credentials for read-only login and public application ID; no Gateway or quota database.
- [x] Print required-scopes/permissions invite on channel-access failure and concrete repair steps.
- [x] Update setup guidance, README, smoke checks, and incident record.
- [x] Verify 55 tests, clean type check, and live invite-only command exit 0.

No server installation or channel permission changes performed. Token stayed inside the authentication flow. User must open the invite and choose the correct server. Existing moderation/slash behavior remains covered by the regression suite.

Suggested commit: `fix: add bot invite flow to startup onboarding`.
