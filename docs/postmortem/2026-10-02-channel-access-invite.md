# Channel-access startup failure lacked an invite path

- Symptom: user startup at 2026-10-02 13:10:21 logged `Cannot access configured channel; check channel ID and permissions` and exited. Optional voice dependency warnings preceded it.
- Impact: onboarding stopped without an actionable bot invite URL. The precise Discord access cause (not invited, wrong ID, or channel permissions) is not established from this log.
- Root cause of UX gap: startup handles channel failure with a generic error and the CLI exposes no invite command.
- Resolution in progress: add an authenticated login-only --invite command with bot/application-command scopes and only required channel permissions; include invitation and channel-check guidance on startup failure.
- Verification plan: test URL parameters, startup error guidance, and CLI login-only behavior without live credentials; run full regressions and type checks.


## Resolution and verification
Added --invite through the existing run wrapper and automatic invite/re-authorization guidance on channel startup failures. Setup success output now directs the user to the invite command. The invite command uses a login-only client and never opens the quota database or starts the Gateway.

Four defining regressions failed before implementation and pass afterward. Full suite: 55 tests passed. Pyright: 0 errors/0 warnings. A live `./scripts/run.sh --invite` succeeded using the user's saved token, resolved the application ID, printed a valid server invite URL, and exited 0 without revealing the token. Installation into the server and access to the target channel still require the user to authorize/check permissions; these were not changed automatically.

Status: onboarding UX fix complete. Follow-up is the documented invite and channel-access smoke check. No optional voice dependencies are required.
