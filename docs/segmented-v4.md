# v4 segmented orbit estimation

This version adds a separate numerical benchmark and a lifted, segmented linear solve for the two existing disturbance models. It preserves the shared nonlinear objective, physical force model, fixed observation weights, full accumulated pulse/OU penalties and local Gaussian uncertainty convention. The legacy numerical path remains the compatibility default.

The implementation and local tests do not establish a completed native benchmark. The checked-in configuration intentionally contains missing artifact pins. Preparation records a blocked status until the required corrected reference, runtime binaries, source inventories, input catalog or preparation dependencies, prior seed protocols and admission evidence are supplied. No native validation result, speedup or accuracy improvement is implied by configuration or report generation.

## Commands and fixed matrix

```sh
orbit-poc segmented prepare --config configs/segmented-v4.json
orbit-poc segmented validate --config configs/segmented-v4.json
orbit-poc segmented run --config configs/segmented-v4.json
orbit-poc segmented report --config configs/segmented-v4.json
```

`run --max-attempts N` executes at most N new attempts in frozen order; it does not change the matrix. A terminal failed attempt is retained on resume. An interrupted directory without a matching completed checkpoint blocks automatic reuse. Use a distinct reviewed attempt rather than overwriting it.

The independent strict JSON configuration rejects unknown keys, duplicate keys, wrong types, changes to the registered profiles or frozen numerical controls. Existing comparison/numerics configuration validation is unchanged.

| Setting | Fixed selection |
|---|---|
| Synthetic orbit/seed | leo500/610000 and eccentric/610001 |
| Atmosphere/coverage pairs | quiet/normal; disturbed/daily 11–13 UTC blackout |
| Synthetic methods | inertial pulses, 1,200 s, sigma 1e-4 m/s; log density, 60 s knots, tau 1,800 s, sigma 0.1 |
| Retained flight settings | original pulse settings above; original density tau 7,200 s, sigma 0.3 |
| 24-hour synthetic profiles | corrected dense, 1-hour segments, 4-hour segments: 24 attempts |
| 48-hour synthetic profiles | corrected dense and 1-hour segments: 16 attempts |
| 72-hour synthetic profiles | corrected dense and 1-hour segments: 16 attempts |
| Flight | April 24, 2024; normal/blackout × both methods × all three profiles: 12 attempts |
| Total | exactly 68 attempts, 28 prepared method cases |

One continuous 72-hour truth/measurement realization is generated per synthetic orbit/atmosphere combination, giving four generations. Its 24- and 48-hour arcs are prefixes. Both disturbance models and all solver profiles share the same retained observations and preparation. Shared seeds, coverage variants and prefixes are dependent observations, not independent statistical trials. The seeds must be absent from every explicitly pinned previous protocol; preparation also checks published historical seed ranges.

## Native multi-day preparation

The new `segmented.multiday` adapter extends the daily preparation code without relaxing the old daily limits. It acquires every daily precise GPS orbit, clock, attitude and bias product across the arc plus at least one hour of interpolation support at both ends. Provider records are stitched by GPS epoch; the later day wins exact duplicate epochs. Every daily source and merged file is hashed. A separate pinned audit records overlap differences, boundary sample gaps, quaternion sign equivalence and daily OSB changes without modifying products or inserting ambiguity resets. The complete native data-directory membership, file contents and symlink targets are sealed as well, so adding a wildcard-visible transmitter file invalidates the preparation. Prefix masks are applied before GNSS-only initialization and before native cycle-slip, ambiguity-arc and observation processing.

GROOPS's SINEX bias converter supports a single time-fixed signal-bias datum. Synthetic generation and inference therefore use the same explicit first-day OSB datum; every daily bias product is retained and checked, but time-variable BSX entries are not silently treated as supported. Flight observations retain the existing known daily-to-primary OSB normalization. Native receiver clocks, float ambiguities and signal biases remain nuisance parameters. No ambiguity reset is inserted merely because a product day changes.

The synthetic time coordinate is the existing GPS-midnight convention. UTC blackout boundaries use the fixed 2024 GPS–UTC offset of 18 seconds. Flight uses its existing UTC arc with 18-second GPS offset. Sampling stays on the original 30-second GPS observation grid. Continuous generator and fitting XML have one complete arc interval; they do not loop over independently initialized daily fits.

