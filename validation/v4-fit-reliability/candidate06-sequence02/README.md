# Candidate06 sequence02: preserved mixed outcome

Eleven correctness checks passed. The original-initialization pulse cold fit passed; the density cold fit failed. This packet publishes that outcome, all13 attempts, original outcomes, failed trial evidence and four saved-output audits.

Read report.json for machine-readable diagnostics and index.html for the evidence links. Aggregate rank/export/selected audit exits retain the unsuccessful density case; inspect their per-case rows.

- Candidate06 remains unsuccessful: the density cold fit failed during its second trial. No density covariance is accepted and no release readiness is established.
- The 11 correctness checks and two cold fits are diagnostic regressions, not replacements for frozen v3.1 or v4 benchmark attempts. Frozen protocols, physical/statistical models and correctness thresholds are unchanged.
- Both cold fits use their original GNSS-only initialization without a donor nuisance state. The one-hour case is synthetic leo500/quiet/normal; GRACE-FO filenames in templates do not make it a flight accuracy experiment.
- Saved-artifact rank, covariance/export and objective/refinement audits have distinct scopes. A strict pulse final covariance does not prove calibrated scientific uncertainty, full-grid independent tangent reconstruction or complete flight derivatives.
- Rank uses the original reduced stochastic row count and the undamped saved factor. Driver singular-value differences are disclosed without adding a numerical agreement tolerance.
- The first density trial was rejected as a physical-domain failure; its second trial failed a native correction check. Preserve both rather than relabeling either as convergence. Trial-history/rollback source and receipt evidence is separate from re-executing every historical trial.
- The original sequence aggregate reporting exception, the initial helper test failure and the source02 selected-audit compression-reader failure remain preserved. Corrected reporting/audit readers do not change estimator outcomes.
- No accuracy-superiority, GPU speedup, complete-flight-Jacobian or paper-readiness claim follows from this packet. No aggregate audit exit code alone determines whether a particular pulse check passed.

All copied receipts preserve original bytes. Bulky inputs, raw row archives and orbit arrays are excluded. Checksums and original absolute source identities remain in inputs-manifest.json. This builder does not rerun fitting, compute covariance or approve a release.
