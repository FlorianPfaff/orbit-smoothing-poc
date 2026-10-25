# Two one-hour cold full fits: pulse passed, density failed

Both candidate04 attempts ran on 25 October 2026 using their original retained-observation GNSS-only initialization, zero initial disturbance coordinates and no nuisance donor. The serial controller ended at **09:04 Europe/Berlin**. The [HTML report](index.html), [machine-readable report](report.json), [CSV](summary.csv) and original terminal receipts retain both outcomes.

| Case | Result | Backend fit time | Supervised time | Peak process-tree memory |
|---|---|---:|---:|---:|
| Pulse | Strict full-fit pass; accepted local covariance | 2,559.46 s | 3,546.24 s | 382,865,408 B |
| Log density | Native propagation failure on first trial; no accepted covariance | 1,272.85 s | 1,622.65 s | 382,791,680 B |

These are separate engineering regressions, not substitutes for frozen v3.1/v4 attempts or a scientific accuracy comparison. Timing includes substantial integrity and inventory I/O; the table does not establish a speedup. Neither attempt hit its two-hour or 8 GiB limit. Both supervisors verified owned-process cleanup, with no received signals.

## Pulse result and limits

The pulse fit completed **10 accepted trials**. Its freshest undamped final covariance point has full rank **91/91**, normalized gradient **8.35656500814021e-9**, maximum position correction **1.0588035919612342e-8 m**, and pulse correction **6.181421462221263e-13 m/s**. These meet the unchanged thresholds. Final nuisance convergence is strict, with two sufficiently small updates and a fresh full-system confirmation of **2.2153862437060773e-11 m**, below the 1e-8 m threshold. It is not nuisance-floor-limited.

The [strict result](evidence/one-hour-run01/cold-pulses/strict-result.json), [fresh nuisance profile](evidence/one-hour-run01/cold-pulses/fit/point-019-final-covariance/qr.profile.json), [factor diagnostics](evidence/one-hour-run01/cold-pulses/fit/point-019-final-covariance/qr.7.diagnostics.json), final factor/RHS and parameter metadata are packaged. Accepted covariance is a **local Gaussian, nuisance-marginalized covariance conditional on the fixed model and hyperparameters**. No coverage, accuracy superiority, multi-day capability, flight capability or release readiness follows from this one result.

The final accepted trial reduced the objective by **6.620211934205145e-9**, below the measured numerical floor **7.22743607184384e-6**. This unresolved reduction is disclosed rather than used to certify convergence. The independent fresh, undamped final stationarity and nuisance checks provide the completion authority. [Full iteration history](evidence/one-hour-run01/cold-pulses/fit/iterations.json) retains that distinction.

## Density failure, preserved without replacement

The first density trial failed in `point-004-trial-001/closure-02` with **“Nonfinite equinoctial reference input”**. [Native failure log](evidence/one-hour-run01/cold-density/fit/point-004-trial-001/closure-02/propagate.log), [execution receipt](evidence/one-hour-run01/cold-density/fit/point-004-trial-001/closure-02/propagate.execution.json), [backend result](evidence/one-hour-run01/cold-density/backend-result.json) and [strict assessment](evidence/one-hour-run01/cold-density/strict-result.json) are included. It had zero accepted iterations and no accepted covariance. The generic strict-assessment error means the failed backend result cannot qualify as complete; the propagation log records the actual native failure.

The saved trial log-density spans approximately **−11.58 to +20.38**, with a maximum proposed density multiplier of **7.073e8**. This is an unaccepted trial, not an inferred atmospheric density or a valid fitted solution. Its first propagation completed before the second propagation rejected the reference input. This packet records the failure and extreme proposal; it does not claim to identify the exact nonfinite element or validate a correction. A separate candidate must diagnose the cause and pass its own tests. No density clipping, prior change or threshold relaxation is represented here.

## Exact problem and provenance

Both are one-hour, quiet, normally tracked 500 km synthetic cases for 24 April 2024, seed 300000. Pulse settings remain 1,200 s and 1e-4 m/s. Density retains 60 s knots, **tau 7,200 s and sigma 0.3**. Candidate04's executable SHA256 is `28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d`; the source snapshot identity is `c3655f86f04ec4990f88accc092c41f2ac539d8a84300b69e7bac16f3d4ef260`.

The exact original requests and their three runtime-only rebindings are packaged. [Plan summary](plan-summary.json) and [scientific input bindings](scientific-input-bindings.json) derive from the original 7,465,129-byte frozen plan; the [execution freeze](evidence/one-hour-run01/freeze.json) binds its exact SHA256. The original full plan and Python runtime inventory remain external, as do source datasets, executable binaries, full row archives and bulk trajectories. [External evidence](external-evidence.json) identifies these omissions explicitly. A hash copied from a completed backend receipt is labeled with that authority; publication does not imply that every bulky artifact was independently rehashed.

The packet includes the 50 passing control tests, the exact 583-check independent prelaunch review, earlier control-test fixture failures, verified namespace/configuration preflight and detached launch receipts. **Prelaunch audits do not substitute for a terminal scientific audit.** Original evidence bytes are unchanged, including their historical absolute paths; [source-map.json](source-map.json) provides portable packet locations. [manifest.json](manifest.json) covers all packet files except itself. The portable checker validates exact membership, bytes, summary derivation, preserved failure, cold request identity and local links. `--verify-originals` additionally checks source-copy identity on the original host.

The earlier [eight-check recovery14 publication](https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/176b4a69be74ee0c6699c7b15097ef15518d4cd8/validation/v4-fit-reliability/recovery14/README.md) remains unchanged. Its statement that these fits had not yet launched describes that earlier snapshot; this packet supplies their subsequent outcomes. Publication launches no new native computation and changes no frozen benchmark, executable, scientific setting or compatibility default.
