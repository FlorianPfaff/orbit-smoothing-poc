# Reproducing the native v3 checks

These are development checks, separate from the frozen 24-hour calibration and
evaluation campaign. A successful one-hour run does not close the production
numerical or uncertainty-validation gates.

**The scientific comparison is incomplete.** The development flight numerical
checks passed, and the shared campaign force model now explicitly selects a
0.1-second thermal maximum step. Calibration, frozen evaluation and uncertainty
assessment remain separate work. The native default and official upstream
reproduction template are unchanged.

Use a Python environment with this project installed, a working TudatPy
interpreter, and the pinned GROOPS build with this repository's extension.
[`scripts/build_groops.py`](../scripts/build_groops.py) builds that extension.
Use the official reduced-dynamic example directory and verified auxiliary cache
prepared by [`scripts/prepare_groops_data.py`](../scripts/prepare_groops_data.py).
Pass absolute paths to executables and existing data directories. Commands below
run from the repository root; replace the example paths with your own.

## Official external example

For the unmodified external baseline, build a separate clean checkout with
`scripts/build_groops.py --upstream-only` and the same pinned environment and
build arguments. The flag rejects a modified checkout and records a null
extension in the build manifest. Keep the extended campaign build separately.

```sh
PYTHONPATH=src python scripts/reproduce_groops_example.py \
  --archive /path/to/scenarioLeoReducedDynamicOrbit.zip \
  --groops /path/to/groops-build/groops \
  --auxiliary-dir /path/to/verified-groops-data \
  --output work/native-validation/official-example
```

This verifies the archive checksum, extracts a fresh copy, preserves the supplied
output, and runs all four official programs with only the auxiliary directory
changed. It records the executable and configuration hashes, command outcomes,
runtime, peak memory and agreement with both supplied daily orbits. The default
software-reproduction tolerances are 1 mm RMS and 3 mm maximum position
disagreement. These are engineering agreement thresholds, not accuracy claims
against independent truth. The directory must be new so reruns preserve earlier
evidence. The extended binary's build record identifies any shared physics
corrections applied to the pinned upstream version.

## Synthetic generation, fitting, and held-out prediction

```sh
PYTHONPATH=src python scripts/validate_comparison_native.py fits \
  --groops /path/to/groops-build/groops \
  --tudat-python /path/to/tudat-env/bin/python \
  --example-directory /path/to/scenarioLeoReducedDynamicOrbit \
  --auxiliary-dir /path/to/verified-groops-data \
  --cache-dir work/native-validation/cache \
  --output work/native-validation/functional \
  --epoch 2024-04-24T00:00:00 --seed 300000 \
  --orbit leo500 --atmosphere quiet --duration-hours 1 \
  --mask-seconds 1200 1800
```

This generates an independent Tudat trajectory and seeded native dual-frequency
GNSS measurements. The synthetic noise is independent Gaussian noise with
standard deviations **0.3 m for every code signal and 0.003 m for every phase
signal**, plus a seeded receiver clock and seeded cycle slips. A constant native
accuracy-definition file is shared by simulation, both estimators, and held-out
prediction. Flight processing retains the mission's official accuracy model.
Simulation injects full integer-cycle ambiguities (`wavelengthFactor=1`), so
same-frequency signals share a coherent fractional phase bias after native
preprocessing. The estimator retains its official half-cycle parameter convention.
Independent half-cycle injections on L1C and L1W are incompatible with the
native full-cycle repair and were corrected as a generator defect.

Both methods run on normal coverage and a diagnostic ten-minute holdout. The
bootstrap is rebuilt from retained GNSS observations after masking. Truth and
held-out measurements are supplied only to the evaluation function. Fit records,
native configurations, logs, covariance, parameter exports, and scores remain in
the output directory. The executable is copied and hashed before execution.
Reusing an existing fit output directory is rejected. Cached acquisition records
must agree with cached file hashes; missing public products require network access.
For a fresh fit-only rerun, add `--reuse-observations
work/native-validation/functional/normal/prepare/observations/data_manifest.json`
and choose a new output directory. This verifies the observation hashes, case,
final noise specification, and full-cycle injection convention, then repeats
masking, bootstrap, native conversion and the same nominal-force closure used
by production preparation. Both paths retain the closure history, native
execution records and hashed initialization inputs in their blind manifests.

