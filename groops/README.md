# GROOPS v3 comparison

This extension targets GROOPS commit
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`. It adds a linearly
interpolated log-density multiplier, a stationary discrete OU constraint,
explicit integration boundaries, marginalized Cartesian covariance export,
deterministic GNSS simulation, and prediction programs for held-out GNSS code
and SLR. The published v2 results are separate and remain unchanged.

**Implementation and successful execution are different acceptance conditions.**
A prepared dataset, passing unit tests, or a successful native build does not
establish improved orbit accuracy. The comparison report retains failed fits
and missing acceptance evidence. Production evaluation requires completed,
frozen calibration; no superiority claim follows from a smaller penalized
objective.

**The scientific comparison remains incomplete.** Flight numerical acceptance
passed with an explicit 0.1-second thermal maximum step in the shared campaign
force model. This setting applies to both primary models and the matched-physics
AR reference; the official reproduction template and native default remain
unchanged. Calibration and scientific evaluation are still separate gates. See the
[native validation guide](../docs/comparison-native-validation.md) for commands,
scoped evidence and preserved failed refinements.

## Build

Use a Linux filesystem for the compiler environment; case-insensitive Windows
directories corrupt some Conda compiler/sysroot package paths. Source data and
the repository may be on a mounted Windows drive, although repeated conversion
is appreciably slower there. MPI is disabled for this version because the
covariance extension currently supports serial execution only.

```bash
micromamba create -y -p /tmp/orbit-v3/native-env --file groops/linux-64.lock.txt
micromamba run -p /tmp/orbit-v3/native-env python -m pip install -r groops/python-requirements.lock.txt
micromamba run -p /tmp/orbit-v3/native-env python -m pip install --no-deps -e .
micromamba run -p /tmp/orbit-v3/native-env python scripts/build_groops.py \
  --source-dir work/v3/groops-source \
  --build-dir /tmp/orbit-v3/groops-build \
  --prefix /tmp/orbit-v3/native-env --jobs 8
```

The script checks the exact upstream revision, applies the versioned extension,
builds GROOPS and writes a build manifest with checksums. The CMake source is
the upstream repository's `source/` directory. The explicit lock contains the
86 native build packages; project Python dependencies are declared separately
in `pyproject.toml`. Tudat has its own existing `tudat-linux-64.lock.txt` and
must run in a separate interpreter. The native extension is GPL-3.0-or-later;
see `extension/NOTICE` and `extension/LICENSE`.

## Data and configuration

Download and extract the [official reduced-dynamic example](https://ftp.tugraz.at/pub/ITSG/groops/scenario/scenarioLeoReducedDynamicOrbit.zip).
Its SHA256 is
`5a9d10bbab419489e5a62306ab5f1c840963ca66fb0b1b9e70fb648e9629f63b`.
Keep the archive, observations, auxiliary products, converted files and runs
outside Git. Public source URLs, byte counts and hashes are recorded when
preparing a dataset; cached downloads are checked before reuse.

`comparison.groops_config.build_day_configs` creates runnable configurations;
`run_native_preparation` executes the product and receiver conversions only.
The templates under `templates/` retain attribution to the published example.
Flight preparation screens THR1B orbit-control activity and GPS/SCA instrument
flags before initialization. An excluded fixed date is recorded and never
replaced by another date.

Flight dates denote actual 24-hour UTC intervals. In 2024 their GPS endpoints
are midnight plus 18 seconds, so preparation joins the named GPS-day product
with the first 18 seconds of the following day's spacecraft measurements and
the attitude support through the terminal 18-second epoch. Transmitter orbit, clock and attitude products include adjacent-day
support; coverage is verified before preparation succeeds. The propagation
and density grids span both UTC-midnight endpoints (17,281 states at 5 seconds).
Measurements retain their original GPS cadence: candidate 30-second epochs run
from GPS 00:00:30 through the following GPS midnight. Provider-marked low-SNR
and phase-break observations remain excluded; the last candidate can therefore
be absent, as it is for April24. No measurement is fabricated or substituted.
Native time-series offsets preserve exact epochs;
adding 18 seconds to an absolute floating-point MJD would lose precision.
The two GNV files stay separate and are read only by post-fit evaluation.

The flight numerical model uses the same canonical 5-second attitude samples
and native degree-7 interpolation on every dynamics grid. Raw 1-second SCA
records remain in the acquisition archive. Finer dynamics grids receive a
separate synchronized attitude file interpolated from the canonical file;
the receiver gets a separate orbit/attitude pair interpolated at its exact
retained GPS observation epochs. This is necessary because the native receiver
matches epochs within 0.1 seconds instead of interpolating them. The receiver
bootstrap geometry remains immutable across models and iterations. SLR uses the
canonical attitude curve. Held-out code prediction samples that same curve and
the fitted orbit at held-out epochs, with the native piecewise interpolator
preserving pulse and density-knot boundaries. Atmospheric force and density-sensitivity
integration use a separate internal quadrature grid, initially 1 second, whose
refinement to 0.5 seconds is checked independently of dynamics-grid refinement.
Thermal integration uses an explicit 0.1-second maximum step, checked against
0.05 seconds as well as the combined dynamics-grid refinement. The selected
setting is included in the shared force-model hash.

GROOPS uses one constant transmitter signal-bias table per arc. Appended
observations are therefore normalized to the primary GPS day's archived CODE
OSB datum: `normalized = raw + primary_bias - active_bias`. Native residuals
subtract the primary bias, giving exactly the active-day correction. Code
attributes stay distinct; phase attributes follow GROOPS's shared-frequency
convention. A per-record correction ledger pins both source files and records
every applied value. This deterministic change does not estimate a bias, modify
provider files, insert a cycle slip, or reset an ambiguity at the product boundary.

Copy `configs/comparison-v3.json` into a working configuration and set its
`backend.groops_executable`, `groops_source`, `example_directory`,
`auxiliary_dir`, `cache_dir` and `tudat_python` paths. Unknown fields and
unregistered methods are rejected. Paths are resolved from the working
directory, so absolute paths are preferable for private configurations.

The main commands are:

```bash
orbit-poc comparison prepare --config work/v3/config.json --stage synthetic
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python scripts/run_comparison_campaign.py --config work/v3/config.json \
  --synthetic-workers 24 --flight-workers 24
