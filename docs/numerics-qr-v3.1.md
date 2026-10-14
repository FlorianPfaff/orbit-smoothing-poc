# Native original-row QR, v3.1

The opt-in native path consumes whitened observation and Gaussian-constraint
rows before normal-equation assembly. The legacy solver remains the default.
`ORBIT_POC_NUMERICS_QR_PREFIX` enables the path and identifies its output stem.

Per-observation ionosphere parameters are eliminated with rank-checked QR.
Their Householder factors are retained and checked against the original rows
when recovering nuisance updates. Independent epoch clocks and VTEC parameters
are eliminated jointly with QR, retaining their conditional triangular factor,
retained-column coupling, transformed target and unit-normalization map. This
uses the native epoch VTEC registration; it changes no model, prior or gauge.
The small epoch block is normalized by its weighted column norms before rank
diagnosis and factorization, and conditional recovery restores native units.
The factor metadata records local indices and scales, and the parameter table
records the same scales alongside units. Time-coupled clocks or VTEC,
unsupported local parameter types, correlated observation errors, MPI, integer
ambiguity resolution and adaptive measurement weights fail closed.
Constraints that bypass the original-row hook are rejected.

The remaining original rows are spooled outside the repository. Column norms
include all reduced retained observation and prior rows after exact local
elimination; this is the same retained-scaling convention used previously. A second pass streams
scaled rows through blocked Householder QR using GROOPS's LAPACK dependency.
The triangular/rectangular merge uses [DTPQRT](https://www.netlib.org/lapack/explore-html/d4/dad/group__tpqrt_gadb01a522e74a81897506c27a3508e35c.html)
and applies the same transformations to targets with [DTPMQRT](https://www.netlib.org/lapack/explore-html/d7/de6/dtpmqrt_8f_source.html).
This preserves the existing triangular structure between row blocks; it does
not refactor the entire square factor for every incoming block.
The implementation never constructs a normal matrix to obtain the factor.
Residual energy outside the retained triangular factor is accumulated explicitly.

The undamped factor is diagnosed by SVD with
`t = epsilon * max(reduced_row_count, retained_column_count) * sigma_max`.
Values at or below `t` are deficient; values above `t` and at or below `10*t`
are unresolved. Neither status permits a solve or accepted covariance. There
is no automatic ridge, discarded estimable column, or normal-equation fallback.
Code/TEC datum spaces come from original-row SVD. Ambiguity datum selection
uses original-row projections, retaining receiver-before-transmitter-before-
ambiguity preferences and reverse-index tie preferences. The selected bases
and masks are exported independently of physical parameter units. The ambiguity
row space is first certified by SVD; unresolved singular values fail explicitly.
The selected columns must span the certified rank and pass their own rank check.

`ORBIT_POC_NUMERICS_MODE` accepts `profile_step`, `linearize`, `step`, `profile`
and `covariance`. `profile_step` holds dynamic updates exactly at zero while
updating clocks, float ambiguities, signal biases and ionosphere. `linearize`
and `profile` export without applying an update. `step` supports dynamic-only
scaled damping through `ORBIT_POC_NUMERICS_LAMBDA`. Final covariance always
uses the undamped factor and selected triangular solves; nuisance uncertainty
remains in the joint factor. Final observation residuals are recomputed at the
accepted state; residual redundancies are explicitly NaN because this path does
not estimate them. Phase recovery continues to use independently recomputed
code/phase residuals.

Each factor generation writes `PREFIX.N.factor.json`, `.R.bin`, `.rhs.bin`,
`.parameters.tsv`, `.rows.tsv`, `.singular_values.txt`, `.delta.tsv`,
`.diagnostics.json` and `.profile.json`. Binary matrices contain two little-endian
uint64 dimensions followed by row-major float64 values. The metadata gives
retained global indices, column scales, dynamic flags and orthogonal residual
energy. For scaled solution `y`, the native increment is `diag(scales) * y`.
The parameter table labels clocks and code/TEC bias coefficients in metres,
VTEC in TECU, density in unitless log coordinates, phase/ambiguity coefficients
in cycles, and phase frequency trends in cycles per channel. Unknown units fail
explicitly. Pulses retain micrometres per second. Initial velocity coefficients
are metres: physical velocity multiplied by the native arc time scale. The
`coordinate_convention` column identifies that scaling; the exported initial
design artifact supplies its numerical SI map. Column normalization remains
separate from these physical coordinate conventions.

For production-sized problems, set `ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS=0`
to remove superseded `.R.bin`, `.z.bin`, `.rhs.bin`, and `.rows.tsv` artifacts only
after their successor factor has been written successfully. Every generation
keeps its parameter identities, column scales, singular values, rank, objective,
and update diagnostics. The current factor remains available; a failed successor
cannot delete the preceding factor. Before deletion, `PREFIX.N.retention.json`
records each path, SHA-256, byte count and artifact role with status `planned`;
status becomes `completed` after deletion. A partially interrupted cleanup is
therefore distinguishable from a completed cleanup. The default keeps all factors.

Set `ORBIT_POC_NUMERICS_SPOOL_DIRECTORY` to an existing output/scratch directory
with sufficient storage. A private `mkstemp` file is unlinked immediately and
closed as soon as the triangular factor is formed; process termination cannot
leave a named row spool behind. Without this setting the default is the system
temporary-file location. Factor metadata records the policy, chosen directory,
and bytes written. A dense spool needs `8 * reduced_rows * (retained_columns + 1)`
bytes, while each triangular factor is currently exported as a dense square
matrix (`8 * retained_columns**2 + 16` bytes). These storage settings do not
change any rows, constraints, scales, or numerical operations.

`direct_cost` is half the current sum of squared weighted observation and full
prior residuals, evaluated before any parameter elimination. The discarded STEC target energy
is restored explicitly: flight third-order and bending terms make STEC a
nonlinear nuisance parameter, so its local QR prediction is not an exact
nonlinear profile. STEC updates contribute their physical measurement effect
to the nuisance convergence check. After nuisance convergence, the recomputed
direct residual is the value used by the outer nonlinear objective. The
separately named `linearized_profile_cost` is the predicted cost after a nuisance
correction and must not substitute for an actual nonlinear objective evaluation.
The objective evaluator checks the profiling status and repropagates every
physical trial independently. The separately audited progress-only resolution
status described in [the objective protocol](numerics-objective-v3.1.md) reports
an inexact nuisance profile with an empirical resolution estimate. It cannot
establish convergence or authorize covariance, and its physical steps use the
explicit inexact-profile forcing rule. A small rejected nuisance step alone
cannot produce that status.

Nuisance stationarity diagnostics use a cancellation-safe predicted reduction:
half the discarded STEC and joint epoch-nuisance target energies plus
`z.T @ (R @ y_nuisance) - 0.5 * ||R @ y_nuisance||**2`, accumulated with extended
precision. This resolves small remaining corrections even when subtracting two
large objective values rounds to zero. The corresponding column-normalized
gradient diagnostics are reported separately for retained nuisance, conditional
clock/VTEC and conditional STEC coordinates, and their maximum is divided by
`max(1, ||weighted current residual||)`. These sequential orthogonal coordinates
preserve native units separately from column scaling. The cached native getters
`lastNuisanceReduction()` and `lastNuisanceGradient()` are reset at each new
linearization; they cannot reuse a prior generation's stationarity result.
`epoch_nuisance_eliminated_target_energy` and
`epoch_nuisance_conditional_gradient_scaled` describe the joint clock/VTEC block;
the older `clock_*` keys remain aliases for diagnostic-reader compatibility.

The full pulse reference is supplied through
`ORBIT_POC_NUMERICS_PULSE_REFERENCE`, a plain numeric vector in native pulse
parameter order. Scalar pulse constraints add it to the accumulated increment;
the OU constraint already combines the reference knots and accumulated update.
Code/TEC zero-mean constraints also penalize full accumulated values. Their
initial coordinates use the native basis projection before any nuisance update;
each block subsequently accumulates its own updates. The combined physical
signal-bias array also receives phase-bias updates, so reprojecting that array
would incorrectly couple a TEC prior to overlapping phase coordinates. The
coordinate caches reset only at parameter/basis initialization, which lies
outside the repeated profiling loop. Each generation records the full native
code/TEC coefficients in `.bias_coordinates.tsv`, and datum basis exports retain
the coordinate transformation. This is a numerical parameter-bookkeeping correction:
Gaussian priors remain on the original parameter coordinates in the fixed datum
basis, with the same means and weights. The legacy implementation can reproject
the combined signal-bias array after an overlapping block changes it, so its
reported full-parameter penalty can differ from the intended penalty. Therefore
legacy-versus-new end-to-end objectives need not match when that defect is active;
solver equivalence is asserted only on identical original weighted rows. The
benchmark must distinguish this correction from changes due to staged derivatives
rather than claiming unconditional objective equivalence.

For fixed physical parameters, the native linearization has weighted rows
`r - A_eta * delta_eta`, including nuisance priors. Each local QR rotation is
orthogonal; its removed target components and conditional coupling are retained.
The retained nuisance-only solve followed by conditional clock and STEC recovery
therefore gives the same linearized correction as the joint nuisance system.
Applying that correction and rebuilding the observation equations evaluates the
actual nonlinear cost, including the higher-order STEC terms. A converged local
profile is checked by fresh undamped rows and its numerical diagnostics; the
linearized solve alone does not certify a global nonlinear nuisance minimum.

Nuisance steps use an objective-checked backtracking search along the joint
undamped GN direction, including recovered STEC and clock corrections. The
candidate factors are 1, 1/2, ..., 1/65536. A nonstationary trial requires positive
actual reduction and gain ratio above 1e-4; there is no nuisance damping or added
prior. Actual reduction uses paired directly evaluated residual squares,
accumulated in extended precision, instead of subtracting large objective sums.
A Linux fork evaluates each candidate in a private memory snapshot. Writable
inherited descriptors are replaced with `/dev/null`; read-only regular inputs
are reopened independently at their current offset. The cost-only accumulator
suppresses factors, traces, bias exports and row spools. The float QR path keeps full ambiguity coefficients instead of transferring
integer cycles into the measured phase values. Each trial checks unchanged
observation/weight bytes and exact accumulated ambiguity coordinates (to floating
precision), and reports half-integer crossings. The parent applies only
an accepted increment, once, and its next direct cost must reproduce the child
cost exactly. A child has a 300-second limit, dies if its parent dies, and exits
without inherited stream destructors. This path requires a single-thread
process and explicit `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`.

Each generation also evaluates a private zero-update replay and records its
objective change, so a history-dependent state refresh cannot be hidden inside
a line-search step. A zero update first synchronizes receiver caches to their
current clocks before the initial cost/Jacobian; every later replay must leave
the objective and state exactly unchanged. `.nuisance_coordinates.tsv` records the complete current
non-dynamic parameter vector, separately from invariant parameter metadata.

Each generation writes `.nuisance_line_search.json`, retaining every trial,
rejection, support failure, actual reduction, alpha, and child wait4 resource
measurement. Child peak RSS is a separate diagnostic, not a simultaneous process
tree peak. Convergence always checks the full fresh undamped correction, never
the shortened accepted update. Two successive full corrections below 10 nm
permit a final fresh undamped factor; all rejected trials without raw
stationarity report nonconvergence. This inner numerical threshold does not
change the specified outer physical convergence criteria.

The opt-in QR runtime evaluates polynomial queries continuously. Native
`Polynomial` uses its time margin both to recognize regular grids and to snap
nearby queries onto stored rows. The latter can introduce a 0.76 mm position
jump for a 100 ns receiver-time offset at 7.6 km/s, inconsistent with the
30 µm outer convergence criterion. QR bypasses approximate query snapping and
approximate time-vector equality, while preserving exact time identity, the
same interpolation degree, stencil selection, regular-grid checks
and pulse boundaries. QR evaluates the identical Lagrange polynomial and its
derivatives using local time differences, extended-precision coefficients and
accumulation; the historical monomial inversion can introduce sub-micrometre
cancellation errors on Cartesian coordinates. This applies to shared GNSS interpolation as well as the
receiver trajectory. The legacy runtime is unchanged. Prediction differences
from this numerical correction belong to both QR profiles and are reported
separately from staged derivative effects. Native tests cover knot neighborhoods,
clock-time slope and exact-grid identity.

QR receiver clock shifts are applied directly to the nominal fractional day,
in extended arithmetic before returning the native `Time`. This avoids first
normalizing a tiny negative clock duration to almost one whole day. The stored
day fraction remains double precision: late-day and midnight tests explicitly
record the remaining few-picosecond representation error. Native clock seconds
and nominal/corrected day components are saved in `.receiver_times.tsv`, avoiding
a lossy round trip through printed clock metres during diagnostics.

Receiver mean, velocity and dynamic-design interpolation retain the unrepresented
part of nominal epoch minus receiver clock as an explicit long-double relative
query offset. Transmitter light-time queries use nominal receiver epoch minus
the combined clock and travel interval, carrying the same remainder into the
transmitter polynomial. The polynomial degree and within-segment stencil rules
are unchanged. The QR piecewise wrapper selects the pulse/knot segment using the
exact intended time, without native `Time`'s 10-microsecond comparison tolerance;
a query before a pulse therefore uses the pre-pulse side and an exact pulse
uses post-pulse velocity. The archived legacy path is unchanged.

The shared numerical policy is `relative_query_clock_range_v1`. Native Time is
still used for metadata, attitude and antenna consumers. Cartesian archives,
state/design matrices and the primary caches retain double storage. The GNSS
range calculation additionally carries each long-double interpolation sum's
low part, including antenna-offset addition roundoff, and reconstructs geometry
in extended precision. Its light-time loop requires transmitter endpoint
agreement below 0.1 nanometres within ten iterations. The archived legacy loop
is unchanged. This initial precise geometry path explicitly rejects Earth-fixed
receivers and supports the benchmark's inertial LEO receivers. These policies
are explicit in factor/backend provenance; they do not claim arbitrary time
or coordinate precision. Clock sweeps at early/late day and midnight test
the relative interpolation, and pulse-side fixtures include 50-nanosecond and
sub-Time offsets.

The corrected code/phase range uses the same geometric, Shapiro, relativistic,
clock and transmitter-scale terms. QR evaluates geometry in extended precision
and subtracts clocks after the measurement-minus-geometry difference, so a small
clock update is not first rounded onto a roughly 20,000 km range. The native
clock Jacobian is unchanged. This numerical correction affects both QR profiles;
it is separate from the staged force/trajectory derivatives and leaves the
legacy runtime untouched.

The raw nuisance convergence influence includes the complete joint observation
row update, including VTEC and recovered STEC, converted back to metres with the
fixed measurement sigma. Existing component maxima also remain, preventing
cancellation from hiding a large individual update. Prior rows retain their
own units; their normalized gradient/potential diagnostics are not silently
compared with a metre threshold.

`OrbitPocQrSolve` is a native correctness fixture that uses the same QR class.
Run its independent solution, covariance, profiling, unit, row-order, block-size,
rank and GTSAM checks with:

```bash
ORBIT_POC_V31_NATIVE=/path/to/groops python -m pytest tests/test_numerics_native_qr.py
```

For a machine-readable release receipt that also verifies the executable against
its source/build manifest, use a new output directory:

```bash
python scripts/validate_numerics_qr.py --native /path/to/groops \
  --build-manifest /path/to/build-manifest.json --output /path/to/qr-validation
```

The receipt rejects missing GTSAM checks, records every test outcome, and includes
the executable, actual patched-source tree and test-source hashes. The build
script hashes compilation inputs before and after the build and rejects changes
during compilation.

These small original-row checks do not establish GNSS pipeline correctness,
nonlinear convergence, flight accuracy or benchmark completion by themselves.

The benchmark sets `ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE=1`. Each
completed weighted-row ledger is compressed with zlib at fixed level 6, decoded again with
CRC/end-of-stream checks, and compared to its original SHA-256 and byte count.
Only after the completed gzip and `verified_row_compression_v1` receipt are
published is the raw TSV removed. Every generation's gzip and proof remain,
including when intermediate R/target factors are released. Compression changes
no numerical rows. Failed or unfinished compression retains the raw source.
The opt-in default is zero for small fixture compatibility; the benchmark
explicitly selects verified compression.
