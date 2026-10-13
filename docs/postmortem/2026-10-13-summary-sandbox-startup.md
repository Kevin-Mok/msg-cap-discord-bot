# Sandbox startup failure during summary inspection

This report records the failed command launcher and the scoped workaround used to inspect the summary implementation.

- Symptom: the first read-only skill command failed before shell execution with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` (exit 1).
- Impact: default sandbox reads were unavailable; that launch changed no repository files.
- Lookup: canonical memory search for `bwrap loopback Failed RTM_NEWADDR` matched `ext-sandbox-loopback`; its execution-environments reference applies to this pre-execution error.
- Evidence: scoped approved inspection commands subsequently exited 0, including the initial Git status and source reads. Pre-existing changes: README.md, docs/postmortem/2026-10-07-saucybot-prompt-sandbox.md, and prompts/saucybot-outage-tweet-counting.md.
- Status: verified workaround; the default sandbox itself remains unresolved. No application defect was inferred from the launcher failure.
- Resolution: use individually approved scoped commands for necessary inspection.
- Learning: no new reusable learning beyond ext-sandbox-loopback. The report is registered with an explicit no-new-learning decision in canonical postmortem-memory/sources.json; the ext-sandbox-loopback guidance remains applicable.
- Next steps: account identities were confirmed and the summary change passes its six focused tests and all 193 regression tests; leave host sandbox repair to its owner.

- Bookkeeping failure: a defensive exact-format assertion rejected whole-ledger JSON serialization before the ledger write; the subsequent targeted check correctly reported an unregistered new report. The report had been updated first. Preserve raw existing ledger text and insert only the new report record, then rerun the targeted check. Lookup for ledger formatting assertion found no precise reusable remedy; this is a local formatting guard, not a bot failure.
- Bookkeeping resolution: inserted one report record while preserving all prior raw ledger text; targeted check exited 0 with no errors, new reports, or changed hashes. No additional reusable guidance was needed.