```

The first command is optional development preparation. After the acceptance
evidence is installed, the production driver runs the synthetic stage, then
the flight stage. Each stage calibrates, prepares every evaluation input,
freezes its data hashes, and only then fits and reports its primary and secondary
campaigns. The synthetic stress and flight ambiguity-resolved reference remain
separate results. See the [production driver instructions](../docs/comparison-native-validation.md#production-campaign-driver).
Individual `orbit-poc comparison` commands support resumable job records, `--max-jobs`, `--budget-hours`, and
`--workers N` for bounded concurrent numerical jobs. Direct CLI preparation stays serial;
the campaign driver primes each date's download caches serially, then prepares
remaining private case directories concurrently, preserving planned result order.
each native fit uses one BLAS/OpenMP thread. Calibration queues all candidate/arc
jobs in an expansion round, so workers can span candidates; orbit groups and
methods remain sequential. Scores and histories retain the original candidate
order regardless of completion order. Size the worker count from measured
per-fit memory and available RAM. Runtime records include hardware,
package versions, and the requested worker count. Compare timings under the
same concurrency because resource contention changes elapsed time. Reported
peak memory covers the native process, excluding the Python wrapper and shared
filesystem caches. Queued and blocked jobs never count as completed numerical fits. Do not reuse
an output directory after modifying its frozen source or configuration.

The driver accepts a maximum of 24 requested workers per stage. Before each
preparation, calibration or evaluation launch, it caps that number using currently available
memory, with an 8 GiB reserve and a 3.5 GiB planning budget per worker. The chosen
count and memory estimate are recorded with the exact command; they are not a
hard process-memory limit. Its own source is part of the frozen protocol.

Checkpoints contain compact job indexes with result paths, SHA256 digests,
identities, statuses and timing. Complete scores, per-epoch residual/covariance
arrays and failure details remain in per-job files. Resume and report loading
verify the saved result bytes; terminal results require their
`result-record.json` index. This keeps campaign checkpoints bounded without
discarding numerical evidence. The protocol report also checks that run
protocol/source hashes, stage, campaign and calibration selection match the
active freeze, then verifies the completed calibration evidence. Legacy inline
development reports can be rendered separately; they do not pass this protocol
provenance check.

Successful production fits retain SI state/covariance arrays, exact native
binary orbits, final parameter and nuisance exports, configurations, logs and
hashes. Redundant native covariance tables and superseded propagation files
are pruned only inside that fit's private directory, with an explicit deletion
audit. Flight evaluation retains full dynamic covariance/design files for
correlated SLR predictions. Set `backend.retain_native_diagnostics` to `true`
before freezing to retain these files for every fit. Use binary orbit artifacts
for downstream native predictions. GROOPS's own ASCII format preserves native
times through long-double text; ordinary Python float-MJD conversion loses
sub-microsecond precision and must not be used to reconstruct native epochs.

`prepare` is available for development. `calibrate` and `run` require an
`acceptance-gates.json` in the run directory, tied to its frozen protocol hash.
The record must contain the ordered `external_baseline`, `model_correctness`,
`pipeline_correctness` and `numerical_accuracy` gates. Each gate records `passed`,
an ISO completion timestamp with timezone, and nonempty result artifacts with
their paths and SHA256 digests. The top-level `evidence_hash` is the canonical
SHA256 of the record excluding that field. Missing gates, changed artifacts,
or a different source snapshot stop production. Do not mark a gate passed from
the existence of runnable code: attach its actual numerical evidence.

The calibration cases contain six independent arcs per orbit, each with both
a 30-minute and a two-hour holdout. The scores first average the two holdout
settings within an arc, then average the six arcs. Both methods start with
16 candidates and may use two boundary expansion rounds. Evaluation uses
fresh seeds 400000–400049 and preserves their pairing across methods and masks.
Reports take denominators from these frozen planned cases, including seeds
missing from both methods. Paired intervals use valid independent seed pairs;
failed or missing pairs remain listed. Fixed-epoch Wilson intervals use valid
coverage outcomes and separately count unavailable planned seeds. Blackout
metrics are not applicable to normal coverage. The predeclared primary cell is
`leo500 / disturbed / blackout`; other cells remain secondary.

## Native model conventions

* GROOPS pulses are three inertial Cartesian velocity changes. Its coefficients
  are **micrometres/second**; the public comparison configuration uses m/s and
  converts the prior standard deviation by a factor of one million. Constraints
  penalize the full pulse. The initialization fit has no pulses.
* Density knots are an ASCII matrix with two columns: GPS MJD and dimensionless
  log correction. The density is multiplied by `exp(g)`. Zero-mean `g` makes
  the multiplier's median one, not its mean. Knots are 60 seconds apart, with
  deterministic linear interpolation of log density between them.
* The OU prior applies to the reference knots plus the current increments.
  The first knot has stationary variance `sigma**2`; transitions use
  `phi=exp(-dt/tau)` and variance `sigma**2*(-expm1(-2*dt/tau))`.
  This is a new discretization and is not v2's continuously driven process.
* The outer loop regenerates the physical trajectory and variational equations.
  The native estimator's internal iterations alone do not update force
  sensitivities. No empirical acceleration parameters enter the density arm.
  The state-transition model retains GROOPS's low-degree gravity-gradient
  approximation; it is not a full Jacobian of every modeled force. Direct
  log-density force partials are analytic. The separate propagated-trajectory
  finite-difference diagnostic quantifies this approximation.
* Polynomial integration stencils stay within model-knot intervals. With degree
  seven, the default propagation grid is five seconds; observations remain at
  30 seconds. Insufficient or misaligned grids fail rather than silently smear
  a knot. Native pulse-epoch output velocities include the pulse.
* `computeCovarianceMatrix` precedes covariance export. The exporter uses orbit
  blocks from the inverse **full** normal system, including receiver clocks,
  ambiguities, biases and dynamic parameters. Output rows are GPS MJD followed
  by 36 row-major SI covariance entries. These are local Gaussian covariances
  conditional on the selected hyperparameters and fixed measurement weights.
  A separate `outputfileCovarianceObservationEpochs` export evaluates the
  variational designs at every nominal GNSS epoch, including withheld epochs,
  before forming `J P Jᵀ`. This handles the UTC dynamics grid's offset from GPS
  observation times. Calibration uses these propagated marginals; it never
  substitutes a nearby state covariance or interpolates covariance blocks.
  Both grids are retained losslessly in the common state-estimate NPZ.
  The [observation-epoch covariance diagnostic](../scripts/check_observation_covariance.py)
  probes every column of a small native linearization and checks the full
  `J P Jᵀ`, with cross terms, against the export using the exact fitted binary.
  The [12-parameter UTC pulse check](../validation/comparison-v3/utc_small_fit_observation_covariance.json)
  passed at 120 off-grid GNSS epochs with maximum normalized error `5.25e-10`.
  This verifies export consistency, not nonlinear uncertainty calibration.

## Isolation and scoring

Estimation accepts an explicit allowlist of input roles. GNV, truth, SLR and
held-out code use separate evaluation interfaces. Observation masks are applied
before GNSS-only initialization, observation cleaning and ambiguity processing.
Flight masks are UTC; their conversion to GPS seconds accounts for the 18-second
offset in 2024. Never initialize or tune from a comparison orbit.

After each mask's GNSS bootstrap, common preparation closes one nominal physical
orbit before either disturbance model is introduced. It holds the bootstrap's
estimated physical initial state fixed only for that numerical closure and
requires changes below 2 micrometres and 3 nanometres/second. Both GNSS estimators
then re-estimate all six initial-state components. This removes force-evaluation
errors from an interpolated gap without adding measurements or a state prior.
The input and output hashes, fixed initial state and all closure iterations are
recorded. The original receiver preprocessing geometry remains immutable.

Density optimization uses recorded numerical adaptive relaxation to limit
accepted log-density increments and suppress opposing update directions. The
accepted initial-state displacement uses the same relaxation factor, and the
native variational evaluator produces the accepted trajectory. The full OU prior
is unchanged. Convergence and the final covariance confirmation always use
undamped native updates; relaxation does not guarantee objective monotonicity.
See the [numerical controls and failure diagnostic](../docs/comparison-native-validation.md#covariance-after-nonlinear-convergence).

Primary fits keep the receiver's input orbit at the common, immutable GNSS-only
bootstrap. An explicit native preprocessing option also uses that geometry for
code initialization and observation cleaning, before restoring the current
dynamic trajectory for estimation. This prevents a model-specific trajectory
from changing the retained observations, nominal angle-dependent weights, or
ambiguity arcs. A native audit exports the retained processed observations,
weights and track boundaries. Their hashes must agree across outer iterations,
hyperparameter candidates and primary methods; disagreement blocks comparison.
The separate native ambiguity-resolved reference retains its official
preprocessing and weighting sequence.

The code predictor calls the native GNSS observation equation. It forms a
dual-frequency ionosphere-free code combination, propagates the full marginal
position covariance across satellites, and projects the unknown epoch clock
using an orthonormal nullspace. The score retains its covariance determinant
and Gaussian normalization, projected residual and projected covariance.
Its support sidecar identifies the actual GPS epoch, PRN and two code signal
types in every prediction. Duplicate rows or sidecar disagreement are rejected.
For each prepared holdout, `predictive_support_sha256` must agree across all
candidates and both primary methods; a mismatch blocks calibration instead of
silently allowing a candidate to omit difficult observations. The two holdout
durations retain separate support identities.
Calibration averages pointwise predictive log scores; it does not treat the
correlated epochs as independent trials for confidence intervals or claim a
joint likelihood for a complete withheld block. Withheld phase arcs are not scored with known
ambiguities. Synthetic Cartesian coverage and paired intervals use independent
seeds; correlated time samples are not extra trials.

Flight validation reports corrected SLR observations independently from GNV
agreement. SLR corrections and screening are explicitly recorded. Neither a
GPS-derived comparison orbit nor sparse SLR data establishes Cartesian truth
coverage. The estimated atmospheric quantity is an **effective drag correction**.

After calibration, the campaign driver uses only CRD station headers to freeze
all date-specific SLR correction sources and their acquisition hashes before
flight evaluation fits. It does not interpret normal-point values or GNV at
this point. Both coverage patterns and the native ambiguity-resolved reference
reuse these files. Production SLR evaluation verifies this inventory and runs
offline; missing or changed correction files are errors.

The SLR predictor propagates the full marginal dynamic-parameter covariance
through the position sensitivities at reflection times, preserving correlations
between normal points. Formal SLR scores use only stations with bounded external
ILRS range-bias calibration and add each station's shared bias uncertainty.
Other station residuals are descriptive; dates without calibrated points have
no formal SLR uncertainty score. No station bias is fitted to withheld SLR.

Per-pass tables use the provider's original CRD H4/H8 sessions. The native
converter can merge several sessions into a station arc, so its arc identifier
is reported separately. Each prediction must match exactly one source station
and ground-transmit epoch within 10 microseconds; source/header hashes and UTC
session bounds are retained. Sessions with no predicted points remain explicitly
unavailable. Whole-date and station scores retain their full covariance blocks;
per-session scores are overlapping summaries and must not be added together.

## Verification

```bash
python -m pytest tests -q
ORBIT_POC_GROOPS=/tmp/orbit-v3/groops-build/groops \
  python -m pytest tests/test_comparison_native.py -q
