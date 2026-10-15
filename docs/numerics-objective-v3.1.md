# Fixed-parameter objective and shared controller

The opt-in adapter is `orbit_poc.numerics.backend.NativeModel`; the controller is
`orbit_poc.numerics.optimizer.minimize`. The existing comparison backend remains
the compatibility default. The numerical adapter accepts only blind estimation
inputs and the two float disturbance models.

## Physical state and trial evaluation

A physical state consists of six SI initial-state components and either full
native pulses in micrometres per second or dimensionless log-density knots.
Native initial-state columns can use a different basis: the evaluator exports
their six physical initial-state rows, and the adapter uses this map when
constructing every trial. Global nuisance corrections do not enter that physical
state.

Every evaluation creates a new directory. It propagates at fixed initial state
and fixed force parameters, repeatedly evaluating the forces on the previous
trajectory until both position and velocity close. A new native process starts
each propagation, resetting history-dependent forces and recomputing atmosphere
crossings. The closure tolerances are 2 micrometres and 3 nanometres per second;
the confirmation and numerical-floor checks tighten both by ten. Failure to
close after sixteen propagations is an explicit numerical failure.

Full pulses enter the variational evaluator and their Gaussian constraints.
Density values enter the actual force multiplier and OU constraint; the
variational density increment is zero at a fixed trial. The native physical mean
reference is separate from the fitted increment vector, so an initial-state
reanchoring or a pulse is neither omitted from the mean nor counted twice in its
prior. Pulses retain the native post-pulse velocity convention.

The GNSS stage refits float nuisance parameters with dynamics held fixed. Its
preprocessing uses the unchanged retained-observation bootstrap, and it cannot
reweight observations or resolve integer ambiguities. Full float ambiguities stay
in their current coordinate system: the QR path disables native integer
recentering that would otherwise rewrite the phase observations whenever an
ambiguity crosses a half-integer. This is algebraically the same forward model
and gauge, with fixed observation bytes and fewer large-value rounding losses.
Every trial verifies unchanged observations and weights, and verifies that full
ambiguity coefficients accumulate exactly to floating-point precision. The
legacy ambiguity-resolved reference retains its original behavior. The
original-row QR path
retains the energy removed by clock and ionosphere elimination. `direct_cost`
is half the squared current measurement and full-prior residual norm, including
the ionosphere energy before its local linear elimination. The distinct
`linearized_profile_cost` is a diagnostic of a proposed nuisance correction and
is not the actual nonlinear objective. Ionosphere nonlinearities therefore
require repeated nuisance profiling, just like the other nonlinear terms.

The inner GNSS profile permits 128 fresh undamped corrections. It backtracks
along each joint nuisance correction, including conditional STEC and clocks,
using factors 1, 1/2, ..., 1/65536. A nonstationary trial must decrease the directly
evaluated nonlinear cost and exceed a gain ratio of 1e-4. Candidate states run in
isolated Linux fork children with no factor, row, trace or bias-coordinate
exports. Only an accepted correction is applied to the parent, once; its fresh
cost must reproduce the child result. Rejected trials leave the parent's
parameters, caches and output files unchanged. Explicit single-thread OpenBLAS
and OpenMP settings and a single-thread process are required.

Convergence requires two consecutive **full undamped** corrections with native
measurement influence below 10 nanometres (including the joint observation
rows and the separate native component maxima), followed by a fresh undamped
linearization. A shortened accepted correction cannot satisfy this check. If all
trial factors fail without raw stationarity, the default result is nonconvergence.
A distinct progress-only status can be recorded only after the empirical audits
below; it is never called nuisance convergence.
An earlier 1-nanometre diagnostic reached a measured representation floor around
3.4 nanometres; the 10-nanometre inner threshold leaves the specified outer
orbit, pulse, density and gradient thresholds unchanged. Every raw correction,
conditional/retained gradient, predicted reduction, trial factor, actual
reduction and rejection is exported. Both predicted and actual reductions avoid
subtracting two large objective sums: the actual value accumulates paired
nonlinear residual-square differences with extended precision. Child wait4 RSS
is a separate diagnostic; the benchmark measures the concurrent process tree.