The pulse check uses 20-minute pulses with a velocity-prior standard deviation of
0.1 mm/s. The density check uses 60-second knots, a two-hour correlation time, and
log-density standard deviation 0.3. These are diagnostic values, not calibrated
winners. `functional_gate.json` records incomplete and failed stages explicitly.
Physical ambiguity recovery is a separate check of the native phase-recovery
export. Raw decorrelated ambiguity coefficients cannot be compared directly with
injected ambiguities because preprocessing offsets and phase-bias gauges differ.

The production retention mode can be checked against the masked diagnostic fits:

```sh
PYTHONPATH=src python scripts/validate_comparison_native.py compact \
  --groops /path/to/groops-build/groops \
  --fit-directory work/native-validation/functional/masked \
  --output work/native-validation/compact
```

This reruns both blind fits with production retention, requires bitwise equal
state/covariance arrays, verifies every retained artifact hash, and predicts
held-out code after redundant native files have been removed. Generation also
prunes reproducible intermediate truth/orbit/receiver files in production mode;
the retained GPS1B, attitude, and evaluation NPZ remain verified inputs. Deletion
audits preserve the removed files' hashes and sizes. Diagnostic runs keep these
intermediate files for physical-observable recovery checks.

## Cartesian covariance at actual GNSS epochs

The UTC propagation grid and retained GPS observation epochs do not coincide.
The native `outputfileCovarianceObservationEpochs` export evaluates the position
and velocity design matrices at every nominal GNSS epoch, including withheld
epochs, then forms `J P Jᵀ` using the nuisance-marginalized dynamic-parameter
covariance. Calibration consumes those marginals. Taking the nearest state
covariance or interpolating covariance blocks is not equivalent.

For a small converged fit made with `backend.retain_native_diagnostics=true`:

```sh
PYTHONPATH=src python scripts/check_observation_covariance.py \
  --binary /path/to/the-exact-fitted-groops-binary \
  --fit-directory /path/to/small-retained-fit \
  --maximum-parameters 128 \
  --output work/native-validation/observation-covariance
```

The fit directory must retain `request.json`, `result.json`, its native fit
configuration, final variational file, dynamic-parameter covariance and
observation-epoch covariance. The checker verifies artifact hashes and requires
the probe executable to match the fitted executable's SHA256. It independently
probes each linearized dynamic column with positive and negative parameter
vectors, then computes `J P Jᵀ` in Python, retaining all cross terms. Its maximum
entrywise error normalized by `sqrt(C_ii C_jj)` must be below `1e-6`.

The [one-hour April 24 UTC pulse check](../validation/comparison-v3/utc_small_fit_observation_covariance.json)
tested 12 dynamic parameters and 120 GNSS epochs, all off the state grid. Its
maximum normalized covariance discrepancy was `5.25e-10`; fit and probe used
the same `74863…` executable. The [full-day export check](../validation/comparison-v3/utc_observation_covariance.json)
also verified all 2,880 nominal epochs, including the 240 blackout epochs, for
normal and masked inputs. That full-day record is a one-iteration export check,
not a converged flight result. These checks validate epochs, column ordering and
covariance propagation. The evaluator shares native interpolation semantics;
the [74863 QR/GTSAM check](../validation/comparison-v3/native-linear-74863.json)
tests the inverse normal system. None establishes nonlinear uncertainty coverage
or replaces the physical-force refinement checks.

The QR/GTSAM check can be repeated for each retained small pulse/density fit:

```sh
PYTHONPATH=src python scripts/check_native_linear.py \
  --binary /path/to/the-fitted-groops-binary \
  --fit-directory /path/to/small-retained-fit \
  --output work/native-validation/linear-check
```

It exports actual weighted observation and constraint rows before native
normal-equation assembly. Independent GTSAM and pivoted QR solutions check the
native increments and nuisance-marginalized covariance; analytic checks also
verify the full-reference pulse and OU prior rows. The `74863` record passes all
required checks for both models. This is a local linear-system check, not a
comparison of scientific orbit accuracy or nonlinear posterior calibration.

### Covariance after nonlinear convergence

Common preparation first closes a nominal-force trajectory. The retained-GNSS
bootstrap supplies one six-state starting estimate, after which repeated native
force evaluation holds that physical initial state fixed until the largest
trajectory change is below 2 micrometres in position and 3 nanometres/second in
velocity. This removes dependence on the artificial curve used to bridge a
tracking gap. The state is fixed only during numerical closure: both final GNSS
estimators subsequently re-estimate all six components. Closure adds no
observations, state prior, pulse, or density parameter. The immutable bootstrap
still supplies common receiver preprocessing geometry. Inputs, numerical
controls, closure history and native executable hashes are retained per mask.