Preparation uses sixteen bounded component jobs: four continuous generators and twelve prefix/mask preparations. Each has a separate two-hour supervision limit, immutable request/runtime/source identity, exact output-directory inventory and successful checkpoint. There is no two-hour catalog-wide limit. Matching completed components can resume; a partial or failed component remains untouched and requires explicit recovery in a new reviewed output. The complete 28-request catalog and 68-attempt manifest are sealed only after all components and retained-flight wrappers verify.

Each unique synthetic prefix/mask gets a fresh code-only SPP bootstrap, central/J2 gap initialization, native conversion and nominal physical trajectory closure. These are numerical starting values, not additional observations. Truth remains in the separate generation/evaluation output and is removed from fitting requests. The Tudat interpreter path and SHA256 are explicit preparation pins. Missing Tudat, native executables, products or closure outputs cause explicit failure. There is no approximate measurement or propagation fallback.

Flight is always read from the exact original April24 normal/blackout requests and native preparations in the pinned original 150-attempt plan/manifest. It is never downloaded, regenerated, remasked or initialized again by this adapter. Its original density settings are tau 7,200 s and sigma 0.3; the fresh synthetic settings remain tau 1,800 s and sigma 0.1. A separate wrapper adds only complete native-directory membership and historical provenance to the old blind preparation. The wrapper leaves observations, daily products, trajectory initialization, masks, weights and all other preparation fields unchanged. The two historical blackout normalization receipts have different bias-file path strings; their complete scientific ledgers are compared after verifying the nested bias-file bytes and removing only those path strings. All formulas, corrections, policies, arcs and bias digests remain in the semantic comparison, and both original receipt hashes remain pinned. `flight_input_catalog` uses schema `orbit-poc-segmented-flight-inputs-v1` with `original_plan` and `original_manifest` artifact pins.

The synthetic preparation adapter can run from pinned prebuilt input requests instead of regenerating data. The catalog schema is `orbit-poc-segmented-input-catalog-v1`, containing exactly the 28 case IDs and a `{path, sha256}` artifact for each request. Each request fixes its stage, case, method, parameters, shared model/mask hashes and blind native-preparation artifact. Nested daily product pins are verified on preparation and resume.

## Runtime and execution identity

Both profile Python source roots contain the pinned v4 harness and shared corrected Python model. The dense native executable remains the archived corrected c24 reference, identified by the independently audited v3.1 correctness receipt. The segmented runtime additionally pins its native segmented solver executable. A dense fit may use the pinned v4 GROOPS executable only as a post-fit diagnostic to export the accepted native variation operator for cross-covariance queries; it does not refit, propagate or change the dense physical trajectory. Its identity and timed cost are retained. Source snapshots, interpreter files, GROOPS build manifests and complete mandatory shared-library/runtime inventories are verified before use. A build manifest's `executable_sha256` identifies the native GROOPS binary.

The immutable plan fixes all 68 attempts before any result is inspected. Preparation then seals exact input and runtime hashes in `manifest.json`. A changed source, request, scientific configuration, input or runtime requires a new output directory. Post-execution release evidence and the original 150 completion report/plan/manifest pins are reporting attachments, excluded from the execution-plan identity. The separate `flight_input_catalog` also pins the original plan and manifest as execution inputs, because the four retained April24 requests define flight benchmark inputs before execution; those pins cannot be changed by a later reporting attachment. Each distinct attachment set is written to an append-only `reporting-inputs/<hash>.json` index. Use deployment configuration outside the pinned source tree so attaching later evidence does not edit pinned source files. The original v3.1 frozen 150-attempt campaign is separate and cannot accept substituted binaries or results from this campaign.

Execution is serial, one reserved CPU set and one thread per fit, with a two-hour wall limit and 8 GiB sampled process-tree RSS limit. Admission requires the current host/boot, an explicitly reserved CPU set, no conflicting workloads, at least 8 GiB additional available memory and 32 GiB free output storage. These are numerical/resource controls, not statistical priors. The harness preserves the request, worker log, status, elapsed wall time and peak sampled RSS for every attempt. Each worker has a dedicated subreaper that adopts orphaned descendants, including children that create a new session. Cleanup signals only exact owned process identities through kernel pidfds after start-tick verification. Success also requires the dedicated supervisor to receive the kernel `waitpid` no-child (`ECHILD`) certificate; an empty `/proc` scan is insufficient. Unverified cleanup stops the campaign and blocks further jobs; the shared controller never sweeps unrelated descendants.

