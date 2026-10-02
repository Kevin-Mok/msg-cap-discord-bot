# Channel access failure exits before repair

Symptom: user startup on 2026-10-02 reports inaccessible channel 443954787038265344 and exits. Impact: neither mention sync nor Discord configuration can run.
Evidence: on_ready catches channel access failures and calls close; on_message also excludes all messages while channel is unset. The exact remote cause (wrong ID or permissions) is not yet known.
Root cause of failed recovery: channel validation is treated as fatal rather than a recoverable setup state.
Status: implementing online recovery, terminal replacement prompt, and administrator mention setup. No token or live configuration is being changed by development tests.
Verification/next steps: regressions for staying online, validated persisted replacement, unauthorized requests, and nonblocking terminal prompt; live Discord check after restart.

During verification the full suite failed because the legacy missing-permission test required client shutdown. This is the behavior explicitly being replaced; its assertion now requires an open connection and unset channel. No counting is permitted before validation.

Resolution: inaccessible channels now leave the Gateway online with counting paused. Interactive terminal input and a Manage Server/Admin mention command validate, save and activate a replacement. Shared runtime serialization prevents competing repair and dashboard operations; terminal readers are cancelled on success/shutdown. The original remote access problem is repaired by selecting an accessible channel or correcting permissions, not by weakening permissions.

Verification: 77 automated tests pass; pyright reports zero errors/warnings; Python compilation and shell syntax pass. Live recovery remains a manual smoke check. Follow-up: run the updated bot, enter a valid ID or use @Twitter Cap channel here, then /cap_help.
