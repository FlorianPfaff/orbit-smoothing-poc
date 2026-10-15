# Diagnostic history after failed validation06

This package records an arithmetic investigation. **The scientific correctness issue remains unresolved.** It does not replace the [failed validation06 report](../recovery06/index.html), authorize covariance, or certify the original 150-attempt benchmark.

| Evidence | Actual outcome |
| --- | --- |
| D01 | Diagnostic build failed before an accepted binary or replay; cleanup verified. |
| D02, trace disabled | Exact fixed-orbit nuisance replay failed. |
| D02, trace enabled | The same nuisance replay failed; cleanup verified. |
| Numerical equivalence | 104 exact checks across 8 generations passed against the original06 replay and both D02 replays. |
| Decimal analysis | Five selected observation rows; 330 complete equations, 250 paired row evaluations and 800 local-update checks; zero native-arithmetic replay mismatches. Two signed row reductions reverse sign under higher-precision evaluation at the same stored states. |

The row analysis demonstrates rounding in residual composition. It does **not** prove descent, stationarity, or convergence of the complete nuisance objective. Parameter-update rounding outside the measured local STEC/VTEC updates remains outside this diagnostic. A numerical correction requires the complete unchanged correctness suite.

Open [the HTML overview](report.html), [the independent analysis summary](decimal-analysis/row-trace-d02-independent-summary-01.json), [the complete Decimal report](decimal-analysis/row-trace-d02-decimal-actual-01.json), [the equivalence evidence](attempt-d02/diagnostic/equivalence.json), or [the trace inventory](reviews/row-trace-d02-external-trace-inventory.json).

The 51 raw trace TSVs (12,065,394 bytes), row spools, executable and upstream source tree remain outside Git. JSON/log/XML/source copies use named private-path tokens; `manifest.json` records original and published hashes separately. Mathematical values, failure statuses and limits are unchanged. Original raw evidence remains preserved outside Git.

The included diagnostic source and tests are historical artifacts. The path-free analyzer can be checked with `python -m pytest -q -p no:cacheprovider decimal-analysis/row-trace07-analysis-03/test_analyze_row_trace.py --basetemp /absolute/external/pytest-temp`. This runs fabricated arithmetic cases only. Earlier failed fixtures, the D01 compilation failure and the initial analysis guard rejection remain visible.
