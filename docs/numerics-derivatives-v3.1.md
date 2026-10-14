# v3.1 six-state trajectory derivatives

The native `PreprocessingVariationalEquation` program accepts
`orbitPocDerivativeProfile`. Its default, `legacy_v3`, retains the existing
position-only correction. The opt-in profiles are `synthetic_complete_v1` and
`flight_gravity_drag_v1`. `orbitPocDerivativeDiagnostics` writes a JSON record
for a single arc. Unknown profiles and measured-accelerometer or fitted-force
inputs unsupported by the staged path are rejected.

Both staged profiles solve the coupled tangent equations

\[
\delta r=b_r+\int_0^t(t-s)(A_r\delta r+A_v\delta v)\,ds,
\qquad
\delta v=b_v+\int_0^t(A_r\delta r+A_v\delta v)\,ds.
\]

The position and velocity corrections use the same force evaluation and Enke
reference as forward propagation. Initial-state sensitivities use the same
coupled operator. Native archive scaling is unchanged: initial velocity columns
contain `1 / arc_duration`, and instantaneous inertial pulse columns remain in
micrometres per second. Downstream variational integration retains its existing
right-continuous pulse convention and direct log-density design.

The tangent integral equation uses restarted GMRES with reorthogonalization,
a piecewise-linear acceleration preconditioner, and a checked true relative
residual at most `2e-12`. This is a propagation solve; it is separate from the
weighted-row QR used for GNSS estimation. It neither forms GNSS normal equations
nor regularizes their parameters. The velocity residual is multiplied by
1,000 seconds solely for numerical balance. Nonconvergence raises an error
including its true residual, right-hand-side and solution norms, iteration count,
solve role and column.

Both the staged mean force integral and its tangent use local interval moments
with `long double` accumulation, preserving the native polynomial weights and
boundary windows. Computing a full-day position integral as the difference of
two global double-precision moments caused cancellation in a retained eccentric
arc. The local recurrence avoids that subtraction; the diagnostics record the
accumulator precision. The `2e-12` checked residual limit is unchanged. The
legacy numerical path retains its original integration.

Consequently, the benchmark contrast from `qr_lm_legacy_jacobian` to
`qr_lm_staged_jacobian` combines the coupled derivative upgrade with this
mean-integral arithmetic stabilization. Report its trajectory and covariance
differences as a **combined derivative and quadrature-arithmetic effect**. It
cannot be attributed solely to the Jacobian. The physical forces, polynomial
weights, priors and observation model remain shared; the separate refinement
checks bound the combined numerical behavior on their stated engineering cases,
without decomposing the two contributions.

## Synthetic profile

Analytic central/J2 and corotating exponential-atmosphere state derivatives are
methods of the actual configured native force instances. This avoids maintaining
a second set of physical constants. The log-density wrapper multiplies both
state Jacobians by its current `exp(g(t))`. Unsupported synthetic force
components, additional gravity fields, and tides fail explicitly.

The drag Jacobian includes the radial density gradient, atmospheric corotation,
the derivative of relative speed, and velocity dependence. At exactly zero
relative velocity its derivative is zero. Fixed density-knot times remain
continuous integration boundaries.

## Flight profile and its limits

The gravity Hessian comes directly from the configured forward gravity object;
its maximum degree therefore matches the forward force automatically. It does
not use the old low-degree `gradientfield` configuration.

Drag derivatives use central finite differences of the separately configured
`orbitPocAtmosphericForce`, including its current log-density correction. Each
component evaluation recomputes nominal atmospheric density, wind, temperature,
and macro-model geometry at fixed time and attitude. Initial position/velocity
steps are 1000 m and 0.001 m/s. The spatial starting step is above the
roundoff floor observed in the native atmosphere/wind calculation: on the Apr24
development window, 1 m/0.5 m central differences disagreed by up to 0.0032
relative norm. A subsequent full-grid test found a near-equator auxiliary epoch
where 100 m/50 m still disagreed by 0.00266, while 1000 m/500 m agreed
within 0.000070. The diagnostic receipts preserve both failures and the actual
atmospheric force evaluations that justify the larger starting step.
This changes only derivative differencing, not the forward force. Another
near-equator column had norm `5.04e-16 s^-2` and an absolute half-step
discrepancy of `1.18e-18 s^-2`: its relative discrepancy exceeded 0.002 solely
because the derivative was close to zero. The flight profile therefore uses a
combined criterion: successive half steps must agree within `0.002` relative
column norm or `2e-18 s^-2` absolute position-column difference, whichever is
larger. This is a dimensioned denominator floor of `1e-15 s^-2`. The velocity
floor remains `1e-17 s^-1` (absolute agreement `2e-20 s^-1`). The accepted step
range, absolute differences, unfloored relative differences and counts of
columns using the floor are all exported. The full nonlinear trajectory
comparison measures the practical effect; the absolute threshold alone is not
an orbital error bound. At most four refinements are permitted. The accepted
derivative is Richardson-extrapolated. Failed refinement aborts the computation.
The nominal geometry is restored after successful differencing.