Closure alone does not ensure nonlinear convergence. In the [preserved April 24
blackout diagnostic](../validation/comparison-v3/nominal-closure-diagnostic-74863.json)
it reduced the first log-density update from 17.82 to 2.652,
but the undamped solve then approached a two-cycle: successive update directions
had cosines approaching -1, updates near 2.15 and orbit changes near 3 metres.
That result is a failed fit, regardless of the old wrapper's covariance flag.

The density wrapper therefore bounds an accepted log-density increment to 0.5
and uses a relaxation factor of at most 0.5 for the remainder of a solve after
consecutive undamped directions have cosine below -0.25. The same factor is
applied to the physical initial-state displacement. A native variational
evaluation produces the corresponding accepted trajectory at unchanged native
epochs. Each accepted force multiplier changes by at most `exp(0.5)`, while
successive steps can reach any log-density value. This is numerical adaptive
relaxation, with no guarantee of monotone
objective reduction. It never clips accumulated log density, changes OU prior
rows, or adds fitted stochastic forces. The density iteration budget is 32;
pulse fits retain 12. Every raw step and accepted factor is recorded. These
source-versioned numerical settings must be frozen before calibration.

Convergence uses the original thresholds on the **undamped** native log-density
update and proposed orbit change. A small damped step cannot certify convergence.
The final confirmation is undamped and computes covariance under the original
model; its full update must independently satisfy the thresholds. Nonconvergence
continues to be reported as a failure.

The wrapper/controller and exact-affine fit-loop regression tests check scaled
initial-state and density updates together, the unchanged prior configuration,
raw convergence criteria, and final reference-density/posterior-density pairing.
They also reject a large undamped confirmation update or absent, indefinite, or
epoch-misaligned final covariance. Reproduce the retained blackout failure with
the same blind request, preparation, native binary and statistical settings:

```sh
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python scripts/check_density_damping.py \
  --request /path/to/retained-density-fit/request.json \
  --output work/native-validation/density-damping
```

The two primary methods now omit covariance inversion and covariance exports
from intermediate outer iterations. Those iterations retain the same native
MAP estimation sequence and test orbit/log-density updates. A candidate that
meets those criteria triggers the existing extra confirmation iteration, which
computes the full native inverse and both dynamic-grid and GNSS-epoch Cartesian
covariances after the final parameter update. Acceptance requires that this
confirmation also converges and its marginal blocks pass the original
positive-definiteness checks. The native ambiguity-resolution reference keeps
its original per-iteration processing sequence.

Intermediate records explicitly mark covariance as not computed. Failed or
nonconverged fits retain runtime, iteration history and the last readable MAP
state/parameter diagnostic, without creating a covariance-bearing posterior.
Old covariance files are removed before a covariance-producing execution, so
they cannot rescue missing final output. This scheduling change does not lower
the memory needed for the final covariance calculation.

The bounded native equivalence replay accepts one or more retained one-hour
fits that previously computed covariance at every iteration:

```sh
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python scripts/check_deferred_covariance.py \
  --groops /path/to/the-exact-baseline-groops-binary \
  --fit-directory /path/to/retained-one-hour-fit \
  --output work/native-validation/deferred-covariance
```

It checks every final state/covariance array, native covariance and parameter
file bytes, and outer update sequence against the baseline, while recording
the old and new source identities. It does not infer a campaign speedup from
the separate runs. Scheduling, missing final output, failed inversion, invalid
covariance and unsuccessful confirmation paths also have focused tests in
`tests/test_comparison_deferred_covariance.py`.

The [persistent-storage replay](../validation/comparison-v3/deferred-covariance-74863.json)
passes for both primary methods under normal tracking and a ten-minute synthetic
blackout. All final arrays and native output files are exactly equal, and all
four MAP update sequences match. The every-iteration baseline uses an isolated
copy of the same source with only its covariance scheduling switch changed;
the record includes that patch and both source identities. The earlier local
replay lost its temporary files during an environment restart and is not used
as acceptance evidence. No campaign speedup or accuracy claim follows from
these four engineering comparisons.

## Calibration support and report integrity

