# Two original one-hour cold full fits

This control adapter prepares two separate full nonlinear fits using the unchanged candidate04 executable and `orbit_poc.numerics.backend.fit_job`. It does not replace any frozen benchmark result. Only `launch` after an exact independent approval can start native estimation.

The registry fixes the original one-hour quiet/normal 500 km pulse and density requests by SHA256. Runtime rebinding changes only the executable path, executable hash and source identity. Physical models, observations, weights, initialization, masks, priors and numerical settings remain unchanged. Density retains 60-second knots, tau 7,200 seconds and sigma 0.3; pulses retain 1,200 seconds and 1e-4 m/s.

Initialization uses the original prepared nominal orbit derived from retained GNSS observations and the existing nominal closure. The backend's original `initial_state()` supplies its first state and zero density/pulse coordinates. No point-029 physical state or nuisance donor is supplied. The adapter checks the actual first-point state and force files when available.

## Execution interfaces

Use the pinned interpreter with `-s -B`. The expected output is `/mnt/d/orbit-v41-recovery02/one-hour-run01` and new Linux disk scratch is `/home/emper/orbit-one-hour-scratch01`.

```text
python -s -B one_hour_controls.py prepare --output /mnt/d/orbit-v41-recovery02/one-hour-run01 --scratch-root /home/emper/orbit-one-hour-scratch01
python -s -B one_hour_controls.py preflight --plan /mnt/d/orbit-v41-recovery02/one-hour-run01/plan.json --sha256 PLAN_SHA
python -s -B one_hour_controls.py launch --freeze /mnt/d/orbit-v41-recovery02/one-hour-run01/freeze.json --sha256 FREEZE_SHA --audit REVIEW_JSON --audit-sha256 REVIEW_SHA
```

Preparation verifies the audited reference runtime and input bytes, collects exact bindings and records a separate request-rebinding journal. Preflight performs no native estimation: it uses the actual frozen native-input parser, creates private fit configurations for both methods, checks output paths, imports the numerical libraries and verifies the selected native loader dependencies. Preflight is supervised with owned pidfd/subreaper cleanup.

The fresh namespace exposes only system runtime directories, pinned Python/source directories, declared estimation/native inputs, control files and the current output/scratch. It does not bind the host `/`, `/mnt`, `/home`, old results or truth archives. Runtime/source directory membership and file bytes are checked. The numerical environment is an explicit whitelist with one thread; inherited warm-start or loader overrides are rejected.

The independent review must use schema `orbit-poc-one-hour-launch-review-v1` and bind `freeze_sha256`, `runner_sha256`, `approved: true`, `two_original_cold_fullfits: true`, `thresholds_unchanged: true` and `namespace_preflight_passed: true`. Merely preparing files does not authorize execution.

## Limits, outcomes and preservation

Each fit has a 7,200-second supervised limit, 8 GiB process-tree RSS, CPU 4, one numerical thread, 32 accepted iterations and 96 trials. Admission requires 16 GiB available memory and 32 GiB free on both output and Linux scratch. Output, scratch and leaf ownership identities are frozen; cold backing directories must be empty. A checked shared cooperative lock coordinates with the existing reference launcher. No unrelated processes are signalled.

A pass requires a complete, converged covariance-valid backend result, exact source/native/support identities, strict fresh nuisance convergence, an undamped complete final factor, full-rank SVD certification, and the raw correction and gradient from the actual final-covariance point. Earlier optimizer confirmation or the mere existence of covariance files is insufficient. Numerical-floor-limited intermediate progress retains the unchanged native semantics; it cannot authorize final covariance.

Both passes and failures preserve the backend outcome, supervisor, strict assessment, native diagnostics and raw intermediate files. Inner native timeouts retain their timeout attribution. Interrupted or unverified-cleanup attempts stop further launches. Existing output and launch records are never overwritten or silently resumed.

The source-control test suite is distinct from the native correctness suite. `tests05.log` records 50 passing contract and tiny-artifact tests under the pinned Python 3.11 runtime, with no failures or skips. Earlier test logs remain; `tests03.log` contains four fixture errors because its synthetic factor omitted required metadata, not a native estimator failure. `development-test-history.json` records that limitation. An early test import generated two unpinned Python 3.14 cache files; those were preserved outside the old trees in `test-created-bytecode01`, and the loader now compiles verified helpers without writing bytecode.
