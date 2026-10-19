# Separate nuisance-profile performance investigation

The frozen v4 campaign and its executable remain unchanged. This development
checkout investigates the cost of objective evaluation; it does not replace a
frozen attempt, change the statistical problem, or relax any numerical gate.

The preserved first 24-hour dense pulse timeout records two completed nuisance
profiles taking 3,129.534 and 3,927.822 seconds. Their 7,057.355 seconds account for
98.013% of the supervised 7,200.426-second fit. Both reported strict nuisance
convergence. A third point completed tighter trajectory closure, but no completed
third-profile receipt was captured. These are nuisance results, not whole-orbit
convergence or authorization for covariance.

The first and repeated profiles both restart at approximately 758.722 m nuisance
update influence, followed by 19.6195 m and 0.655118 m. This identifies duplicated
cold-start work at the same physical state. It does not establish which internal
QR, observation evaluation, or I/O operation dominates. Warm starts require a
broader state-identity and rollback design and are deferred from the first
candidate.

## Offline analyzer

`scripts/analyze_nuisance_profile.py` reads terminal-fit receipts only. It runs no
native process and writes only a new diagnostic JSON file. For a closed full fit:

```bash
python scripts/analyze_nuisance_profile.py /path/to/closed-fit \
  --terminal /path/to/closed-fit/result.json \
  --supervisor /path/to/closed-fit/supervisor.json \
  --output /path/to/new-diagnostic.json
```

Several capture directories for the same fit may be supplied. Identical copies
are counted once; conflicting copies fail. Optional repeated `--manifest` inputs
verify the captured file hashes and lengths. The report pins every consumed
receipt and the analyzer source. It rejects running or unknown terminal statuses,
conflicting recorded attempt identities, an explicitly running supervisor in a
capture root, and changes to inputs during analysis. A captured full result is
checked against its terminal hash when supplied. Missing identity information is
reported as unknown. This offline check does not inspect current remote process
liveness; a stable copy of an old terminal receipt is not a current-host check.

The analyzer reports profile wall time, trial-child CPU, and zero-update-replay
CPU separately. Missing timings remain null with explicit coverage counts.
Historical replay receipts have no replay CPU measurements, so no replay timing
is inferred. Trial failures, nonzero replay statuses, invalid receipts, incomplete
profiles, and missing LM evidence remain visible. Absence of LM records in a
partial capture cannot prove that no LM work occurred. Reported native convergence
and fit status are not independently certified by this tool.

Optional `qr.<generation>.nuisance_performance.json` sidecars add measured parent
row assembly and disjoint child categories: zero-update replay, ordinary line
search trials, arithmetic audits, and probe history. The final probes are not
counted a second time. Sidecars must agree with existing line-search trial counts,
statuses and overlapping timing fields. A replay CPU field absent from the older
receipt may be supplied by its matching sidecar. Ordinary child CPU already in
the older receipt is counted once. Missing or orphaned sidecars do not create
timing measurements.

Observation-design time is part of row-build time; child row-build time is part
of child wall time; all these durations overlap the overall profile wall time.
They must not be added together. The report keeps these scopes separate and
retains unavailable and incomplete timing records explicitly.

## Proposed bounded native comparison

Run this comparison only in a separately admitted environment and separate
output/build directories. Do not execute it on a CPU assigned to a frozen timed
fit. Preserve the current source, build, configuration and input hashes, and pin
the performance candidate separately.

1. Select two already validated small native fixed-orbit profiles, one pulse and
   one density case. Include the archived troublesome nuisance replay as a
   separate regression. Freeze their original profile XML, inputs, observation
   support, physical coordinates and controls before comparing candidates.
2. Run legacy and opt-in candidate from independently fresh native processes, with
   the same single-thread settings and cold nuisance initialization. Alternate
   execution order in a predeclared list. Each run has its own spool/output root;
   neither reads previous factors or estimated nuisance coordinates.
3. Compare direct objective values, actual reductions, zero-update replay,
   observation signatures, weighted row counts, parameter names/units/order,
   full-pulse and OU costs, nuisance termination status, and line-search decisions.
   Verify unchanged fixed observations and weights. Count all failed evaluations.
4. On identical captured small linearizations, retain the existing MAP limit of
   `1e-7` posterior standard deviations and relative covariance limit of `1e-8`.
   For complete fixed-point evaluations, compare objectives against independently
   measured numerical floors; keep the existing position, pulse/density and
   measurement prediction limits. No tolerance is inferred from runtime gains.
