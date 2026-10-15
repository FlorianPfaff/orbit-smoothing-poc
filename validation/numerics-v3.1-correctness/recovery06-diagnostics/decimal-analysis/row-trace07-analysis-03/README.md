# Independent diagnostic arithmetic replay

This analyzer is separate from the diagnostic overlay and every native estimator. It reads the overlay's 16-column TSV, preserves exact binary64 and long-double hexadecimal values, and uses 110-digit Decimal arithmetic.

Run it only after the original candidate06, diagnostic trace-disabled, and trace-enabled replays have passed the exact numerical-equivalence check. Paths are supplied by the caller; no diagnostic attempt is hard-coded.

```sh
python analyze_row_trace.py \
  --trace /new/diagnostic/trace/row-trace-PID.tsv \
  --trace /new/diagnostic/trace/row-trace-CHILD_PID.tsv \
  --equivalence /new/diagnostic/equivalence.json \
  --output /new/diagnostic/independent-decimal-analysis.json
```

Pass every trace file exactly once. The analyzer rechecks the evidence hashes referenced by the equivalence receipt and binds each trace's artifact stem to its verified trace-enabled directory. Existing output files are never overwritten.

The replay holds the **actual stored nuisance state** fixed. It preserves the original native rounded STEC coefficients, signal-composition matrices, ambiguity transformations and weights, then tracks loss from prematurely narrowing residual arithmetic. The seven STEC operations also have a separate binary64 replay checked against their actual stage outputs. Unsupported nonzero model corrections or ambiguous/missing stages make that equation unavailable instead of silently absorbing the difference.

Local STEC and VTEC updates have explicit before/delta/after operands. For those updates the report separately compares the actual stored result with the high-precision ideal update. VTEC mapping and trigonometric coefficients are native shadow evaluations. Individual ideal updates for clocks, shared signal biases and ambiguities are unavailable in this first trace; their actual snapshots must not be interpreted as exact unrounded updates.

Paired reductions use `(old - new) * (old + new) / 2` for each selected weighted row. The STEC prior is reported separately in its existing units. The five traced observation rows are bounded diagnostic evidence and cannot establish the full objective, a covariance, convergence or a scientific acceptance gate. A native replay mismatch must be investigated before attributing its discrepancy to a particular narrowing stage.

Only an equation segment carrying `retained_original_rows`, equal to its final homogenized residual, can participate in a pair. Reconstructed baseline equations used to recover local nuisance updates are analyzed separately and cannot be mistaken for the retained baseline.

Nested `GnssParametrizationGroup` wrappers are accepted only when their complete traced child sequence reproduces the wrapper's before/after boundaries. Every child is checked; a wrapper cannot hide an unsupported nonzero correction.

```sh
python -m pytest test_analyze_row_trace.py -q -p no:cacheprovider
```

Fixtures cover exact long-double notation, signed zero/subnormal and bit checks, event ordering, complete phase/code STEC arithmetic, native coefficient and weight rounding, ambiguity mapping, missing inputs, nonzero unknown models, repeated evaluations, local/VTEC update rounding, unique pairing, evidence tampering and trace-directory binding.