Held-out scores must use identical observations for every candidate and primary
method on a prepared holdout. The native predictor records GPS epoch, PRN and
the actual first/second code signal types. Duplicate epoch/PRN rows, disagreement
between the support sidecar and prediction rows, or a changed
`predictive_support_sha256` across candidates or methods is rejected. A support
mismatch blocks calibration rather than becoming an ordinary excluded fit.
The 30-minute and two-hour holdouts have separate support identities.
The [UTC held-out geometry check](../validation/comparison-v3/utc_prediction_geometry.json)
records 2,128 prediction/support rows over 240 epochs; it is a functional check,
not a calibrated score or orbit-accuracy result.

Campaign manifests retain the frozen planned cases. Reports use those cases for
paired-seed and fixed-epoch coverage denominators, including a missing seed when
neither method produced a row. Intervals use valid independent paired seeds;
missing and failed fits remain explicit. Wilson coverage intervals use valid
outcomes and list unavailable planned seeds separately. Blackout metrics are
not applicable to normal-coverage cases and are not counted as failures.

Each job keeps its complete `result.json`, with a compact `result-record.json`
index containing the exact path, SHA256, identity, status and timing. Campaign
checkpoints store these indexes instead of copying per-epoch residual and
covariance arrays. Full scores and failed-result details remain in the job's
files. Resume verifies result bytes before accepting a cached status; reports
load needed results through the same hash checks. A terminal checkpoint without
its saved index cannot be safely resumed.

`orbit-poc comparison report` also requires the run's protocol/source hashes,
stage, campaign and selection hash to match the active freeze and completed
calibration, whose evidence is verified again. A copied run from another source
or selection cannot be combined with the current calibration. Direct
`comparison.report.create_report` rendering of historical inline development
manifests remains available separately; it is not a production protocol check.

Focused regression checks can be run without a native process:

```sh
PYTHONPATH=src python -m pytest -q \
  tests/test_comparison_protocol.py tests/test_comparison_metrics.py \
  tests/test_comparison_backend.py
```

The [stable 74863 suite](../validation/comparison-v3/automated-tests-74863-final.json)
records the exact runtime source snapshot, native SHA, JUnit hash and optional
archived-fixture skip. The earlier [168-pass run](../validation/comparison-v3/automated-tests-74863.json)
is preserved with its two differing source snapshots. A passing suite validates
the recorded implementation; it is not the scientific campaign.

## Production campaign driver

Use the maintained driver after completing the acceptance checks and placing
their hash-linked `acceptance-gates.json` in the configured run directory:

```sh
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python scripts/run_comparison_campaign.py --config work/v3/config.json \
  --synthetic-workers 24 --flight-workers 24
```

Start from `configs/comparison-v3.json`, set the local native binary, source,
data-cache, auxiliary, example and separate Tudat interpreter paths, and choose
a new output directory before freezing. If the binary uses staged shared
libraries, set `LD_LIBRARY_PATH` to their directory. The driver verifies the
existing acceptance evidence; it does not create passing gate records.

The driver runs synthetic calibration and evaluation before starting flight
calibration and evaluation. For each stage, it freezes the selected
hyperparameters, then prepares **all** evaluation inputs before any evaluation
fit: 800 primary plus 10 stress synthetic cases, or 12 primary plus six
ambiguity-resolved flight cases. The complete prescribed campaign therefore
has 1,620 synthetic evaluation fits and 30 flight evaluation fits; exclusions
and failures remain explicit. Initial calibration has 1,536 synthetic and
384 flight fits before any required boundary expansion.

`evaluation-input-freeze-<stage>.json` pins the protocol, source, native binary,
driver and calibration selection, every prepared result and index, raw/derived
input files, acquisition/generation manifests and the converted native inputs
and XML configurations. For flight, a date-specific SLR auxiliary preflight reads
only CRD H2 station identifiers after calibration, then pins all station,
Earth-rotation, tide, ephemeris, ILRS bias and reflector-documentation files and
their acquisition records. It does not parse normal-point values, calculate
residuals or interpret GNV. The complete correction inventory is included in the
evaluation freeze; frozen evaluators verify it and run offline. Missing or
modified corrections fail the evaluation instead of being fetched or replaced.
Reference products remain evaluation-only. The driver verifies this inventory again before each primary or secondary run, and refuses
to overwrite a changed freeze or reuse an altered input. Interrupted preparation
resumes its verified job records; a partial preparation is not an input freeze.