Flight atmospheric Jacobians are evaluated at the same actual auxiliary epochs
as the one-sided atmospheric force quadrature. State corrections at those epochs
use the existing piecewise interpolation, respecting knots and pulse boundaries.
The operator retains both gravity and atmospheric contributions in position and
velocity. Finite differences never call the history-dependent total force.

The flight profile explicitly omits:

- Thermal-history sensitivities.
- Gradients of forces other than the configured gravity field and drag,
  including third-body/tidal and radiation-pressure components.
- Derivatives of atmospheric event times with respect to the trajectory.

The diagnostics record these omissions, the maximum accepted drag refinement
discrepancy, evaluation counts, and the tangent solver residual/iteration count.
This metadata does **not** certify a complete flight Jacobian. The numerical
benchmark must measure the combined omitted contribution against independent
full nonlinear trajectory perturbations.

## Validation commands

`tests/test_numerics_derivatives.py` compiles the actual standalone C++ kernels
and checks force derivatives over multiple altitudes and directions, Hessian
symmetry and trace, zero relative velocity, finite-difference refinement and
failure, and a damped oscillator with an analytic six-state solution. It also
checks zero right-hand sides and failure to meet a tangent-solver budget. A
full-day circular Kepler case exercises the rotating, indefinite gravity
Hessian and secular state-transition growth against the independent analytic
Hill/Clohessy–Wiltshire solution in inertial coordinates. Its position and
velocity discrepancy limits are `3e-8` and `1e-10`, respectively, in the native
scaled state basis; all six columns must still meet the true residual limit.

With `ORBIT_POC_GROOPS` pointing to the built v3.1 binary, the same test file
checks actual native synthetic force instances with nonzero log-density
corrections and compares native six-state transitions against independent
SciPy DOP853 perturbed trajectories, with and without density knots. These small
synthetic tests use deliberately amplified drag to expose omitted velocity
coupling. The native `OrbitPocStateDerivatives` diagnostic exports force Jacobians
or archived physical state-transition matrices; it does not substitute a Python
force model for the native implementation.

These local correctness tests precede the frozen 150-attempt benchmark and the
full flight perturbation/refinement gate. Passing them alone is not numerical
or scientific acceptance of the benchmark.

The reproducible flight diagnostics are separate from the frozen benchmark:

```sh
python scripts/validate_numerics_drag_steps.py --prepared PREPARATION_JSON --binary GROOPS --output NEW_DIRECTORY
python scripts/validate_numerics_flight_derivatives.py --prepared PREPARATION_JSON --binary GROOPS --output NEW_DIRECTORY
python scripts/validate_numerics_flight_refinement.py --prepared PREPARATION_JSON --binary GROOPS --output NEW_DIRECTORY
python scripts/validate_numerics_synthetic_refinement.py --request ENGINEERING_REQUEST --binary GROOPS --output NEW_DIRECTORY
```

The preparation must be the April 24 UTC development preparation. The drag-step
study samples 37 epochs and evaluates only the actual atmospheric component.
Optional `--failure-log` adds an exact recorded failure state, with normalized
degree-7 interpolation of the actual attitude, to probe a missed auxiliary
epoch without changing the original failure receipt. The
trajectory derivative diagnostic covers 11:45–12:15 UTC, repropagates all six
initial-state axes with two central-difference amplitudes, and records omitted
terms and perturbation refinement separately. It uses a 0.1 s thermal step to
reduce the diagnostic's numerical floor. Force history is initialized at the
window start on each propagation; this is a standalone 30-minute arc rather than
a slice of a warmed 24-hour trajectory. It cannot certify all 24-hour flight
arcs or a complete flight Jacobian.