When ordinary backtracking exhausts all factors, three isolated fixed-parameter
re-evaluations measure an **empirical arithmetic resolution**. They use the first
and last interpolation nodes instead of the middle node as the Lagrange anchor,
and reverse the extended-precision range accumulation order. These are
algebraically equivalent evaluations of the same polynomial and measurement
formula. The largest absolute paired residual-square difference is recorded as
`nuisance_objective_resolution`; it is not a rigorous error enclosure. Every
zero-update replay, audit, observation/weight fingerprint and support check must
succeed. A zero measured resolution or an undamped positive nuisance potential
larger than that resolution cannot produce the limited status.

Four independent cost-only probes at `+a`, `-a`, `+a/2`, and `-a/2` along the
fresh full nuisance correction then test the local objective. Their signal is
kept separate from the arithmetic-resolution estimate. Both symmetric curvatures
must exceed sixteen resolution units, scale by four within twelve units, and
produce slopes consistent with the fresh undamped gradient under the exported
resolution-based allowances. The two empirical quadratic remaining-improvement
estimates, including their propagated empirical slope and curvature allowances,
must also fit inside the measured resolution. These tests allow the
residual Hessian to differ from the Gauss–Newton Hessian; they reject weak or
negative curvature, wrong slopes, amplitude dependence and unresolved probes.
The initial probe amplitude is `max(64, sqrt(4096 * resolution / potential))`.
If the shape, slope and nominal-potential checks pass but the propagated
allowance alone is too large, the audit may double the amplitude to improve
measurement resolution. It retains every round and stops after at most five
rounds. Both the planned amplitude times the full undamped influence and the
actual reported influence of every probe must stay at most one metre; a separate
scalar ceiling of `1e9` guards numeric overflow. This admits large multipliers
on tiny corrections without permitting large nuisance displacements. Every
other failure stops immediately; no
acceptance criterion is relaxed. All empirical factors and
raw probe costs are exported, without a global-minimum claim.

Only a successful audit followed by a fresh undamped factor at unchanged
parameters may set `nuisance_floor_limited=true`. Such a profile explicitly has
`nuisance_converged=false`, and the native covariance exporter rejects it.
Unsuccessful audits remain ordinary nonconvergence. Audit and probe children
cannot write parent output files or alter the accepted nuisance state. The
outer controller's separate progress-only guard is described below; final
convergence always requires a strictly converged nuisance profile.

## Steps, rollback and convergence

The controller solves in complete weighted-column-norm coordinates. LM damping
applies only to physical dynamic parameters, and the predicted reduction omits
the damping penalty. Actual reduction is measured by a new closed physical
trajectory and a new nuisance fit. The initial damping is 0.001; accepted steps
require positive actual reduction and gain ratio greater than 0.0001, as
specified in the protocol. Gain-ratio updates use the Nielsen cubic rule.
Changes smaller than the measured numerical floor are flagged explicitly as
unresolved objective differences; the floor does not replace the stated step
acceptance rule. Such steps cannot establish convergence without all the fresh
undamped correction, gradient and covariance checks below.

An explicitly inexact inner profile has a separate progress-only policy. If
either endpoint is marked `nuisance_floor_limited`, the sum of their empirical
nuisance objective-resolution estimates must be at most 0.001 times the outer
predicted reduction. Subtracting that sum from the measured actual reduction
must still give a gain ratio above 0.0001. This conservative forcing rule applies
only to inexact profiles; strictly profiled points keep the acceptance rule
above. The empirical estimate is not a rigorous error bound or proof of a global
nuisance minimum. A floor-limited current point or confirmation cannot establish
outer convergence, and the covariance evaluator rejects this status outright.

The accepted point is immutable. A rejected point owns separate propagation,
parameter, force-state and nuisance artifacts; it cannot overwrite the accepted
point. Observation support, parameter identities and preprocessing-audit hashes
must agree across evaluations. Initial repeated evaluation and tighter closure
measure the objective floor instead of treating a logged residual sigma as an
objective.
When a proposed reduction approaches that floor, or the physical correction
passes its size tests but the gradient does not, the controller repeats the
measurements at that accepted state. It uses the more accurately closed
trajectory and its fresh factor for the next stationarity check and proposal.
The physical initial state, pulses or density knots do not change during this
refinement, and it is not counted as an accepted optimization step. The recorded
floor measurement retains both objective values. An absolute floor measured at
a poor initial trajectory is remeasured near the solution.