```

The native tests execute the compiled density force and its sensitivities,
compare finite differences, and check that integration windows do not cross
knots. Separate GTSAM/QR tests check joint MAP estimates and covariance after
marginalizing nuisance variables. Neither substitutes for the end-to-end
clock/ambiguity/slip recovery and integration-refinement gates.

The [validation guide](../docs/comparison-native-validation.md#cartesian-covariance-at-actual-gnss-epochs)
includes the retained-fit command for checking covariance at GNSS epochs, plus
regressions for predictive support, missing planned seeds, checkpoint integrity
and report provenance. The [candidate 03 suite](../validation/comparison-v3/automated-tests-3b434b8c.json)
records 241 passing tests, its unchanged source snapshot and native/JUnit hashes.
The earlier [stable 74863 suite](../validation/comparison-v3/automated-tests-74863-final.json)
is preserved, as is the [168-pass run](../validation/comparison-v3/automated-tests-74863.json)
during which source files changed. These automated checks do
not replace scientific calibration and evaluation.

The frozen source fingerprint includes five generated package metadata files.
Their exact bytes are archived in
[frozen-package-metadata](../validation/comparison-v3/frozen-package-metadata/manifest.json).
To reproduce the recorded fingerprint, install dependencies first, then copy
those five files to the `source_path` locations in that manifest before
recomputing the snapshot. A fresh package installation can regenerate different
metadata without changing the numerical implementation; its fingerprint must
still be recorded as a different source snapshot.
The [execution-script archive](../validation/comparison-v3/execution-scripts/manifest.json)
also preserves the exact host-specific acceptance review and launch helpers.
Use the generic campaign commands above with your own configuration when
running on another host.

For a small serial native problem, `ORBIT_POC_LINEAR_TRACE=/absolute/prefix`
exports each linearization's actual whitened observation and constraint rows
before native normal-equation assembly, plus native increments and full inverse
entries. It requires `keepEpochNormalsInMemory` and at most 2,000 parameters.
The trace is disabled in production. These rows permit a genuinely independent
QR/GTSAM check of native MAP increments and nuisance-marginalized covariance;
factorizing GROOPS's normal matrix again would not test its assembly.
The [74863 QR/GTSAM record](../validation/comparison-v3/native-linear-74863.json)
passes the MAP, marginal covariance and full-reference prior checks for both
models. The [current synthetic pipeline rerun](../validation/comparison-v3/synthetic-functional-74863.json)
passes four one-hour fits with independent Tudat truth and matching preprocessing
and held-out support. The separate
[noiseless nuisance mapping check](../validation/comparison-v3/nuisance_mapping_74863.json)
uses matched native truth to verify clocks, physical ambiguities and retained
slip segmentation under one joint datum. None of these tests establishes
statistical uncertainty coverage.

Acceptance order is: reproduce the external example; establish model correctness;
check the GNSS pipeline and isolation; meet the numerical refinement threshold;
freeze calibration and all evaluation specifications; publish paired results,
uncertainty diagnostics and failures. In particular, refinement must change
predicted code by less than 0.003 m and phase by less than 0.00003 m at the
default synthetic noise levels. The [final development flight refinement](../validation/comparison-v3/flight-refinement-final.json)
and [separate thermal/combined refinement](../validation/comparison-v3/thermal-refinement-0p1.json)
pass with the explicit shared 0.1-second thermal setting. The carrier criterion
is a geometric bound; native IF-code and SLR changes are evaluated directly.
The scientific comparison remains incomplete until the frozen calibration and
evaluation campaign, uncertainty diagnostics and failures are reported.
