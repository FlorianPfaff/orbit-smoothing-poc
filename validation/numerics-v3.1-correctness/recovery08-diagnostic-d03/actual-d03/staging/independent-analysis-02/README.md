# Independent D03 analysis

This helper reads the generation4 full-row diagnostic. It does not run GROOPS or
change a fit. Run it only after original08, diagnostic-off and diagnostic-on pass
the exact 52-check equivalence comparison and all owned diagnostic processes have
terminated. Keep bulky TSV files outside Git.

```text
python analyze_nuisance_trace.py \
  --trace-directory D03/diagnostic/trace \
  --equivalence D03/diagnostic/equivalence.json \
  --factor D03/diagnostic/trace-on/qr.4.factor.json \
  --line-search D03/diagnostic/trace-on/qr.4.nuisance_line_search.json \
  --output NEW_ANALYSIS.json
```

Use the actual replay directories recorded by the equivalence receipt. The
helper checks their association and hashes, and refuses an existing output.
Failures produce a separate `failed_closed` result; preserve that result before
repairing an analysis assumption.

All sums use Decimal110 and exact binary floating primitive values. Binary64
hexadecimal values must match their captured bits. Every original observation
row, including local STEC priors, and every separate constraint must be present.
The total must match the factor's `original_objective_rows`. Recovery-only
equations cannot substitute for retained rows. Both ordinary alpha0 and alpha1
trials are required, with unchanged observations and weights.

The output keeps four calculations separate:

1. The requested original linear prediction from mapped global `A*x`, local
   `B*delta`, and all constraint coefficients.
2. The prediction from the exported `aprioriParameter` coordinate change with
   the requested local increment. This is explicitly a transformed-coordinate
   diagnostic, since a rounded native bias array need not remain in the chosen
   gauge subspace.
3. A direct stored-state observation prediction from actual clock seconds,
   signal-bias operands, ambiguity contributions and STEC changes at the original
   native derivative. It is withheld if the full row mapping cannot be checked.
   Separate constraints use their actual native target changes and are labelled
   as such. Their binary64 arithmetic is unchanged.
4. The actual complete high/low residual change and full objective reduction.

Component objective attribution uses each component's residual change times the
mean complete residual. This symmetric formula conserves the full actual
reduction without assigning cross terms in an arbitrary order. The components
include distance, clocks, Shapiro, the relativistic dot product, each antenna and
bias contribution, ambiguities, STEC, local priors, separate constraints, and an
explicit arithmetic closure remainder.

Raw clock division/storage, ambiguity storage, each bias-family update, and
local STEC/VTEC updates are audited separately. Native STEC observation types are
inferred only when their exact stored-input expression reproduces the captured
model contribution uniquely; otherwise that attribution is unavailable. No type
label is fabricated.

Geometry checks retain the final complete query and the ordered light-time
operand sequence for each equation. The distance directly preceding a travel
assignment is paired with that assignment; the later transmitter-displacement
convergence check is never substituted for the path length. Exact nearest-even
rounding at the pinned x87 64-bit significand separates distance high/low
narrowing, division by light speed, and clock-plus-travel addition. The captured
native operations are compared with that replay; an unmatched replay is exposed.
Velocity interpolation narrowing in the relativistic term and split-time
remainder arithmetic remain separate. All-block summaries and the twenty
largest exact objective-prediction disagreements are reported; a small row
sample is never extrapolated.

The difference between native clock-design prediction and actual distance,
clock, Shapiro and relativistic changes can include omitted derivatives,
nonlinearity and representation errors. These remain competing explanations
until the measured components distinguish them. This bounded diagnostic cannot
authorize covariance, change a numerical floor, pass the required scientific
gates, or complete the frozen150-fit benchmark.
