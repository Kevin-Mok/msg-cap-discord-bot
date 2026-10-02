# Sandbox initialization blocked workspace commands

- Symptom: initial read-only commands failed before execution with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.
- Impact: normal sandbox command execution was unavailable; no project or user state was changed by the failed commands.
- Evidence: both initial workspace/skill reads exited 1 with the same bwrap error. Escalated read-only retries succeeded; workspace was empty and had no Git repository.
- Root cause: the command sandbox could not initialize its loopback networking in this environment; not a bot/runtime failure.
- Resolution: use explicitly scoped, approved escalated commands for this workspace. Do not read secret files from the reference project.
- Status: project work can proceed; underlying sandbox issue remains external to the project.
- Verification: escalated filesystem reads and the deliberate TDD RED test run executed normally.
- Follow-up: environment owner can repair sandbox initialization; no runtime workaround is needed in the shipped bot.