The nonlinear controller retains the existing 32 accepted iteration / 96 total trial limits, initial damping 1e-3 and gain-ratio threshold 1e-4. Damping never enters accepted covariance. Final acceptance requires a fresh undamped correction and strict nuisance convergence: position change <30 µm, log-density update <1e-4 or pulse update <1e-8 m/s, and normalized scaled gradient <1e-8. Small damped steps, iteration exhaustion and numerical-floor-limited nuisance progress are not convergence.

## Executed prebenchmark validation

`validate` can run before the expensive 68-case preparation. It freezes a separate validation context over the exact execution plan, source, both verified runtimes, corrected reference and original validation input pins; it never pretends that an incomplete catalog is a prepared benchmark manifest. Later `run` and `report` require this context to match their exact plan and runtimes. `validate` creates a pinned validation plan and an append-only attempt journal, then runs the actual allowlisted commands serially under the same interpreter, admission checks, two-hour per-command limit and process-tree cleanup. The ten original Gate1 stages run first: the unchanged 106 tests, unchanged 51 regressions, four refinements, two objective/prior checks and two distinct original nuisance replays. Their failures remain visible, and any Gate1 failure prevents later v4 gates. After Gate1 succeeds it runs the three actual native tangent tests, structural/optimizer, protocol, multi-day, validation, product-boundary and owned-supervisor fixtures and the two small actual GNSS linearization gates. The latter compare both segment layouts and three damping values against dense QR and independent GTSAM 4.2 QR on the same captured rows. None of these test results authorizes an accepted-fit covariance by itself.

`validation_inputs` pins schema `orbit-poc-segmented-validation-inputs-v1`: the exact14 original artifacts, corrected-source freeze, complete glob-visible native data inventories and dependency artifacts. The original 106/51 test names and original 14 byte hashes are shipped as literal `validation_reference.py` constants. Protected original test and gate-script bytes must still match the corrected-source reference. The command registry does not accept shell commands or passed-gate flags from JSON. Every completed output is parsed, hashed and checked against its exact command and runtime. A timeout or interruption is retained, never retried over its directory. `run` refuses to execute a benchmark fit until a matching actual validation journal passes this independent recheck. Optional attached release evidence cannot replace it.

The mandatory library manifest uses `orbit-poc-segmented-runtime-closure-v1`. It contains `directory`, exact `files`, pinned `loader`, an `executables` mapping for native/Python/segmented_solver with exact executable and dependency artifact lists, and `runtime_trees` artifacts containing complete `native_data_inventory` records for the Python and native environments. The pinned loader's `--list` runs inside the configured namespace with an explicit `LD_TRACE_LOADED_OBJECTS=1`; only named `linux-vdso` is exempted as a non-file, and unknown/bare-address mappings are rejected. Resolved `/lib` and `/usr/lib` aliases are compared by their actual pinned bytes. Full Python inventories additionally cover NumPy/SciPy/GTSAM dynamically loaded wheel libraries. Missing or extra files fail verification. Inherited `LD_*` injection and Python path variables are cleared; the declared library directory and pinned venv interpreter path are used. The original150's separate glibc runtime is not substituted.

## Pinned native builds

Build into new external directories with the reviewed compiler/dependency environment and pinned GROOPS upstream commit `7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`:

```sh
python scripts/build_groops.py --numerics --segmented --jobs 1 \
  --source-dir /absolute/external/pinned-groops-source \
  --build-dir /absolute/external/segmented-build \
  --prefix /absolute/frozen/native-env
/absolute/frozen/native-env/bin/x86_64-conda-linux-gnu-c++ \
  -std=c++17 -O2 -Wall -Wextra -Werror groops/extension/segmentedQrMain.cpp \
  /absolute/frozen/native-env/lib/liblapack.so /absolute/frozen/native-env/lib/libblas.so \
  -Wl,-rpath,/absolute/frozen/native-env/lib \
  -o /absolute/external/orbit-poc-segmented-qr
```

Record the actual compiler, source, binary, build manifest and all resolved runtime dependencies before preparation. The corrected dense reference is its archived binary, not a rebuild of this source. Build commands do not imply validation passed.

## Evidence and release gates