The driver first prepares one case per date serially to populate verified shared
download caches, then prepares the remaining private case directories concurrently.
It preserves the planned case order in every input inventory. Before preparation,
calibration or evaluation, the driver measures Linux `MemAvailable`, reserves 8 GiB, and budgets 3.5 GiB per
worker, up to the requested maximum of 24. It records available/total memory,
the estimate and actual worker count in `driver-<stage>.json`. Insufficient
memory stops the launch. This planning guard is not a hard RSS limit. Each
command receives a 168-hour budget for starting jobs and retains the runtime's
individual native-command timeout. The top-level completion status means all
planned commands completed; scientific acceptance and unavailable SLR remain
separate reported outcomes.

The driver is included in the runtime source snapshot. Editing it after a
protocol freeze requires a new output directory. Direct `orbit-poc comparison`
subcommands remain available for development; use this driver for the production
sequence and complete evaluation-input freeze. Its isolated regression tests
do not launch numerical jobs:

```sh
PYTHONPATH=src python -m pytest -q tests/test_comparison_campaign_driver.py
```

## Fixed fitted-state refinement

```sh
PYTHONPATH=src python scripts/validate_comparison_native.py refine \
  --groops /path/to/groops-build/groops \
  --tudat-python /path/to/tudat-env/bin/python \
  --fit-directory work/native-validation/functional/normal \
  --coarse-step 5 --fine-step 2.5 \
  --output work/native-validation/refinement
```

This independently regenerates the two Tudat reference grids, then executes
native force integration at each resolution. It holds the fitted physical initial
state and pulse coefficients or posterior density curve fixed. The native helper
reanchors the six initial-state columns linearly; this approximation is explicitly
part of the diagnostic. Truth geometry is used only in this numerical check, never
in the estimator bootstrap or fit.

The script compares both the common 30-second epochs and the native shared
boundary-aware degree-7 interpolation: each 60-second knot, its plus/minus 0.123
second neighbours, and every coarse-grid midpoint. Pulse epochs use the
post-pulse velocity. The maximum Euclidean position difference must be below
30 micrometres, a conservative geometric carrier-range bound; the code bound is
3 millimetres. This does not independently validate every GNSS correction,
clock linearization, or flight-data model. Aligned-epoch agreement alone is
insufficient near velocity pulses.

## Broader prescribed-force refinement without GNSS downloads

```sh
PYTHONPATH=src python scripts/validate_comparison_native.py physics \
  --groops /path/to/groops-build/groops \
  --tudat-python /path/to/tudat-env/bin/python \
  --fit-directory work/native-validation/functional/normal \
  --epoch 2024-04-24T00:00:00 --duration-hours 24 \
  --orbits leo300 leo500 leo800 eccentric \
  --atmospheres quiet disturbed \
  --coarse-step 5 --fine-step 2.5 --pulse-amplitude-m-s 0.01 \
  --output work/native-validation/physics
```

The existing fits supply only native configuration templates and cached auxiliary
paths. This diagnostic does not fit new GNSS data. Each orbit/atmosphere pair gets
independent fine/coarse Tudat reference grids. Both native resolutions use exactly
the same physical initial state and deterministic prescribed pulse vector or
60-second density curve. The pulse amplitude covers the largest initial tuning-grid
standard deviation; it is not a claim about fitted pulse magnitudes. Results are
checkpointed after each method in `physics_refinement.json`, including failures.

## Published evidence and raw locators

Compact records are under [`validation/comparison-v3`](../validation/comparison-v3/).
Paths beginning `raw-artifacts/` are **documented relative locators**, not files
included in the curated repository. They refer to the native XML, NPZ, matrix,
instrument, and log files produced by the commands above. Byte hashes refer to the
original evidence bytes; relocation does not imply that new runs are bitwise
identical across native builds or platforms.

The `prototype-*` records used the official angle-dependent GRACE-FO accuracy
pattern before the constant synthetic noise correction. They remain historical
development evidence, not acceptance evidence for the final synthetic specification.
Their raw locators use `raw-artifacts/prototype-functional/{normal,masked}` and
`raw-artifacts/prototype-refinement-{aligned,offgrid}`. New runs should use the
current command defaults. One-hour results, prescribed-force checks, physical
ambiguity recovery, and the full production campaign must be reported separately.

