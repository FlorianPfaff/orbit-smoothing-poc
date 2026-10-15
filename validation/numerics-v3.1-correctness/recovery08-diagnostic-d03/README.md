# D03: bounded nuisance-model diagnosis

Sealed snapshot of analysis attempts01–03 and their independent all-row cross-check. Scientific correctness remains unresolved; later causal analysis is published separately.

D03 reproduces the first four nuisance generations of execution08's failed density point006. Both diagnostic runs stop deliberately before generation5 and record `scientific_complete: false`. They are incomplete diagnostic replays, not accepted fits. The original failed execution08 gates remain unchanged.

The original08 output, trace-off run and trace-on run agree in all 52 prescribed arithmetic-equivalence checks. The instrumented native executable is `3a113ae1a88954a33f81f6e251ecffb98a757058821568965aae11658be8e251`, generated from the unchanged source at `8e4d36f7c47d57acdb9fa30d15a6005189bbf221` plus separately pinned diagnostic instrumentation. The exact original input profile hash is `3d74ba408612e204910ad9deb81e8562e0aeb99ecd705295d0a98c1071517cce`.

| Diagnostic step | Recorded outcome |
| --- | --- |
| Build | Completed, 200.921 s |
| Trace-off | Deliberate incomplete stop, exit1, 58.958 s |
| Trace-on | Deliberate incomplete stop, exit1, 183.236 s |
| Exact equivalence | 52 checks passed |
| Owned cleanup | Verified; independent audit checked 1,853 process identities and two namespaces |

Generation4 has an undamped update of 19.6447 nm and accepts only a step multiplier of 0.00006103515625. That earlier accepted step does not imply convergence under the unchanged 10 nm nuisance threshold. The diagnostic instrumentation captures the generation4 baseline, requested joint nuisance update, full trial and zero-step trial; the complete original08 failure history continues to generation52 in its separate published report.

The completed independent Decimal reconstruction uses 110 digits and accounts for all 9,469 original objective rows: 8,064 GNSS measurement rows, 1,344 local STEC prior rows and 61 separate constraints. It retains 386 global parameters and 1,344 equation blocks. The three trace files total 4,445,392,754 bytes and remain outside Git; their exact hashes are in the result.

| Generation4 quantity | Recorded or reconstructed value |
| --- | --- |
| Native QR full-step predicted reduction | +5.55430549e-16 |
| Independent requested-step prediction | +5.55507497e-16 |
| Linear prediction from stored GNSS nuisance primitives, with actual separate-constraint changes | +5.57604925e-16 |
| Re-evaluated full-step actual reduction | -2.63093607e-14 |
| Independent versus native actual-reduction difference | -7.91834e-31 |
| Zero-step actual reduction | Exactly zero |

A separate 128-digit reconstruction independently reproduced all original-row costs and predictions; its actual-reduction difference was below 8.9e-109. It additionally checked 20 selected component rows. The 1e-90 arithmetic agreement tolerance is diagnostic only and does not change an estimator gate.

The requested linear step predicts a decrease, while re-evaluation increases the objective on these exact rows. The component reconstruction places the principal discrepancy in the distance/receiver-clock contribution relative to the local model. This does not uniquely identify the cause: the clock-coefficient approximation, captured query arithmetic and finite light-time iteration still require separate examination. It is not evidence that changing a threshold would be valid, nor a convergence, covariance or orbit-accuracy result.

All preceding failures remain visible. Preparation01 failed before a plan or native launch because a literal `Path.glob` missed an alias whose target exists only inside the namespace; the separately versioned02 preparer enumerates and verifies those aliases. Analysis01 failed before parsing under Python3.10. Analysis02 used the pinned Python3.11 interpreter but failed its native/precise-row consistency check. The corrected analyzer explicitly models the recorded 64-bit-significand addition followed by the 53-bit-significand cast; analysis03 completed on the same immutable trace. Failed independent-audit and transfer schema assumptions are also retained. No estimator, physical input, prior, weight or acceptance threshold changed during these analyses.

The package preserves controls, tests, installation/build/source/native identities, the diagnostic boundary sentinels, equivalence evidence, analysis invocations and independent reviews. Paths are tokenized for publication; original and published hashes are both recorded. Source trees, native binaries and raw trace/row files are excluded. The original v3 campaign and frozen150-attempt benchmark remain separate.

Evidence: [Execution08 full failure report](../recovery07-08/index.html), [Machine-readable summary](summary.json), [Completed analysis03](analysis-attempt03/result.json.gz), [Independent all-row accounting](independent-row-accounting/d03-independent-row-math-summary-01.json.gz), [Independent native lifecycle audit](controls-review/d03-terminal-independent-audit-02.json.gz), [Exact equivalence](actual-d03/diagnostic/equivalence.json.gz), [Publication manifest](manifest.json), [Complete evidence index](evidence.html).
