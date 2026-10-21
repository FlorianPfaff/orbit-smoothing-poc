# V4 fit failure investigation

`scripts/analyze_v4_fit_failures.py` reads bounded captures of an existing
campaign. It does not connect to the execution host, run a native process,
resume an attempt, change thresholds or rewrite the frozen results. The output
describes only the captured terminal prefix, not the current live campaign.

Run it with the four separately collected evidence files and the actual
optimizer source used for stage attribution:

```sh
python scripts/analyze_v4_fit_failures.py \
  --terminal /absolute/evidence/terminal-details01.json \
  --points /absolute/evidence/point-details01.json \
  --search /absolute/evidence/nuisance-search01.json \
  --memory /absolute/evidence/memory-closure01.json \
  --optimizer-source /absolute/frozen-source/src/orbit_poc/numerics/optimizer.py \
  --output /absolute/outputs/investigation01
```

The output directory must be new. It contains `report.json` and `index.html`.
Capture hashes and the analyzer/optimizer hashes are computed from bytes read
during analysis. Original remote-file hashes embedded by the collector are
preserved as collector claims; this offline analyzer cannot rehash remote files
from decoded JSON. A separate canonical content hash identifies each decoded
record. Captured log heads/tails are excerpts, not complete logs.

The analyzer checks the actual optimizer's ordered initial, repeat and closure
refinement calls before attributing an attempt to the period before its first
optimizer trial. Missing point details produce an unknown stage. Intermediate
`qr.N.profile.json` filenames indicate progress only. A strict completed native
profile requires a zero-exit, non-timeout execution record and explicit
convergence without a numerical-floor limitation; it is not an accepted orbit
fit. A supervisor's `complete` means its worker returned, and can accompany a
scientifically failed result.

The first capture contains 30 terminal attempts: 18 timeouts, eight process-tree
memory-limit stops and four native failures. All stopped before the first
optimizer trial. Fifteen timeouts occurred in the initial native nuisance
profile. The remaining three quiet 24-hour pulse attempts completed their cold
initial and repeat profiles, then stopped during closure refinement. The 48-hour
density memory stops reached native profiling. Nested closure evidence corrects
the initial interpretation of the 72-hour density file listings: `closure-01`
exists and its logs reach `OrbitPocEvaluateVariational` after writing the native
variational archive, without a completed execution receipt. Absence of a
top-level `closure.json` does not mean closure was never started. These observations
identify the last logged program, not the allocating function, and do not prove
a kernel out-of-memory kill.

The four 72-hour pulse failures reported the generic zero-update replay guard.
Their nuisance-search records also contain explicit 300-second child trial
timeout errors and unsuccessful zero-update replay statuses. Failed replay
execution does **not** demonstrate an objective or cached-state change: its
placeholder cost is not a scientific measurement. The current capture does not
record the replay's own error, so it does not by itself establish that replay's
failure as a timeout. An execution-error diagnostic must retain that distinction.

No report from this tool authorizes release, covariance acceptance, benchmark
reclassification, removal of the cold checks or relaxation of scientific
thresholds. Correctness and performance fixes require separate reviewed changes
and their own evidence; the original campaign remains intact.