The propagation refinement diagnostic starts from the preparation's actual
thermal step (the native default is 1 s when unspecified) and halves it together
with the state grid and atmospheric quadrature. Both trajectories close at the
same fixed physical initial state. It compares native code predictions on the
same retained development observations. `OrbitPocPredictSignals` exports complete
native per-frequency code and carrier equations, with the receiver clock and
STEC fixed and no fitted ambiguity tracks. Signal identities and nuisance values must agree exactly between grids. The
prediction program receives the same QR environment as the opt-in estimator,
including continuous polynomial query evaluation. Receiver positions and
velocities are refreshed at the fixed clock-corrected queries, preserving the
sub-Time query remainder and the sub-double position remainder used by the
native range calculation. Anchored polynomial accumulation and exact pulse-side
selection therefore run through the same path as the estimator. It writes a
`prediction_mode.json` record and never solves nuisance parameters. It prescribes
the same fixed clock offsets on both grids, cycling through `+/-50 ns`,
`+/-5 microseconds` and `+/-20 microseconds`, to exercise interpolation near
the historical time-snap margins. The exported clocks must match exactly.
The coarse native sigmas are frozen for both comparisons; any change in the raw
geometry-dependent accuracy-pattern values is reported separately. Paired differences must remain below
one percent of both the declared per-frequency noise and the native sigma.
Unknown carrier ambiguities cancel in these numerical differences; the absolute
phase residuals are never used as accuracy scores. Position differences at native
and off-grid epochs supply an additional interpolation check.

The synthetic refinement command uses a verified engineering request and tests
nonzero prescribed pulses or log-density corrections without estimation. It
retains the same initial state, forward forces, observations and nuisance values
on 5 s and 2.5 s grids. All commands require a fresh output directory and keep
native inputs, logs, hashes and failure receipts outside Git.

## Recorded engineering checks

The recorded candidate is `groops-3aad854b51102dce`. Its nine derivative tests
and four targeted native/GTSAM acceptance tests passed without skips. These
receipts identify that exact executable; they do not certify subsequent builds
or completion of the frozen benchmark. The four full refinement experiments
below ran on `51a9a4ac003aa51c`; the explicit replay and component-identity chain
at the end of this section records their applicability to the candidate.

The one-hour `leo500` quiet synthetic engineering case passed the complete
native signal refinement check for both fixed, nonzero disturbances. The pulse
case changed code/carrier predictions by at most `1.129e-8 m`; the density case
changed them by at most `5.863e-9 m`. Both compared 8,106 native per-signal rows
with identical signal support, receiver clocks and STEC. The worst carrier
change was `3.762e-6` of its assumed standard deviation, below the `0.01` limit.
Off-grid position changes were at most `5.60 micrometres`. These are bounded
engineering checks, not measurements for every frozen benchmark case.

The receipts are
[`synthetic-staged-refinement-pulses.json`](../validation/numerics-v3.1/synthetic-staged-refinement-pulses.json)
and
[`synthetic-staged-refinement-density.json`](../validation/numerics-v3.1/synthetic-staged-refinement-density.json).
They pin the actual native binary, diagnostic source, requests, force values,
observations and numerical configurations. A later build that changes these
implementations requires a new receipt.

The native atmosphere step studies are retained in
[`native-drag-step-diagnostic.json`](../validation/numerics-v3.1/native-drag-step-diagnostic.json),
[`native-drag-step-auxiliary-diagnostic.json`](../validation/numerics-v3.1/native-drag-step-auxiliary-diagnostic.json),
and [`native-drag-near-zero-diagnostic.json`](../validation/numerics-v3.1/native-drag-near-zero-diagnostic.json).
The last receipt measures the `1.18e-18 s^-2` discrepancy directly from the
actual native atmospheric component. The corresponding failed development
runs remain indexed in
[`derivative-development-history.json`](../validation/numerics-v3.1/derivative-development-history.json).

