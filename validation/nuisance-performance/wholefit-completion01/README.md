# Passive whole-fit completion controls

Fixed status at **2026-10-19T09:07:18.640673+00:00**: the passive waiter was running on CPU4 (PID 20530, start ticks 1332922, boot `f7440b3b-052f-4809-8240-f8d8aea32be8`). This packet contains controls and tests, with no assessment of whole-fit outcomes. The independent audit of actual outcomes remains pending.

The existing experiment has two predeclared attempts, cache1 then cache0. The helper observes the original controller and requires terminal cleanup and post-input identity receipts before invoking the pinned checker once. It does not change the experiment, signal processes, launch native work, or publish results. A missing or unclosed attempt remains explicit. Its bounded wait does not turn an unfinished fit into a timeout or convergence result.

The [plan](controls/plan.json) and [launch](controls/launch.json) pin the helper and checker. The [author validation](author/receipt.json) and [independent helper review](independent/helper-review.json) each record 32 passing injected tests; [concrete-plan review](independent/concrete-plan-review.json) is separate. These reviews are not an independent audit of experiment outcomes.

**Timing comparison is compromised.** The pinned [clock observation](clock/observation.json) and [supervisor snapshot](clock/supervisor-snapshot.json) record a discrepancy of about 1,230.8 seconds between elapsed UTC and supervisor time; the cause is unverified. The supervisor keeps its unchanged monotonic 7,200-second limit. Compliance with a two-hour elapsed-UTC budget is not established. This pair supports no speedup conclusion or full benchmark acceptance. Numerical outcomes remain a separate question.

The source and test copies are exact. [The manifest](manifest.json) records hashes, original paths and byte-copy provenance for every payload. [The process observation](waiter-observation.json) records only bounded process metadata. The [previous protocol packet](../wholefit01-protocol/README.md) retains the experiment freeze; the [checker packet](../wholefit-checker01/index.html) documents the reviewed analysis.

No live helper log, report directory, fit output, dataset, row archive or executable was copied. Absolute paths in the receipts are historical attribution, not instructions to replay the run. This packet and helper have no release authority.