The JSON and HTML reports include every planned attempt, even when preparation is blocked or a native fit fails. Comparisons use only matching inputs and the same disturbance model, and require identical native preprocessing audit hashes for fixed support and weights. Cartesian covariance at both trajectory and nominal-observation epochs is compared after normalization by dense posterior standard deviations. Cross-epoch blocks use ||Pab_segmented − Pab_dense||F / sqrt(||Paa_dense||F ||Pbb_dense||F), so zero cross-covariance is well defined. A diagonal-normalized joint 12-state metric is additional information. Common queries are start/end, nearest 1 h/2 h and nearest 4 h/8 h, independent of segment layout. Selected dynamic covariance includes the physical initial state and first/middle/last original force blocks. Position and force differences must meet the unchanged 30 µm and density 1e-4/pulse 1e-8 m/s limits. Prediction differences use exact native observation row identities and the fixed per-row noise. A missing prediction export is an unavailable equivalence check, never a pass. Objective differences must lie within the measured numerical resolution, including physical repeat variation; a small value alone does not certify stationarity.

Release readiness requires all of the following:

- The unchanged 106 native tests, 51 correctness regressions, four refinements, both objective/prior checks and both distinct original nuisance replays.
- Lifted-system true residual <2e-12; small-problem MAP discrepancy <1e-7 posterior standard deviations and relative covariance error <1e-8.
- Rank classification, unit/row/block invariance, full constraints and cross-covariance, rollback and propagated derivative evidence bound to the actual source, native binary and input manifest.
- Full-arc normalized covariance difference <1e-6; prediction differences <1% of assumed noise; actual objective agreement within measured resolution.
- Strict successful 72-hour leo500 disturbed-blackout fits for both methods, flight equivalence, and no dense-success/segmented-failure regression.
- All 68 attempts reported, plus completion of the separate original 150-attempt benchmark using its original pinned runtimes.

`release_evidence` uses schema `orbit-poc-segmented-gates-v1` and binds `manifest_hash`, `source_sha256` and `native_sha256`. Each gate has a pinned `evidence` receipt with schema `orbit-poc-segmented-gate-receipt-v1`, its check name and the same source/native/manifest identities. A separately pinned invocation must identify a completed zero-exit execution with cleanup. The pinned result is parsed: native JUnit must match both its supplied inventory and the immutable published corrected 106/51 inventory without failures/skips; measured JSON uses schema `orbit-poc-segmented-measured-gate-v1`, the same identities and retained raw artifact pins. Counts and scalar values are derived from that result, not copied from a summary assertion. Original replay receipts are parsed for two strict undamped updates, fixed observations/weights and exact zero transactions. Their original/executed XML and physical input hashes are checked against the corrected reference audit; a passing wrapper cannot override a failed native receipt. The original 150 completion check reconstructs every original request from its pinned plan/config and manifest, then verifies exact per-attempt request/input identities and runtime hashes; one result cannot stand in for multiple cases. Missing or mismatched evidence leaves readiness false. Dense long-arc failures may remain as reported outcomes; they do not automatically block readiness when the required segmented cases and all applicable paired/flight gates pass. A segmented failure with a successful dense counterpart does block readiness.

Flight still uses `flight_gravity_drag_v1`: full configured gravity and drag derivatives, while thermal-history sensitivities, other force gradients and atmospheric event-time derivatives remain omitted. Flight numerical equivalence cannot certify a complete flight Jacobian. The effective drag correction is not an independent atmospheric-density recovery claim.

## Local tests

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider \
  --basetemp /absolute/external/segmented-test-temp \
  tests/test_segmented_protocol.py tests/test_segmented_multiday.py tests/test_segmented_validation.py \
  tests/test_segmented_linear_system.py tests/test_segmented_solver.py \
  tests/test_segmented_tangent.py