`unsegmented-physics-24h.json` preserves a failed diagnostic from the original
interpolator. All eight prescribed pulse cases exceeded the 30-micrometre limit
off-grid, despite much closer agreement at aligned epochs; all eight density
cases passed. This evidence motivated the shared boundary-aware interpolation
change. The raw locator is `raw-artifacts/unsegmented-physics-24h`.

The [`synthetic-functional.json`](../validation/comparison-v3/synthetic-functional.json)
record contains four successful one-hour fits/evaluations using constant noise,
coherent full-cycle injections, and the canonical native bootstrap time grid.
Physical ambiguity recovery remains a separately recorded check. Earlier
constant-noise half-cycle runs are preserved in `half-cycle-functional.json`
and `half-cycle-fitted-refinement.json` as historical development evidence.
The [current 74863 functional rerun](../validation/comparison-v3/synthetic-functional-74863.json)
also passes all four normal/masked pulse/density fits with independent Tudat
truth. It verifies the updated receiver geometry, GNSS-epoch covariance and
native held-out support identity; both primary arms have identical preprocessing
and predictive support for each mask. Its one-hour results are not calibration
or held-out scientific evaluation results.

A [fresh persistent-storage regeneration](../validation/comparison-v3/synthetic-functional-closure-74863.json)
also passes all four fits after shared nominal-force closure and final-only
covariance scheduling. It regenerates independent Tudat truth and the GNSS
observations, confirms equal preprocessing and held-out support between arms,
and records the exact `c8d7` Python source and `74863` native identities. These
raw outputs are retained on the named remote host instead of temporary storage.

The [74863 noiseless nuisance check](../validation/comparison-v3/nuisance_mapping_74863.json)
separately passes all four fits under a matched native truth model. With one
joint global clock/phase datum, maximum clock and physical ionosphere-free
ambiguity discrepancies are 0.507 mm and 1.211 mm; the largest retained slip-jump
error is 0.364 mm, below the declared 2 mm mapping tolerance. Retained tracks
cross no injected slip, and missing or short segments remain documented. Truth
is used only for this post-fit diagnostic. This verifies parameter/measurement
mapping, not statistical nuisance-parameter coverage. The earlier `aef8`
evidence and its physical-observable archives remain preserved separately.
The [`compact-retention.json`](../validation/comparison-v3/compact-retention.json)
check confirms that both production-retention reruns preserve bitwise identical
state/covariance arrays and successful held-out scores after pruning.
[`fitted-refinement.json`](../validation/comparison-v3/fitted-refinement.json)
records the corresponding numerical check. The broader
[`physics-refinement-24h.json`](../validation/comparison-v3/physics-refinement-24h.json)
passes all 16 prescribed-force checks after the interpolation correction, with a
maximum off-grid position difference of 25.379 micrometres. The explicit
[`aef8 binary record`](../validation/comparison-v3/physics-refinement-24h-aef8.json)
repeats all 16 checks after the density-knot epoch correction; the older
`physics-refinement-24h-d5e8.json` is retained for provenance. This evidence covers
the declared synthetic forces, not subsequent flight atmospheric-event changes.
These raw locators are
`raw-artifacts/coherent-functional`, `raw-artifacts/coherent-fitted-refinement`,
and `raw-artifacts/physics-aef8-24h`, respectively.

## Upstream thermal endpoint correction

The extension applies `native_thermal.py` to the pinned GROOPS radiation-pressure
implementation. Its original thermal Euler loop always took a full one-second
step, including when only half a second remained before a requested 2.5-second
force epoch. That both advanced the thermal state beyond the requested time and
extrapolated absorbed pressure. The patch clips the last step to the remaining
interval; the thermal model is unchanged. The optional
`radiationPressure/orbitPocThermalMaximumStep` controls the maximum Euler step;
the native default remains one second. The isolated integer-step arithmetic
matches the old algorithm, but this does not establish bitwise equivalence of
complete native runs: floating-point native epochs can affect endpoint tests.
Both inference methods use this corrected implementation. The resulting binary
is an extended, corrected GROOPS build, not an unmodified upstream executable.

`tests/test_comparison_thermal.py` compiles and exercises the installed C++ step
helper, checks exact fractional endpoints, verifies integer-second equivalence,
and checks idempotent application of the pinned source patch. These focused tests
do not replace the full physical-force refinement gate. The initial 24-hour
Apr24 full-force gate failed at millimetre scale; removing radiation alone did
not resolve the discrepancy. Those failed attempts remain preserved. Subsequent
atmospheric, attitude and thermal checks resolved the numerical discrepancies
without changing the acceptance thresholds.

