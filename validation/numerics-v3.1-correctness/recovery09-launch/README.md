# Candidate09: validation launched, outcome pending

The independently reviewed light-time arithmetic correction was launched on
October 15, 2026 at 12:36:08.791 UTC on `gpuserver4090`. This immutable snapshot
records launch and preparation, not the eventual scientific outcome.

The frozen source is `7e232423566a9d608ada0bcc88af8a86dd914db3` (772 files).
The publication cherry-pick `451d12af8f6b3b48d133a6a7fd67b274da2d9a41`
contains the same five changed files, verified against the source freeze.
The correction preserves expansion precision through the light-time duration
calculation. It changes no physical/statistical model or acceptance threshold.

The planned unchanged suite has the original 106 native tests, four refinement
checks, both objective checks and both distinct original nuisance replays.
There are also 51 separate correction regressions. The 316 passing fabricated
control tests check orchestration and reporting; they are not native acceptance
results. Every original input pin and all previous failed executions remain bound
through the correction lineage.

The first staging helper rejected an artifact containing the valid `bytes` field
because it compared against a two-field record. It stopped before source
extraction or native work. The separately reviewed second helper validates the
exact path, hash and byte count; the failed first receipt remains here. A missing
upstream-checker transfer was likewise caught before namespace smoke, then the
exact reviewed checker was transferred. The single subsequent smoke and
independent prelaunch audit passed.

The 21 exact runnable control/test sources are in
[`scripts/correctness_recovery09`](../../../scripts/correctness_recovery09/).
This evidence package tokenizes host paths and retains both original and
published hashes. Tokenized helper copies in the provenance are records, not
commands for reproducing the occupied run. Full sources, runtime archives,
observations, binaries and row spools stay outside this package.

Correctness remains unresolved until the complete required suite and independent
terminal audit pass. No accepted covariance or release readiness is inferred;
the frozen 150-attempt benchmark remains a separate deliverable.

[Machine-readable snapshot](summary.json) · [Launch receipt](actual-prelaunch/candidate09-launch.json) ·
[Independent prelaunch index](control/candidate09-independent-control-review.json) ·
[Source equivalence](control/candidate09-publication-source-equivalence.json) ·
[File manifest](manifest.json)
