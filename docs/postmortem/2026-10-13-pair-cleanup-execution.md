# Pair cleanup execution environment

This report records local execution problems encountered while implementing tweet-pair cleanup. Repository behavior was verified through the approved execution route; the default sandbox remains unavailable.

Date: 2026-10-13. Status: verified workaround; host sandbox unresolved.

Symptom and impact: two initial read-only commands failed before execution with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. The read-only reviewer observed the same startup failure. No repository command body ran. Approved scoped escalation subsequently read files and ran the tests successfully.

Lookup: searched `bwrap loopback Failed RTM_NEWADDR` in canonical postmortem-memory. Execution-environment guidance covers exactly this pre-execution failure and recommends approved scoped alternate execution; applicable based on identical failures across independent reads. This workaround does not fix the host sandbox.

Additional diagnostic correction: a ledger inspection assumed a separate `findings.json`; FileNotFoundError showed findings are embedded in `sources.json`. Existing source data was read successfully and remained unchanged. Inspect declared keys before opening inferred companion files. During intentional RED development, a fixture used `self.fail` for a set and shadowed unittest's assertion method; renaming it to `failed_ids` restored expected assertion-level RED. No production state was involved.

Resolution and evidence: approved execution completed scoped file edits, three isolated cleanup demos, and all 209 unittest cases (exit 0). Compileall and whitespace validation passed. The demos confirmed unmatched originals delete first, complete pairs delete together when necessary, and exempt counterparts survive. Live Discord activation remains pending restart and manual smoke checks.

Follow-up: retain the host-sandbox limitation; do not broaden host permissions. Canonical incident learning records this as no new reusable learning beyond existing sandbox and inspection guidance.
