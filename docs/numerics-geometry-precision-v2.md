# High/low geometry arithmetic v2

`high_low_geometry_v2` changes arithmetic representation in the opt-in QR GNSS
path. The configured polynomial, stencil, pulse/knot side, physical observation
equation, prior, measurement weights and convergence thresholds are unchanged.
The legacy GNSS branch and archived double-valued interfaces remain intact.

The existing optional `preciseValues` interpolation output still returns the
absolute long-double interpolation result. A new optional trailing
`coordinateRemainders` output returns the low part relative to the returned
double. Local weighted offsets are accumulated before adding the orbital-scale
anchor. The low part is evaluated as `(anchor - rounded) + local_offset`, so a
small offset is not first rounded onto the large anchor. At exact nodes and grids
that low part is zero. For derivative output the center is zero; the low part
then refers to the returned derivative. Unsupported adjoint/least-squares
precise-output modes retain their explicit rejection.

The piecewise wrapper propagates both outputs separately through sorting and
batching. Its legacy fallback returns ordinary values and zero low parts. The
receiver cache, transmitter interpolation and diagnostic exporter explicitly
request the new low output. Antenna addition computes `(base - rounded) + antenna
+ low`, preserving the previously recovered low coordinate.

A two-long-double expansion carries geometry through coordinate differences,
squared norm, square root, scale and clock corrections, and measurement
subtraction. Error-free addition and explicit `std::fma` product residuals retain
the low part. The Shapiro logarithm remains ordinary long double because its
rounding is multiplied by millimetres, not orbital distances. The final GNSS
residual remains double. Factor metadata records `range_geometry_precision` as
`high_low_geometry_v2`; it does not imply a new statistical model.

The helper requires round-to-nearest and at least 64 long-double significand bits;
fast-math reassociation is rejected at compilation. Use the pinned compiler and
explicit no-fast-math settings for validation. Existing arithmetic-audit anchor
and summation-order modes remain active.

## Installation and validation

Use a **new disposable clone** of pinned GROOPS upstream
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee` and run the complete extension installer.
Old v1 representation markers are rejected before any write. Preserve prior
installed source, binary, manifests and results. Do not bypass this guard or
assume that old marker-based installation is an upgrade procedure.

`tests/test_numerics_geometry_precision.py` checks installer branches and
idempotence, compatible API propagation, versioned metadata, and the actual
standalone expansion helper against independent Decimal arithmetic. Those checks
are not substitutes for building GROOPS and rerunning the unchanged native
objective/profiling, code/carrier refinement, boundary and covariance gates.
Neither a passing scalar arithmetic test nor this version field implies that a
fit converged or that an empirical numerical-floor audit passed.

Remaining numerical limits include double-valued parameters and residuals,
rotations, interpolated velocities/design rows, long-double polynomial weights,
and the existing query-node construction. Subtracting a tiny relative time offset
from a much larger node time can still quantize it. The proposal intentionally
does not change that polynomial representation or its stencil. `preciseDistance`
returns a single long-double value for light-time iteration; that rounding is
divided by c before affecting the transmitter state. No arbitrary-precision or
complete-flight-Jacobian claim is made.

The complete `apply_extension.apply(..., numerics=True)` installer checks for
incompatible position-remainder markers immediately after verifying the pinned
upstream commit, before creating directories, copying headers or running any
patcher. Direct QR-stage entry retains the same guard. Legacy installation
without `numerics=True` is unchanged.
