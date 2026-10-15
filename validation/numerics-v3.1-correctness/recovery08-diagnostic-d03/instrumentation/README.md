# D03: full-row nuisance diagnostic

This separate installer targets a fresh generated GROOPS tree after applying the
unchanged source04 extension at candidate07 commit
`8e4d36f7c47d57acdb9fa30d15a6005189bbf221`. It is a diagnostic instrumentor,
not a numerical correction or an acceptance test. The prescribed validation08
must finish and its owned processes must be cleaned up before any D03 native
build or replay is launched. Bulky trace files remain outside Git.

Use `python install_nuisance_trace.py --tree NEW_GENERATED_GROOPS_TREE --receipt NEW_RECEIPT`.
Every target anchor is checked before any write. The installer refuses an already
instrumented tree. Preserve its source hashes and installation receipt.

Both diagnostic-off and diagnostic-on use
`ORBIT_POC_D03_MAX_GENERATIONS=4`. Only diagnostic-on sets
`ORBIT_POC_D03_DIRECTORY` to a pre-created absolute trace directory. Traces cover
all rows and estimated parameters at QR generation4: baseline linearization,
the joint nuisance recovery, and trial alpha1/alpha0. Other trial outcomes remain
in the unchanged native line-search journal. No sampling of rows is performed.

The first attempt to start non-cost generation5 writes
`<ORBIT_POC_NUMERICS_QR_PREFIX>.diagnostic-incomplete.json` and throws
`D03 diagnostic generation limit reached; scientific validation incomplete`.
Its exact JSON is:

```json
{"schema":"orbit-poc-d03-generation-stop-v1","diagnostic_only":true,"scientific_complete":false,"completed_generations":4,"reason":"bounded diagnostic stopped before generation5"}
```

The failed diagnostic process must have no timeout, verified owned cleanup,
exactly generations1–4, and this sentinel. Its exit cannot count as scientific
completion or authorize covariance. No successful profile or accepted fit may
be inferred from the deliberately bounded run.

Before interpreting any trace, compare original08, diagnostic-off and
 diagnostic-on with `verify_trace_equivalence.py --reference ORIGINAL_POINT006
--trace-off OFF --trace-on ON --last-generation 4 --receipt NEW_RECEIPT`.
Original08 must have a contiguous longer sequence; both diagnostic runs must
contain exactly four generations. Missing original factors are accepted only
through their original completed retention receipts and a matching false
`keep_intermediate_factors` policy. The final diagnostic factors cannot be
substituted by retention metadata. All factors, steps, coordinate exports and
original row bytes must agree, plus JSON numerical values (excluding only the
existing explicit spool path and timing keys). This is 52 checks, not a gate.

Each TSV record has the established D02 sixteen columns: QR stem, phase, alpha,
receiver, transmitter, epoch, row, component, stage, scalar kind, index, exact
hexfloat value, binary64 bits (or `-` for extended values/text), evaluation ID,
record event ID and arithmetic-audit mode. Per-process files avoid interleaved
fork writes. Floating exception state and errno are restored after formatting;
no writable descriptor is retained across a fork.

The ledger captures all retained original residual high/low pairs, their rounded
native targets, local STEC prior rows, and separate epoch/global constraint rows
with global parameter IDs. Global design blocks come from the actual mapped
`GnssDesignMatrix::mult` inputs, before elimination; local design B and recovered
STEC updates remain separate. Native global and joint influence values are
recorded for independent reconstruction, with full parameter names and native
before/requested/after coordinates. Capture includes raw clock seconds and
metres/division operands, local STEC+dSTEC and VTEC updates, shared signal-bias
arrays, ambiguity cycle coordinates and T mappings.

Geometry taps include distance high/low before narrowing, light travel seconds,
clock-plus-travel duration, nominal/rounded times and remainder; interpolation
node times/values/weights and precise/native results; receiver/transmitter center
and antenna offset composition; transmitter velocity interpolation and its
native output; and distance, Shapiro, relativistic dot, geometric and clock
contributions to the precise range. The complete observed/sigma/LOS and native
STEC coefficients remain available to identify component rounding.

Analyze original-row sums independently: requested mapped `A*x+B*local`, then
mapped actually stored updates, versus the observed high/low residual change.
Compare per-row reductions and their compensated aggregate with the original
prediction and actual reduction. Initialization/recovery-only equations are not
original objective rows; identify them by the retained-original stages. Account
for every retained row and separate constraint; missing support invalidates the
analysis. Changes in native coefficient values or nonlinear geometry must be
reported separately from stored-state quantization. No observed discrepancy
justifies changing a floor threshold without a separately versioned correction
and the complete unchanged validation suite.