Thermal refinement is tested independently at fixed state-grid geometry and
absorbed-pressure endpoints:

```sh
PYTHONPATH=src python scripts/check_thermal_refinement.py \
  --binary /path/to/groops-build/groops \
  --reference-config /path/to/fixed-flight-refinement/evaluate.xml \
  --steps 0.1 0.05 \
  --output work/native-validation/thermal-refinement
```

This command isolates thermal discretization. The preserved
[0.5-to-0.25-second diagnostic](../validation/comparison-v3/thermal-refinement-0p5-diagnostic.json)
failed the 30-micrometre bound at 64.674 micrometres. Sharing a thermal step
between two state grids is therefore insufficient. Separate state-grid and
atmospheric-mesh checks, native observable comparisons, and the
[combined state/thermal comparison](../scripts/check_combined_refinement.py)
must also agree; a thermal-only result is insufficient.

The [final flight refinement](../validation/comparison-v3/flight-refinement-final.json)
passes both models on the 24-hour April 24 development reference with the
selected 0.1-second thermal maximum step. It separately refines the state grid
from 5 to 2.5 seconds and the atmospheric maximum spacing from 1 to 0.5 seconds,
holding the fitted physical initial state and force parameters fixed. Maximum
changes across those checks were 11.969 micrometres in off-grid position,
12.398 micrometres in native IF code and 5.326 micrometres in native SLR. The
carrier check uses the conservative geometric position bound, not a native
carrier-phase residual export.

The [independent thermal and combined checks](../validation/comparison-v3/thermal-refinement-0p1.json)
also pass: 0.1-to-0.05-second thermal refinement changes off-grid position by at
most 13.279 micrometres; simultaneously refining state and thermal settings
changes it by at most 24.438 micrometres. Both are below the unchanged
30-micrometre geometric bound. This is development numerical acceptance at
fixed fitted parameters, not demonstrated orbit accuracy, calibrated uncertainty
or a result from the frozen May evaluation dates.

The dominant initial flight discrepancy was isolated to atmospheric drag:
removing radiation left an 8.205-millimetre maximum difference, whereas removing
drag as well reduced it to 5.21 micrometres. `native_atmosphere.py` therefore
integrates the unchanged drag samples separately across exact hourly UTC driver
events. Each side uses its own polynomial samples, including fractional intervals
when the event is off-grid. The daily solar and three-hour wind-index steps are
included, along with hourly DTC slope changes. It also detects each orbit's
local-solar-midnight crossing using the native JB2008 longitude, Sun position,
and sidereal-time convention. The unchanged JB2008 local-time polynomial has
a discontinuity at that join. A bracketed native-time root search locates each
crossing to 0.1 microsecond.

When an event and a continuous density knot form an interval with fewer than
eight native samples, eight distinct interior quadrature epochs are added.
Only smooth reference geometry is interpolated; the native atmospheric force
and density derivative are evaluated again at those epochs. This avoids both
interpolation across a force jump and ill-conditioned duplicate sample nodes.
The log-density sensitivity integrals use the same event quadrature rule.
Archived indices and the JB2008 local-time join are not smoothed. Focused tests
cover off-grid jumps, a segment containing no native samples, knot-adjacent
slivers, and native local-midnight crossings in both directions.

The atmospheric quadrature has its own declared maximum spacing (default one
second), independent of the output-state grid. All of its force/design samples
are genuinely evaluated on that separate mesh. The known attitude curve uses
the same canonical five-second quaternion support on both state grids, without
averaging; each five-second polynomial-stencil join is an integration boundary.
Short segments use at least eight interior samples, so the default can be denser
than one second (eight interior nodes in a five-second segment are 0.625 seconds
apart). This is not a claim of exactly 86,401 daily force evaluations.

The full-flight gate independently compares state grids of five and 2.5 seconds
at the same force setting, then force maximum spacings of one and 0.5 seconds at
the same state setting. Passing only the first comparison cannot establish force
quadrature accuracy. Both comparisons require the original geometric and native
GNSS/SLR observable tolerances, with fixed physical initial state and fitted
force parameters. Native process runtime and peak RSS are measured directly.

