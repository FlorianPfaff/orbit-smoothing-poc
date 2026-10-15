# Execution10 launched; scientific outcome pending

Execution10 launched on October 15, 2026 at 13:00:35.384 UTC on
`gpuserver4090`. This is an immutable launch snapshot, not a terminal result.
The source is `c24eccbcfc541250af958fd7c84101c3d039ced3`, also published on
`numerics-v3.1-correctness-06`; publication cherry-pick
`4a16df18a54975f1704a5dcf153920e74a822ebf` has the exact same one-file change.

The immediate predecessor is **failed execution09**, source
`7e232423566a9d608ada0bcc88af8a86dd914db3`. That attempt had 104 original native
tests pass and two installer tests fail; its nine subsequent stages were not run.
Only `groops/extension/positionRemainder.py` changes now, preserving installer
compatibility with the unchanged scaffold tests. The prepared 1,129-file native
source tree is byte-identical before/after this installer correction. This is
source equivalence, not a native acceptance result.

All 772 tracked source paths remain, including the exact original 106 native
tests, 51 separate regressions and unchanged gate scripts. Original inputs,
physical/statistical models, priors, weights and acceptance thresholds stay
fixed. The full required suite must still run and pass independent audit.

The **21 scientific controls remain byte-identical version09**. Consequently,
`candidate09-*`, `validation-09` and `postprocess-09-01` filenames name the
control protocol, while the execution root and exact launch identity identify
attempt10. The unchanged control lineage retains its cumulative comparison
against candidate07/source04 from execution08. That cumulative basis is **not**
the immediate predecessor: the separately pinned installer supplement proves
failed09/source05 → execution10/source06, the exact one-file change, unchanged
51-test inventory and preserved failed09 journals. Any inherited report phrase
about an immediate candidate07 predecessor must be read with this explicit
correction; it is archived control-version wording, not current chronology.

[Exact supplementary helpers and tests](../../../scripts/correctness_execution10/)
include the strict lineage verifier, stager and freezer, with independent fixture
counts 49 +27 +30 +10. The published layout also includes25 exact fixture dependencies;
all116 fixtures pass at the published location. The original missing-dependency
publication draft is preserved outside Git; no executed helper or test changed.
The raw candidate09 control-validation JSON is an exact required test input,
separate from tokenized evidence copies. [Original controls09](../../../scripts/correctness_recovery09/)
remain unchanged. These preparation tests and source equivalence do not authorize
covariance or release readiness. The frozen 150-attempt benchmark remains a
separate unfinished deliverable.

[Launch summary](summary.json) · [Launch receipt](actual-prelaunch/candidate09-launch.json) ·
[Immediate correction lineage](source-freeze/installer-correction10.json) ·
[Actual supplementary verification](actual-prelaunch/execution10-supplementary-verification.json) ·
[Independent prelaunch audit](control/execution10-independent-staging-audit-01.json) ·
[Source equivalence](control/candidate10-publication-source-equivalence.json) ·
[Manifest](manifest.json)
