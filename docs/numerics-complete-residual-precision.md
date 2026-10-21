# Complete observation residual precision

The opt-in numerical QR path retains a high/low expansion through the complete
GNSS observation residual. The legacy estimation path and native ambiguity
resolution remain unchanged. This is a numerical correction, not a change to
physical models, observations, Gaussian priors, weights or convergence limits.

An independently reproduced trace from failed validation attempt06 identified
rounding in the ambiguity transformation `T * value`. For one selected row,
the rounding changed its apparent objective reduction from approximately
−3.31e−13 to +3.57e−14. The full nuisance step's predicted reduction was only
2.51e−16. The diagnostic executable reproduced 104 checks against the original
executable exactly with tracing disabled and enabled. The trace establishes a
local arithmetic defect; its five selected rows do not establish convergence
of the complete objective.

The correction retains the existing corrected-range expansion, then composes
receiver signal bias and antenna pattern, the transmitter transformation,
float ambiguity transformation and seven active STEC terms in the same
expansion representation. Native coefficients, stored nuisance states and
measurement weights are retained. The appended STEC prior is already weighted
and is not weighted a second time. The QR target is rounded from the completed
weighted expansion, while the original objective ledger retains both parts.

Actual observation-cost reductions use paired products
`0.5 * (before - after) * (before + after)` without first narrowing either
residual. Separate epoch and global Gaussian constraint targets retain their
existing binary64 arithmetic. The reported largest residual change also uses
rounded binary64 rows and is a diagnostic only. These distinctions are
recorded in factor provenance.

The supported native GNSS reducers explicitly maintain the expansion. Missing,
incomplete, nonfinite or inconsistent expansions fail before objective capture.
Active temporal-bias and troposphere corrections are rejected in this initial
precision path; the prescribed synthetic and flight configurations use neither.
The standalone row-solver fixture still accepts exact binary64 rows and has an
additional optional expansion input for independent objective tests.

New tests compare residual composition and paired objective reductions against
100-digit Decimal arithmetic, including identical rounded residuals with a
nonzero true reduction, sign reversal, row ordering and prior accounting.
They supplement the unchanged original 106 native tests and existing 18
regressions. Fresh native build, all four refinements, both objective/prior
checks and both distinct original nuisance replays remain required. Stored
nuisance-state quantization and other component arithmetic remain possible
limitations; no numerical-floor allowance or acceptance limit is increased.