Native propagated sensitivities retain GROOPS's low-degree gravity-gradient
approximation for state perturbations. Direct log-density force derivatives are
exact at the reference geometry, but the state-transition equations omit the
full drag position/velocity derivatives and other small force gradients. Both
methods share this approximation. Their reported covariances are consequently
local linearized covariances under the stated native model and fixed tuning
parameters; force-derivative tests alone do not validate the entire nonlinear
trajectory Jacobian.

The [current UTC-day derivative diagnostic](../validation/comparison-v3/density-trajectory-derivative-74863.json)
checks one six-hour density knot on the converged April 24 normal-coverage fit.
Both fit and diagnostic use native `74863`, a 0.1-second thermal step and
one-second atmospheric quadrature. The fit source is `4aad`; the later
diagnostic source is `c8d7d8dc`, with the corrected UTC origin applied exactly
once. Each perturbed trajectory independently re-evaluates all forces until
fixed-initial-state closure. Central differences at 0.05 and 0.025 log-density
units are combined by Richardson extrapolation. The largest position-derivative
discrepancy is 0.6484 millimetres per unit log density (0.02667% of the largest
finite-difference derivative); the step-halving Richardson correction is
0.1189 millimetres/unit and the observed pre-support cancellation floor is
6.31 micrometres/unit. These quantify this one approximation check, not a global
Jacobian error bound or evidence that posterior uncertainty is calibrated.

Reproduce it against a retained converged development result with the exact
same native binary:

```sh
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python scripts/check_density_trajectory_derivative.py \
  --binary /path/to/the-fitted-groops-binary \
  --result /path/to/retained-density-fit/result.json \
  --output work/native-validation/density-trajectory-derivative \
  --knot-hours 6 --step 0.05 --workers 4
```

## April 24 post-fit SLR session reporting check

The [original engineering evaluation](../validation/comparison-v3/flight_postfit_74863.json)
exercised the native corrected SLR predictor, its correlated covariance, and
separate GNV agreement after the normal April 24 pulse fit converged. It remains
preserved. Its original `per_pass` labels represented native station arcs, which
can merge multiple provider sessions.

The [reporting-only rerun](../validation/comparison-v3/flight_postfit_crd_sessions_74863.json)
fixes that interpretation using source CRD sessions. All 80 native prediction
rows map uniquely to their station and source ground-transmit epoch, with maximum
matching error 0.314 microseconds against a fixed 10-microsecond tolerance.
Eleven original sessions are reported; ten contain retained predictions. The
remaining station 7090 session contains five points below the predeclared
20-degree elevation cutoff, retained in the inventory as unavailable. Its
exclusion is supported by the original geometry-only audit, without residual
selection.

The original fit source hash is `4aad3ac1117420812c0922c80b7a1d1b51046cad08dd6b0fcd06e3e8c077a92e`.
The isolated post-fit reporting source hash is
`fb04bb58dbd9531c27a598302999877bf761da1cc34a349e903407c3c0eb2348`;
only `slr.py` and the backend's session-metadata arguments differ. Native
prediction and full covariance files are byte-identical to the original
engineering evaluation. Whole-day, station, date and geometry scores, and GNV
agreement, are exactly unchanged. An independent source-session reconstruction
reproduces the eligible 17-point session's full correlated Gaussian score to
`1.5e-14` in NLL.

This is an engineering codepath check, with no orbit refit or May data. The
April 24 post-fit GNV access is explicitly recorded as an extension of the
already disclosed development diagnostic. It cannot inform calibration settings
or establish scientific accuracy or uncertainty coverage.


## SLR correction input freeze

The [SLR freeze regression record](../validation/comparison-v3/slr-correction-freeze-tests.json)
checks metadata-only acquisition, complete transitive correction inventories,
resumption without downloads, offline predictor configuration, date-specific
campaign binding, and rejection of changed sources or acquisition records. It
also checks that physical SLR unavailability still preserves separate GNV
agreement. Its CRD/GNV fixtures contain deliberately nonnumeric observation
content; no flight observations are opened or downloaded by these tests.

The driver stores one `slr-auxiliary-freeze/<date>.json` per retained flight date.
Both coverage patterns and the integer-ambiguity reference reuse that correction
manifest. All header stations are frozen, including stations later excluded by
post-fit fixed quality rules. Native CRD quality screening, externally bounded
station-bias selection, pass mapping and residual calculation remain evaluation
operations. Direct development evaluations may acquire corrections explicitly;
production `frozen_evaluation` calls require the full campaign input freeze and
cannot fall back to online acquisition.
