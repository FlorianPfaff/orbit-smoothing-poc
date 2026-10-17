# Shifted-cut diagnostic publication

The [independently audited report](../shifted01/index.html) checks captured linearizations with shifted computational cuts. Both methods exercise genuine interior boundary movement at the 1,800-second offset. The pulse 300-second offset has no interior-cut coverage and is not credited as such.

Worst MAP discrepancy is below 2.25e-12 posterior standard deviations; worst relative covariance discrepancy is below 9.14e-14. These are linearized numerical checks, not newly estimated trajectories or accepted-fit covariance. No propagation or benchmark fit was performed: v4 remains at 0/68 attempts in this snapshot, and release readiness remains false.

The exact raw capture is an [external prerelease evidence asset](https://github.com/FlorianPfaff/orbit-smoothing-poc/releases/tag/v4-shifted-01), with SHA-256 `bf82c551377ea710bd2a8da7ece46816c8e905307dd079680dee207bb6516b9e`. Its 110-member inventory is in [external-asset-manifest.json](external-asset-manifest.json). Numerical arrays, graph/solver payloads and row files remain outside Git. The report records exact references for all 84 external payloads; 36 original/shifted row files remain in their pinned remote archives rather than this compact capture.

The independent publication audit records exact membership and bytes. Thirteen expired temporary fixture origins are distinguished from available original files: their archived copies match the original recorded hashes. Earlier parser, staging and read-only audit failures remain preserved. This diagnostic supplements the separate validation03 snapshot without rewriting it.
