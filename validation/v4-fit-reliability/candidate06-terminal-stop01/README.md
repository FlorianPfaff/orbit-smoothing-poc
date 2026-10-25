# Candidate06 first validation sequence: terminal admission stop

The first candidate06 validation sequence ended with a **failed aggregate** on 25 October 2026. Four stages completed; six numerical stages and both cold full fits were never launched. This additive packet records the terminal outcome after the earlier [native-test failure publication](https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/1a82ecb6b5cba43bd6795adca7bf6acbbcfca90d/validation/v4-fit-reliability/candidate06-native-failure01/README.md). That published packet and the earlier proposal remain unchanged historical snapshots.

| Prescribed stage | Terminal outcome |
|---|---|
| Original 106 native tests | **102 passed, 4 failed**, no skips; failed gate retained |
| Correction regressions | **51 passed**, no failures or skips |
| Synthetic density refinement | Passed the unchanged saved trajectory and measurement-refinement gates |
| Synthetic pulse refinement | Passed the unchanged saved trajectory and measurement-refinement gates |
| Flight refinement | Not launched |
| Eccentric 24-hour refinement | Not launched |
| Density objective/full-prior check | Not launched |
| Pulse objective/full-prior check | Not launched |
| First original nuisance-failure replay | Not launched |
| Distinct candidate1/point012 nuisance replay | Not launched |

All four completed stages have verified empty owned-process trees with `kernel_ECHILD` cleanup receipts. Their recorded cleanup signals target tracked owned PID/start identities. They do not target the process that later caused the admission stop. This is evidence about the audited receipts, not a claim about every process on the host.

The four native-test failures remain the previously published control-environment mismatch: those unchanged fixtures expected 17 ordinary nuisance-search trials, but the production fail-fast option caused zero. They are not waived by the other passing stages. The [original failure packet](https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/1a82ecb6b5cba43bd6795adca7bf6acbbcfca90d/validation/v4-fit-reliability/candidate06-native-failure01/report.json) preserves the full diagnosis and historical evidence.

## Why the sequence stopped

Before flight refinement, the unchanged host-admission rule detected a separate pytest process, PID 72934 with start tick 1506771. Its exact command and unique output path match the preserved scientific-execution controls review: 174 mocked tests, with no native fits. The review's JUnit start was 21:34:00 UTC; the primary failure receipts were written at 21:34:15 UTC; the review's terminal receipt followed at 21:34:45 UTC. These are JUnit and receipt timestamps, not a separately instrumented admission-event clock.

The parent agent authorized the overlapping review tests while the primary sequence was active. This was our scheduling mistake. Admission correctly refused the next stage; no admission rule was weakened, and the detected process was preserved. This controller stop is distinct from both the earlier four failed test assertions and any native-fit numerical failure.

Overlapping review jobs also mean the recorded stage and end-to-end times are **not uncontended benchmark measurements**. They remain observed validation timings and cannot support a speedup claim.

## Audit and release limits

The independent terminal audit passed 133 checks: exact sequence/control/result identities, completed-stage outcomes and cleanup, the overlapping process attribution, six unlaunched stages, and both cold fits remaining unlaunched. Its receipt is [included here](evidence/terminal-audit/audit01.json), with its [archive-only source](evidence/terminal-audit/audit.py). An audit pass confirms attribution and reporting; it does not turn the failed aggregate into a correctness pass.

Neither cold fit started. Their directories contained only the prepared request and runtime-rebinding records. There is no new cold convergence, accepted covariance, flight result, objective result, nuisance replay result, release qualification or frozen-benchmark result from this stopped sequence.

A separately prepared recovery uses explicit fail-fast flag 0 for the unchanged original 106-test suite, adds the unchanged 37-case option suite, and keeps production flag 1 for the other stages and cold fits. Preparation has completed for that eleven-stage recovery; further preflight and numerical qualification are outside this packet. No results are substituted into the stopped attempt, and no passing recovery is claimed here.

## Evidence packaging

The packet adds the compact terminal records, correction JUnit, two refinement result summaries, overlapping review receipts, and independent terminal audit. The original native failure evidence is reused by its immutable commit link; source datasets, runtime inventories, raw prediction arrays and row spools remain external.

`provenance.json` records exact original locations and hashes for copied files. `external-artifacts.json` records the audit's remaining input pins and the immutable prior publication. `artifact-manifest.json` pins the packet itself. Publication verification checks these copies and bounded claims; it executes no scientific or archived controller code.

This static evidence packet grants no scientific acceptance or release authority. Publication verification and review receipts, when completed, are recorded separately. Publication target: existing [draft PR #9](https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9).