A candidate with failed trajectory closure, failed nuisance profiling, an
invalid objective or unresolved/deficient rank is rejected with its reason
recorded, followed by a more strongly damped trial. A changed observation set
or an exhausted execution budget terminates the fit. Initial-point failures
also terminate the fit because there is no valid accepted point to retain.

Convergence uses a fresh undamped correction, requiring maximum position change
below 30 micrometres, maximum density update below 0.0001 or pulse update below
1e-8 m/s, and normalized scaled gradient below 1e-8. A tighter confirmation and
another fresh undamped final linearization must pass the same criteria. Damping,
iteration limits, wall limits and rank failure never establish convergence.
If the tighter confirmation reveals a remaining correction, the controller
continues from that fresh factor at the same physical parameters, recording the
failed stationarity check without incrementing the accepted-step count. The
complete `confirmation_checks` ledger preserves every such check, including
consecutive refreshes before another trial. The existing trial and wall budgets
still apply. Final covariance is never accepted
on the strength of a stale earlier check.
The adapter and controller share one monotonic start time, so native input
initialization counts against the same fit budget. The wall limit is checked
again after confirmation and final covariance work.
Covariance uses selected solves in the full retained, undamped QR factor and
marginalizes the nuisance parameters. It is a local Gaussian approximation
conditional on the frozen statistical settings.

## Build and evidence

Use an independent checkout of upstream commit
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee` and separate build/output directories:

```sh
python scripts/build_groops.py --source-dir /work/groops-v31 \
  --build-dir /work/build-v31 --prefix /work/native-dependencies \
  --numerics --jobs 8
```

If the compiler/dependency prefix does not contain a complete CMake
installation, pass `--cmake-executable /absolute/path/to/cmake`. The build
records upstream revision, extension hashes, compiler, CMake cache and binary
digest in `build-manifest.json`. MPI is disabled explicitly.

`native_runtime.json` and `iterations.json` record objective values, reductions,
rank, damping, raw corrections, rejected trials, propagation counts, execution
logs and resource measurements. The final fit also retains the physical
parameters, direct GNSS phase diagnostics, original-row QR factor and covariance
artifacts. Unsuccessful fits have no accepted covariance. Engineering tests and
the frozen 150-attempt benchmark have separate receipts; passing a small test
does not imply completion of the benchmark.

For a blind synthetic development fixture, run the complete optimizer and the
independent native objective check in distinct new output directories:

```sh
PYTHONPATH=src python scripts/run_numerics_development.py \
  --request /work/engineering-request.json --native-binary /work/groops-v31 \
  --output /work/engineering-fit
PYTHONPATH=src python scripts/validate_numerics_objective.py \
  --request /work/engineering-request.json --native-binary /work/groops-v31 \
  --output /work/engineering-objective-check
```

The latter checks nonzero full-parameter prior rows against their analytic
pulse/OU residuals and compares the profiled objective derivative with actual
repropagated positive/negative perturbations. The initial direction gives a
5-centimetre maximum linearized position change; up to nine geometric halvings
separate finite-difference truncation from numerical resolution. Two consecutive
step sizes must meet the same relative tolerance of 1e-4. Every tested scale,
including failed coarse steps, remains in the receipt. Both scripts
preserve earlier attempts and record the current source/native identities
separately from preparation identities. Development receipts never establish
that a frozen benchmark attempt has run.
The objective check records the nuisance status and empirical resolution at
every endpoint. It propagates that resolution and ten times the repeated
physical-closure cost difference into the central-difference diagnostic, and
requires the discrepancy plus this empirical allowance to meet the unchanged
relative tolerance of 1e-4. This
does not certify nuisance convergence or turn the empirical estimate into an
error bound.
An optional `--initial-state-from /work/blind-point/physical_initial.txt` selects
the six physical initial components from a preserved blind engineering iterate.
The check still injects its declared nonzero force parameters and recomputes
physical closure and nuisances. Such a check records the selected input hash and
initialization policy; it verifies local objective correctness, not robustness
from the original bootstrap. Original-start failures remain in the engineering
ledger, and this option is unavailable to frozen benchmark initialization.
