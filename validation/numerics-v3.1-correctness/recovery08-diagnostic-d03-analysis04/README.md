# D03 analysis04: clock-plus-travel arithmetic attribution

Analysis04 extends the sealed analyses01–03 snapshot with an exact algebraic decomposition of the same captured generation4 full trial. Every component includes all8,064 GNSS measurement rows; the full9,469-row objective accounting is unchanged. Both independent reviews passed, with component-sum closure within1.70e-107.

Clock-plus-travel duration addition contributes−2.68673436e-14 of the−2.68691010e-14 distance-clock discrepancy (99.9934596%). This is measured algebraic attribution around captured baseline kinematics. Query-arithmetic terms use the captured linear coefficient and retain explicit motion and closure residuals; it is not an executed corrected-forward-model counterfactual.

Each table contribution is the sum of that normalized residual component change multiplied by the mean baseline/trial row residual; it is not a measured gain from a corrected native fit.

| Component | Contribution |
| --- | --- |
| Clock-plus-travel duration addition | -2.686734362e-14 |
| Coefficient/weight scaling rounding | +1.486462375e-24 |
| Exact fixed-point versus first-order clock coefficient | +4.545919366e-20 |
| Final light-time iteration residual | -7.142484012e-21 |
| Range-projection remainder | -2.202036354e-27 |
| Receiver position versus moving-clock kinematics | -1.467556673e-22 |
| Transmitter position versus captured-duration kinematics | -1.681954286e-18 |
| Travel-distance cast and division | -1.135675879e-19 |

The smaller measured terms remain in the table and full result. This evidence supports testing a narrow arithmetic correction. It does not show that such a correction passes the unchanged objective gates, the failed second replay, covariance checks or the full v3.1 release requirements. The original execution08 result remains failed; no scientific gate or acceptance threshold is replaced.

The new analyzer is separately versioned; its54 fabricated tests and independent review are preserved. Analyses01/02 failures and completed analysis03 remain unchanged in the preceding snapshot. No native fit was launched by this analysis. The three pinned raw traces (4,445,392,754bytes) remain external. Publication copies tokenize paths and record both original and published hashes.

- [Preceding analyses01–03 snapshot](../recovery08-diagnostic-d03/index.html)
- [Actual execution08 failure](../recovery07-08/index.html)
- [Full analysis04 result](analysis-attempt04/result.json.gz)
- [Actual invocation receipt](analysis-attempt04/receipt.json.gz)
- [Attribution/runtime review](reviews/d03-analysis04-attribution-review-01.json.gz)
- [Independent component review](reviews/d03-exact-geometry-independent-result-review-01.json.gz)
- [Independent54-test review](reviews/row-trace-d03-analyzer-independent-review-03.json.gz)
- [Summary](summary.json)
- [Manifest](manifest.json)