```

Protocol tests exercise strict configuration, immutable input identity, failed-attempt resume and complete report inclusion. Multi-day tests execute real XML construction, daily-product merging and 72-hour SPP arithmetic with controlled input fixtures. Native integration, full nonlinear equivalence, all required correctness gates and the bounded benchmark still require the pinned executables and actual input artifacts; local fixture success does not substitute for those runs.

## Explicit wide-tangent candidate

The 72-hour preparation failure exposed loss of accuracy in the global tangent
solve. The separately versioned candidate keeps extended precision through the
operator and Krylov calculation, then checks the actual returned binary64 state.
If that check fails, refinement starts from the returned state and its residual.
The limit remains 120 iterations, restart capacity 20 and relative residual
`2e-12`. The frozen repeated diagnostic passed all 27 captured systems, with no
paired regression and unchanged baseline traces. Its [complete report](../validation/segmented-v4/tangent-rhs-family02/index.html)
retains the earlier rejected candidate. These results do not establish native
trajectory closure or completion of the 68-fit benchmark.

Build selection is explicit. Existing `--numerics` and `--segmented` invocations
retain their previous installation paths. The additional option below requires
`--segmented`, uses the same pinned upstream commit
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`, and installs seven reviewed source
payloads only after checking their original or already-installed hashes:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/build_groops.py \
  --source-dir /absolute/fresh/groops-source \
  --build-dir /absolute/fresh/groops-build \
  --prefix /absolute/pinned-dependencies --jobs 1 \
  --numerics --segmented --wide-tangent-candidate
```

Use the admitted owned-process controller for validation and timed execution.
Keep the original binaries and campaign directories intact. The build manifest
records the complete patched source and a separate `wide_tangent_extension`
receipt. The source-delta build must additionally reproduce this full installer
from pristine upstream source, reproduce the untouched baseline link, and check
dependencies for every linked C++ and Fortran object.

For flight tangents, metadata capture uses the existing batch interpolation
traversal, including its selected anchor and high/low coefficients. Tangent
export schema `orbit-poc-segmented-tangent-v2` records those semantics explicitly;
the bounded diagnostic decoder also accepts archived v1 exports. Its exact
dyadic lift records rounding when materializing binary64 rows and rejects a
nonzero coefficient lost to underflow. This decoder is limited to 1,000 epochs
for diagnostic checks; it does not replace the production variation-of-constants
factor construction. GNSS query interpolation remains unchanged.

The complete native candidate (`643a1b6d523a363e…`) passed the unchanged
106/51 tests and all fourteen validation07 stages, including the four refinements,
two objective/prior checks and both distinct nuisance replays. The
[supplemental report](../validation/segmented-v4/native-supplements07/index.html)
records ten native batch-interpolation cases, a matched QR-enabled flight
export/no-export pair and 32 shifted-cut solver calls, with independent audits.
The shifted checks use one-hour captured synthetic linearizations; their
one-hour/four-hour layouts do not constitute multi-day fit results. The
300-second pulse shifts have no interior ownership movement; the 1,800-second
shifts provide that coverage. GNSS precise-offset interpolation remains outside
the batch fixture's coverage.

The flight pair's original checker failure is preserved: it compared native
`dt = 5.000000000000568` with literal `5`. A separately versioned decoder checks
the exact retained binary time grid and native endpoint arithmetic. Independent
reinspection passed with unchanged residual and STM limits, using the same
preserved outputs and no new propagation. Both native legs used QR and the
retained final reference, so this is neither an ordinary-to-QR comparison nor a
replay of the deleted intermediate input. The flight derivative omissions above
remain applicable.

Fresh preparation07 completed on 18 October 2026 at 20:31:00 UTC. All four
continuous 72-hour generations and twelve prefix/mask jobs completed with
verified owned-process cleanup. The [preparation report](../validation/segmented-v4/preparation07/index.html)
publishes the exact 28-case catalog, 68-attempt order, settings and input pins.
Independent audit verified the retained preparation receipts, unchanged source
and runtime identities, and the frozen manifest
`63f3010564c6da76c0f92a007ed1fbe057d610d44cccb6b5e4f509afafbf2251`.
Bulky generated inputs and full inventories remain outside Git with their hashes
recorded in the report.

At that terminal preparation capture, no benchmark fit had begun. Preparation
does not establish fit convergence or accepted covariance. The 68-attempt
benchmark and the separate original v3.1 150-attempt campaign remain release
requirements.

The [campaign control report](../validation/segmented-v4/campaign07/index.html)
preserves three failed metadata setup attempts and their independently reviewed
corrections. The latest correction closes the dynamic loader's parent-symlink
chain and creates each resolved link location once, while retaining the complete
link ledger and exact input checks. It passed 122 independent control tests, a
real isolated-filesystem fixture, and replay of all 44,072 captured file rows and
46,948 inventory entries. Scientific source, runtime payloads, prepared inputs
and numerical settings are unchanged. This dated snapshot does not certify a
successful remote setup, launch, fit convergence or release readiness.