The staged April 24 flight refinement check also passed on the same 30-minute
development window. Jointly halving the 5 s trajectory grid, 1 s thermal step
and 1 s atmospheric quadrature changed 2,880 native code/carrier equations by
at most `0.933 micrometres`. The largest change was `0.002191` of the smaller
native or declared standard deviation, below `0.01`. Fixed clock/STEC values and
signal identities agreed exactly. The geometry-dependent native sigmas changed
by at most `8.92e-12` relative; the coarse values were frozen for both numerical
comparisons. Off-grid position differences reached `11.76 micrometres`.
See [`flight-staged-refinement.json`](../validation/numerics-v3.1/flight-staged-refinement.json).
This measures numerical convergence on the stated window, not flight accuracy.

The independent nonlinear flight perturbation study completed all 25 physical
trajectories (75 tightly closed propagations) on April 24 11:45–12:15 UTC. Every
column passed the two-amplitude step check and its omitted-term discrepancy was
resolved above the finite-difference error:

| Initial component | Maximum position-Jacobian difference | Half-step difference | Units |
|---|---:|---:|---|
| x | 3.367e-07 | 2.659e-09 | m/m |
| y | 5.931e-07 | 5.439e-09 | m/m |
| z | 3.997e-07 | 4.253e-09 | m/m |
| vx | 2.456e-04 | 1.397e-06 | s |
| vy | 3.592e-04 | 3.849e-06 | s |
| vz | 1.037e-04 | 3.429e-07 | s |

These differences compare the staged tangent with independently repropagated
full-force trajectories at fixed actual attitude. They combine the omitted
thermal-history, other-force and atmospheric-event sensitivities with residual
finite-difference/propagation error; they do not identify each omitted term
separately. The result quantifies the approximation on this development window
and cannot certify a complete flight Jacobian.

The actual native drag checks evaluated 6,076,875 component forces. Accepted
spatial half-steps were 500 m, and velocity half-steps were 0.0005 m/s. The
near-zero-column floor was used 75 times; the largest unfloored relative
disagreement was 0.002339, while the largest combined-criterion value was 0.001178.
See [`flight-derivative-diagnostic.json`](../validation/numerics-v3.1/flight-derivative-diagnostic.json)
for controls, all six columns, input/source/binary hashes and the explicit
omission inventory.

The retained full-day eccentric density case (seed 300000, original 30-minute
mask) exposed a cancellation failure missed by the short tests. The exact
failed first propagation now completes at a true tangent residual of
`1.1761e-12`, below the unchanged `2e-12` limit. A separate fixed-state
refinement with nonzero density knots closes both the 5 s and 2.5 s grids
and compares 195,054 actual native code/carrier rows. The largest prediction
change is `0.351 micrometres`, or `0.0001168` of the assumed standard deviation.
Off-grid position differences reach `6.21 micrometres`. The fine-grid closure
needed ten passes and reached a `33.4 nm` final position change; all passes,
including the preceding submicrometre numerical fluctuations, are retained.
This is a selected regression case, not independent accuracy evidence. See
[`native-long-arc-derivative-regression.json`](../validation/numerics-v3.1/native-long-arc-derivative-regression.json)
and
[`synthetic-staged-refinement-density-24h.json`](../validation/numerics-v3.1/synthetic-staged-refinement-density-24h.json).

The flight omission study retains the executable hash that actually ran its
25 trajectories. The current candidate has the same 18 force/tangent extension
components and build configuration. Replaying the exact full-day propagation
and the three-closure flight baseline on `51a9a4ac003aa51c` produced numerically
identical physical states and state-transition matrices. Review of the changed
interpolation code confirmed that the archived no-GNSS branch remains unchanged.
All four signal refinements ran anew through that candidate's QR-enabled GNSS
arithmetic. Subsequently, `d781cef73c433490` reproduced all eight saved coarse/fine
prediction and support files byte for byte with the arithmetic-audit mode absent.
The final `3aad854b51102dce` changed only nuisance audit control, diagnostics and
their fixtures; every active force, tangent, default GNSS arithmetic and signal
exporter source file is identical to that replayed build. This supports the
bounded reuse described in
[`derivative-gate-applicability.json`](../validation/numerics-v3.1/derivative-gate-applicability.json)
and its linked replay and component-identity receipts. This evidence does not
attest to nuisance convergence, accepted final covariance, a complete flight
Jacobian, or the frozen benchmark outcomes.