5. Require both consecutive nuisance updates below the unchanged `1e-8 m`
   threshold and a fresh undamped factor for strict success. Empirically
   floor-limited progress retains its existing label and never authorizes
   covariance. Preserve the original failure-replay behavior and all support,
   rank, rollback and covariance-freshness gates.
6. Report time and memory with outcome/equivalence evidence. Separate repeated
   cost-only evaluation work from full row assembly, QR and rank certification.
   An arithmetic-equivalent optimization may be useful without making the
   complete two-hour orbit fit feasible; a whole-fit claim needs a separate run.

This is the acceptance-runner specification, not evidence that the runs occurred.
The offline analyzer's focused tests cover timing scopes, incomplete captures,
failed children, duplicate/conflicting receipts, input identity, terminal status,
manifest validation, nonfinite evidence, and refusal to overwrite a report.

## Separate native build and cache controls

Build this candidate in a fresh source/build pair, using the same pinned compiler
and dependency environment as the corrected reference. Admit the build and test
CPU resources separately from the frozen campaigns. For the v4 numerical profile:

```bash
python scripts/build_groops.py \
  --source-dir /path/to/new-native-source \
  --build-dir /path/to/new-native-build \
  --prefix /path/to/pinned-native-environment \
  --jobs 1 --numerics --segmented --wide-tangent-candidate \
  --nuisance-performance
```

The build script requires upstream commit
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`. The optional installer runs after the
corrected numerical and selected segmented/wide-tangent extensions. It records
the installer/header hashes, original source hashes and all four installed file
hashes in `orbit-poc-nuisance-performance-extension.json`. Those four files are
the GNSS processing source, LEO dynamic-orbit parametrization source, nuisance
line-search header and new instrumentation/cache header. `build-manifest.json`
also records the optional manifest, actual patched source inventory, executable,
CMake cache, compiler and build command. Retain the runtime/dependency inventory
with the candidate; an executable hash alone does not identify its loaded
libraries.

Reentering an already installed source tree requires `--nuisance-performance`
and the same segmented/wide-tangent profile flags. The build script verifies the
optional extension before configuring and skips the generic installers, whose
header-copy step would otherwise overwrite the attributed line-search header.
A changed installer, installed source, or profile is rejected; use a fresh tree
for a changed candidate. The installer prevalidates all patch anchors before
writing source and accepts a pre-copied header only when its bytes match exactly.

Both runtime controls default to `0` and accept only `0` or `1`:

| Environment variable | Effect when set to `1` |
| --- | --- |
| `ORBIT_POC_NUISANCE_PERFORMANCE` | Writes measured per-search performance sidecars. |
| `ORBIT_POC_NUISANCE_INTERPOLATION_CACHE` | Reuses one identical native LEO design-interpolation result within a single row build. |

Compare cache `0` and `1` with performance `1` using the **same candidate
executable**, independently fresh processes and separate output XML/spool roots.
Set `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and
`NUMEXPR_NUM_THREADS` to `1` in both runs. The cache does not change a public
comparison/segmented configuration, nuisance initialization, observation mask,
iteration budget or numerical threshold.

The cache wraps only the existing LEO `PosDesign` interpolation. Its exact key
contains the receiver, epoch, arc, parameter/polynomial/design identities,
integer/fractional time components, full `long double` time remainder and
arithmetic-audit mode. Signed zero is distinguished; nonfinite queries always
execute the original interpolation. There is no tolerant `Time` comparison or
rounding of the remainder. A failed interpolation is never cached.

Every `buildNormals` call starts a fresh cache generation, including a forked
trial. Scope exit or an exception disables reuse; design calls outside that
scope, including conditional nuisance recovery, execute the original
interpolation. This lifetime remains enforced when instrumentation is disabled.
Storage holds one native 3-by-dynamic-parameter matrix, not a trajectory-wide
collection. Each observation still performs its own line-of-sight multiplication,
design registration and validation, group QR/rank checks and segmented export.
All original objective/prior ledgers and transactional trial checks remain active.

Performance sidecars cover search iterations; the final standalone linearization
has no search sidecar. Parent nuisance solves, local recovery and parameter-update
costs are not separately timed. Interpolation time is nested inside
observation-design time, which is nested inside row-build time. Cache counters
report calls, actual evaluations and exact-key hits; they do not establish a
speedup or numerical equivalence. Those claims require the native off/on evidence
and unchanged acceptance gates described above.
