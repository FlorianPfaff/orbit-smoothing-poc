# Recovery14: eight reference checks passed

The fresh candidate04 recovery run completed on **24 October 2026 at 14:38 Europe/Berlin**. All eight numerical checks passed. The [report](index.html), [results](report.json), [CSV](summary.csv), and independent terminal audit preserve the measured outcomes and their limits. No scientific run was launched for this publication.

| Check | Result |
|---|---|
| Synthetic density refinement | Passed; maximum prediction change 7.09406e-7 of assumed noise sigma |
| Synthetic pulse refinement | Passed; maximum prediction change 2.63208e-6 of assumed noise sigma |
| Flight window refinement | Passed; maximum prediction change 0.00218926 of assumed noise sigma |
| Eccentric 24-hour refinement | Passed; maximum prediction change 7.59276e-7 of assumed noise sigma |
| Density objective and full OU prior | Passed at consecutive derivative scales 0.125 and 0.0625 |
| Pulse objective and full pulse prior | Passed at consecutive derivative scales 1 and 0.5 |
| Original nuisance replay | Strict convergence; final update 3.00185e-10 m |
| Distinct candidate1/point012 replay | Strict convergence; final update 3.77723e-10 m |

All four prediction refinements remain below the unchanged **0.01 sigma** limit. Density's larger derivative scales 1, 0.5 and 0.25 failed the directional criterion; the prescribed half-scale search retained those outcomes and passed at two consecutive finer scales. Neither the 1e-4 derivative threshold nor the scale schedule was relaxed. All **22 density and 10 pulse objective profiles** converged strictly, as did both distinct replays. None depended on numerical-floor-limited nuisance acceptance. The measured arithmetic resolution used by the derivative test is retained and is not an uncertainty bound.

The independent audit passed **359 overall checks and 381 objective checks**. Density's first passing relative error, including its empirical resolution allowance, is **9.82621e-5 against 1e-4**, so the margin is narrow. The audit recomputed weighted-row costs, full priors, finite differences and refinement metrics. The base tangent factors had been removed under the frozen retention policy; therefore the directional check uses the recorded native derivative scalar, not a second independent tangent-factor solve. See the [audit report](evidence/terminal-audit14-01/report.txt) for this distinction and the retained checker-development failures.

This is an eight-check reference-preservation result for the candidate04 native executable, SHA256 `28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d`. It does **not** certify a complete nonlinear fit, accepted orbital covariance, a speedup, the separate candidate05 executable, a finished frozen benchmark, or release readiness. The flight check is a standalone 30-minute fixed-state window. `flight_gravity_drag_v1` still omits thermal-history sensitivities, other force gradients and atmospheric event-time derivatives.

## Provenance and retained failures

The packet includes unchanged copies of the plan, freeze, launch review, terminal and per-stage receipts, objective profile receipts, source/build identities, control scripts/tests and independent audit. [source-map.json](source-map.json) maps original absolute evidence locators to portable package paths. Copied JSON content retains its historical absolute paths and original bytes. [manifest.json](manifest.json) covers every published packet file except itself. Bulky datasets, executable binaries, full trajectories and row archives remain external; publication is not a self-contained native runtime.

Candidate04 can be traced from publication commit `ffddebbe10a20e7a1033423e030deba444130052` through the archived patch to `4bc693b75b83d9e27474cb4da50a9ae6078f49a6`, followed by the candidate04 source patch and source snapshot. These patches are archival evidence; this publication does not install candidate04 changes into the PR's executable code. Reproducing the build additionally requires the exact dependencies and original inputs named in its manifests. The controls require the original environment's paths or an independently checked relocation; do not blindly execute archived launch scripts.

The workspace relocation changed canonical path spellings in two command arguments while preserving their input bytes and scientific options. The loader-cache index also changed; selected native executable and library identities were reverified. No claim of byte-identical entire runtime or command strings is made.

Earlier recovery failures remain recorded: interruptions, run12's two objective checks failing before profile evaluation because of read-only output routing, and run13's preparation-only composed-directory identity failure. Run14 re-executed all eight checks; it reused no earlier pass. All eight stage supervisors verified owned-process cleanup. Stage timing includes inventory I/O and is not a full-fit performance comparison.

The four original long regression attempts remain timeouts, as do the four separate candidate05 conditional-design diagnostics. Their audit summaries are included as context, with the full original records preserved externally. Prefix agreement does not establish completed endpoint equivalence or a whole-fit speedup.

## Next full-fit tests

The [next-test plan](evidence/next-full-fit-plan01/README.md) identifies **two existing one-hour synthetic cold full fits**, one pulse and one density, using candidate04 and their original retained-observation GNSS-only initialization. The exact requests, hashes, differing density hyperparameters, budgets and thresholds are in [plan.json](evidence/next-full-fit-plan01/plan.json). These tests need a new audited full-fit control adapter; they have not been launched or frozen for execution.

Candidate05 must pass its own qualification before four conditional-design OFF/ON whole-fit comparisons can be attributed to it. The exact 72-hour pulse and 48-hour density regressions follow only after a measured bottleneck improvement completes their original cold nuisance solve strictly. Those cases already timed out with the same candidate04 executable, so this validation result alone does not justify identical expensive reruns.

All proposed fits retain 7,200 seconds, 8 GiB process-tree RSS, one numerical thread, 32 accepted iterations and 96 trials, the existing strict convergence tests, and fresh undamped nuisance-marginalized covariance requirements. Warm starts cannot waive the cold checks. Frozen v3.1/v4 protocols, inputs, executables and outcomes remain unchanged; new results cannot replace their failed or missing slots.
