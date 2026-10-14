# Synthetic force arithmetic in the correctness candidate

`configured_crf_parts_stable_reference_v1` changes floating-point evaluation
only for `synthetic_complete_v1`. It does not change the configured physical
forces, integration coefficients, statistical priors, or convergence criteria.
It remains subject to native build, derivative, refinement and objective gates.

The two closed density evaluations that motivated this work had identical
physical initial states and density files. Their final trajectories differed
by 31.10 nm, despite an identical initial epoch. Their archived mean positions
differed by at most 11.22 nm; the initial-state corrections differed by at most
20.39 nm. The full state-transition matrices agreed to roughly 1e-15 relatively.
These observations locate a remaining mean-trajectory repeatability problem;
they do not establish that this arithmetic correction fixes it.

The new capability is parallel to the existing synthetic derivative dispatch.
Only the actual configured synthetic gravity, synthetic drag and log-density
wrapper implement it. Unknown components, configured gravity fields or tides
fail explicitly. The aggregate preserves actual satellite-state updates and
component order. The real Earth rotations remain available for those updates,
the archive, and the measurement model.

The supported gravity and drag classes already calculate CRF forces, then
rotate their output. Their new full-force capability calls the existing
acceleration method with identity output rotation, avoiding a redundant
CRF–TRF–CRF round trip. It does not pass an invented Earth rotation to arbitrary
force models. Gravity shares its existing J2 expression between the ordinary
entry point and the decomposition; the original scalar order and final vector
grouping are preserved. Drag uses its actual configured acceleration method.
The log-density wrapper evaluates its existing multiplier at the original time
and applies it recursively. Component sums and multiplier application in this
new path use long double; legacy and flight propagation retain their original
calls and arithmetic.

When Enke reference gravity is enabled, keep the configured central coefficient
and noncentral force separate. For position `r`, fitted reference position `R`,
actual configured coefficient `mu`, and reference coefficient `mu_ref`, set

```
delta = r - R
q = (2 R·delta + delta·delta) / (R·R)
f = expm1(-1.5 log1p(q))
reduced central force = [-mu (delta + f r) + (mu_ref - mu) R] / |R|³
```

This is algebraically `-mu r/|r|³ + mu_ref R/|R|³`. The original forward GM is
398600441800000 m³/s², whereas this fixture's reference GM is
398600441500000 m³/s². Their difference is retained; it is not rounded away or
assumed zero. Add the actual noncentral components before converting the
reduced force to the existing double-precision integration vector. Reference
subtraction occurs once at the aggregate level. The original fitted reference
orbit, reference positions/velocities and integration windows remain unchanged.

The new diagnostics identify this version and the configured reference GM.
Analytic derivatives continue to come from the same actual force instances.
The derivative of this exact residual with respect to `r`, at fixed `R`, is the
derivative of the original full physical force. Flight remains
`flight_gravity_drag_v1` with its previously disclosed approximations.

Focused tests compare the compiled residual helper with an independent
100-digit Decimal oracle, including coincident and separated positions, equal
and unequal GMs, noncentral forces and recursive weighted composition. A small
adapter compiles the actual patched gravity/drag headers with nondefault
parameters and checks the ordinary gravity output against its original
operation sequence bit for bit. Fabricated installer tests check unsupported
capabilities, the synthetic-only branches and idempotence. These are not a full
GROOPS compile or trajectory experiment.

Remaining limitations include fitted-reference rounding, absolute trajectory
storage, initial-state reanchoring, and finite precision in configured force
components. This correction does not justify weaker closure or objective
criteria, selected repeats, or a claim that the earlier failed gate passed.
