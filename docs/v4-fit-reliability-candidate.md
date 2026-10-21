# Isolated v4 fit reliability candidate

This branch investigates the frozen v4 failures without changing that campaign,
its executables, its results, or its correctness thresholds. It starts from
`b8608cf75fe8dc73e661b863cab7bce96adab3eb` on `segmented-v4`. Candidate runs are
component experiments, not replacements for any frozen fit attempt.

## Changes and compatibility

Three controls default to the original execution path:

| Control | Default | Candidate behavior |
| --- | --- | --- |
| `ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY` | `0` | `1` stops a nuisance search immediately after an invalid mandatory zero-update replay. The caller still rejects the point. |
| `ORBIT_POC_NUISANCE_COST_ONLY_DESIGN` | `0` | `1` omits unused dynamic observation derivative interpolation during cost-only child evaluations. Full linearizations and all nuisance derivatives, measurement residuals and prior rows remain computed. |
| `ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS` | `0` | A canonical integer from `1` through `65536` bounds derivative rows in fixed-parameter closure evaluation. All parameter columns and chronological native integration remain intact. |

The first two switches accept only `0` and `1`. Malformed values fail explicitly.
The zero-update replay diagnostic now records its execution error, distinguishing
a failed child process from a measured objective or state change. Timing and RSS
for that replay remain in the separate performance sidecar.

The caller also rejects invalid replay support, row counts and nonfinite
diagnostics explicitly. Valid default-path behavior is preserved; malformed
replay rejection is strengthened. Cost-only omission still runs native query,
stencil and time-remainder validation, but cannot detect nonfinite values or
overflow in derivative entries it does not compute. Full parent and final
linearizations retain those derivative calculations and checks. The candidate
evidence therefore concerns the tested finite-data profiles, not every possible
malformed derivative input.

The 300-second isolated-child deadline, two-hour fit deadline, 8 GiB process-tree
RSS limit, strict convergence requirements, cold initial/repeat/refinement checks,
physical models, priors, weights and covariance rules are unchanged. No warm-start
implementation is included. Small or floor-limited progress cannot authorize
covariance.

## Fresh pinned build

Use a new source tree and build directory; do not install over a campaign tree.
The upstream GROOPS commit remains
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`.

```sh
python scripts/build_groops.py \
  --source-dir /absolute/candidate/native-source \
  --build-dir /absolute/candidate/build \
  --prefix /absolute/pinned/compiler-and-libraries \
  --cmake-executable /absolute/pinned/cmake \
  --jobs 4 --numerics --segmented --wide-tangent-candidate \
  --nuisance-performance --variational-memory-candidate
```

The build manifest includes the installed extension hashes, complete compiled
source inventory, compiler and CMake identities, and executable hash. Execution
must also pin linked libraries. Compiler parallelism is separate from numerical
execution: run native validation and each measured profile serially with one
BLAS/OpenMP thread and current-host admission/owned-process cleanup.

The builder rejects profile changes on reuse and rejects a memory overlay without
the required nuisance-extension provenance before any installer can overwrite it.
No public comparison or segmented command defaults change.

## Evidence and limitations

The [candidate02 report](../validation/v4-fit-reliability/candidate02/index.html)
contains the audited component results, source/data/runtime identities and
retained failures. It also includes environment-specific reproduction controls;
the original external datasets and pinned toolchain are required.

The first candidate exposed four compatibility failures in the unchanged 106-test
suite: the old tests expected 17 unsuccessful proposals after an invalid replay,
whereas unconditional early exit produced zero. All four still rejected and
preserved parent state; the 51 correction regressions passed. Candidate02 makes
early exit explicitly opt-in and adds separate tests for both behaviors. The
original test files and failed candidate01 evidence are preserved.

The first copied GNSS profile harness omitted output directories. All eight
processes exited without producing a usable receiver or QR estimate. The strict
checker rejects all four comparisons. Those elapsed times are not performance
samples. A separately versioned harness creates output parents before freezing
and launching; no failed result is overwritten.

The [failure analysis](v4-fit-failures.md) describes the captured 30-attempt prefix.
The [memory candidate](variational-memory-candidate.md) explains the blocked
closure component. The 48-hour GNSS profile still retains large derivative
matrices when it forks nuisance trials. Fixing closure storage does not resolve
that later memory limit. A safe follow-up needs independently validated derivative
storage and lifecycle changes; changing RSS accounting would not be a fix.

Even successful small profile equivalence and closure replays do not establish
72-hour fit convergence, accepted covariance, completed v4 release gates or
accuracy superiority. All such claims remain withheld.
