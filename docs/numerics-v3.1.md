# v3.1 numerical reliability benchmark

This is a separate numerical experiment at fixed statistical settings. The
running v3 comparison, its calibration and its frozen source/binary remain
unchanged. v3.1 does not select new disturbance hyperparameters, inspect orbit
truth, or establish accuracy superiority.

The commands are `orbit-poc numerics prepare`, `run` and `report`, each with
`--config /absolute/path/to/deployment-config.json`. They are also available
through `python -m orbit_poc.numerics.cli`. Unknown configuration fields and
unregistered profiles are rejected. `run --max-attempts N` is a bounded partial
execution; its report still contains all 150 planned attempts.

## Fixed case matrix

There are 50 cases, each executed with all three profiles:

| Cases | Selection |
| --- | --- |
| 6 | Audited eccentric pulse failures, seeds 300000–300005, 120-minute holdout, 300-second pulses with sigma 0.01 m/s |
| 6 | Their identical-input 0.001 m/s pulse neighbors |
| 2 | First slow eccentric density pair, seed 300000, 30/120-minute holdouts, tau 600 s and sigma 0.03 |
| 4 | Saved April 24 normal/blackout controls for both methods, at their exact saved parameters |
| 32 | Four regimes × quiet/disturbed × normal/blackout × two methods |

The retained fixtures are bound to the exact checked-in pulse-failure,
first-density-score and four-fit engineering ledgers, including their SHA256
digests. There is no search for another successful example if one is missing.
Retained failures are deliberate stress fixtures and must be distinguished from
the prospective cases in interpretation.

The complete selection is recorded in
[`case-selection.json`](../validation/numerics-v3.1/case-selection.json).
[`retained-case-receipts.json`](../validation/numerics-v3.1/retained-case-receipts.json)
records the read-only check of all 18 historical request/result/preparation
records. These receipts do not replace the execution-time hash checks of bulky
input files or establish that the new native runtime has passed its gates.

Prospective cases use seeds 510000 (quiet) and 510001 (disturbed), 24-hour arcs,
30-second observations and a blackout at elapsed hours 11–13. Their epoch and
truth-generator recipe are the v3 synthetic recipe. The pulse parameters are
1200 s and 1e-4 m/s; density parameters are 60-second knots, tau 1800 s and sigma
0.1. Sixteen observation preparations are shared by the two methods. Pinned
prior protocol/seed manifests must establish that these seeds have not already
been used; a known overlap blocks preparation. This audit does not make claims
about unrecorded experiments. These cells share two seeds, and coverage variants
and methods reuse underlying realizations; they are not 32 independent trials.
Timing ratios are descriptive and have no independence-based confidence intervals.

The profiles are `legacy_v3`, `qr_lm_legacy_jacobian` and
`qr_lm_staged_jacobian`. Every case uses the same retained observations,
preprocessing, weights, priors and initialization across profiles. Profile order
rotates deterministically between cases to avoid always assigning one profile
the first execution. Attempts run serially with one BLAS/OpenMP thread, so timing
does not depend on competing benchmark workers.

## Preparation and immutable provenance

`configs/numerics-v3.1.json` is an explicitly unconfigured deployment template.
Blank runtime/input/process pins are not readiness evidence and cause a clear
block. Copy the template **outside the source tree** before filling deployment
paths: the source digest includes `configs/`, so putting its own final digest
inside that tree would create a circular identity.

Both runtimes require their source-tree digest, Python executable path/digest
and native executable path/digest. The archived profile runs the original
`orbit_poc.comparison.backend.fit_job` in a separate pinned interpreter and
source tree. It is not emulated by the new optimizer. Its original 32-density /
12-pulse iteration policy remains unchanged. The two new profiles call
`orbit_poc.numerics.backend.fit_job` from the new pinned source snapshot.

A native library manifest may be supplied with exactly `directory` and `files`;
each file has `path` and `sha256`. All files must lie in that directory. When
present, the subprocess uses that verified directory as its library path.
The Python invocation path preserves its virtual environment rather than
following the final executable symlink to the base interpreter. Python package
trees can be pinned through an optional execution-context receipt. The local
mirror deployment uses that receipt for full package/shared-data content manifests,
the common unprivileged mount-namespace wrapper, host identity and smoke checks.
The harness verifies the receipt hash on preparation and resume; it does not
interpret arbitrary commands from the receipt. Inherited diagnostic
and numerical `ORBIT_POC_*` environment overrides are removed from each worker.

`prepare` first saves a source/config/case/profile plan. It then verifies the
retained requests and all raw/converted estimation artifacts, generates the
prospective inputs, and freezes a complete input manifest before any fit can
start. Preparation invokes the established blind preparation pipeline with the
new pinned binary. A separately supplied prepared-input catalog may instead
provide the 16 prospective preparations. Its schema is:

```json
{
  "schema_version": 1,
  "entries": [
    {
      "case": {"...": "the complete exact prospective case"},
      "request": {"path": "/absolute/request.json", "sha256": "64 lowercase hexadecimal characters"},
      "result": {"path": "/absolute/result.json", "sha256": "64 lowercase hexadecimal characters"}
    }
  ]
}
```

The catalog itself is pinned in configuration. Every result must match its
hashed preparation request and requested case. Its estimation files are verified
again; the catalog is not an exemption from input validation. Truth/reference
and held-out measurement artifacts never enter a fitting request or the frozen
estimation inventory. Synthetic generation may produce truth as usual, but the
benchmark harness does not open its arrays.

`run` requires the complete input freeze. Source, configuration, runtime and
input changes require a new output directory. Existing terminal checkpoints,
including failures and unresolved ranks, are verified and reused without
re-execution. An interrupted directory without a terminal checkpoint blocks
automatic continuation pending an explicit recovery review. There is no
automatic retry, substitute case or source-updating resume.

## Protecting the existing campaign

Execution requires a pinned protected-process receipt containing exactly:
`schema_version: 1`, `pid`, `/proc/PID/stat` field-22 `start_ticks`, `boot_id`,
SHA256 of the raw NUL-separated `cmdline` bytes, and nonempty `scope_tokens`.
Tokens identify the old campaign directory and runtime paths, so detached or
restarted workers are also detected. This is a process identity check, not just
a PID-exists test.

By default, active v3 scope blocks execution. A configured CPU reservation is
usable only if it is inside the calling process's affinity and disjoint from
every protected process's affinity. A receipt with unavailable/unverifiable
information is not treated as evidence of free resources. The default memory
policy requires 16 GiB available: an 8 GiB reserve plus an 8 GiB worker budget.
The resource check runs again before every preparation or fitting subprocess.

Each worker starts a separate process group. The external two-hour wall limit,
process-tree RSS limit or output-filesystem reserve terminates the group and records
a resource failure. A fit starts only with at least 64 GiB free output storage;
the worker stops if free space falls below its frozen 16 GiB reserve. Filesystem
free space is sampled once per second, separately from the 50 ms RSS sampling.
The new solver additionally has 32 accepted iterations and 96 trial evaluations.
Baseline and new profiles receive the same external resource limits. RSS is
sampled at 50 ms and sums parent/descendant RSS; shared pages can therefore be
counted more than once. It is a conservative guard, not an exact physical-memory
measurement.

## Generated-file retention

`generated_intermediates_v1` applies after each terminal new-profile attempt.
Every log, JSON/TSV diagnostic, physical parameter file and final result artifact
is retained. Original prepared inputs, symlinks and archived-profile outputs are
never deleted. Superseded triangular factors and generated closure/proposal
binaries are removed only after recording their path, role, size and SHA256.
For a failed attempt, its last available triangular factor is retained explicitly
as a diagnostic; this does not make its covariance accepted. The receipt includes
any cleanup failures. Cleanup follows measured fitting time and records its own
elapsed time. Native intermediate-factor retention within a live fit is a separate
opt-in mechanism documented with the QR implementation.

Storage estimates distinguish transient row-spool space from retained results.
A bounded engineering check of the retained 24-hour density fixture, using the
earlier globally retained VTEC topology, measured 5,204 columns, a 216,652,944-byte
factor and an 8,062,878,120-byte row spool. Sampled summed process-tree RSS peaked
at 3,368,103,936 bytes. This was one completed factor and one nuisance trial,
not a converged fit or benchmark timing. Two closed row ledgers compressed from
1,458,253,598 to 15,640,657 bytes in 6.93 seconds with round-trip hash verification.
A closure's variational archive contained 7,193,208 bytes, independent of the
number of density parameters. A subsequent engineering check with local
clock/VTEC elimination and staged derivatives measured 2,384 retained columns,
a 45,467,664-byte factor and a 3,640,712,040-byte row spool; sampled summed RSS
peaked at 3,033,952,256 bytes across two factors and six nuisance trials. It used
a development binary while nuisance convergence remained under repair, so it
certifies resource shape only. Forecasts use 229 evaluated points as a conservative control-flow estimate, with up to
16 closure passes per point, including objective-floor refinements and repeated
confirmation refreshes. This is not a strict upper bound; 96 trial steps alone
do not bound the output count, and wall/disk guards remain authoritative. Retaining every generated closure
until terminal cleanup can exceed the physical backing reserve. Every retained
generation's parameter and objective metadata also counts toward capacity.
Final build identity, storage policy and free-space checks remain prerequisites
to freezing the production benchmark.

During trajectory closure, explicitly completed closure directories receive a
separate retention receipt. The current orbit and variational binary pair stays
available; older completed pairs are removed only after their hashes and sizes
are saved. Exported closure trajectories are losslessly compressed after the
optimizer reads them, using the same verified gzip procedure as row ledgers.
Unmarked partial closures and all logs, reference parameters and initial-state
design files remain. This reduces retained closure binaries to one pair per
evaluated point; these maintenance costs remain inside fitting time.
Failed-attempt terminal cleanup preserves those current pairs and unmarked
partial closure binaries as diagnostic artifacts, without accepting covariance.

After a linearized proposal has been read and its correction metrics computed,
its unused orbit binary is released after recording its path, SHA256 and size.
The full trajectory text remains as verified gzip, with the metrics, physical
parameter vector, configuration and logs. Partial or failed proposals are not
selected for online cleanup. Terminal cleanup also records every deletion proof
before unlinking; an interruption preserves that proof and any recovery status.

## Results and acceptance

The JSON and standalone HTML report include all 150 slots: completed, failed,
unresolved-rank, memory/disk/wall-time-limited, interrupted and not-yet-run attempts. A
terminal execution count is distinct from valid convergence with undamped
covariance. Missing legacy diagnostics remain unavailable, not zero.

Each result retains its request/input/runtime hashes, numerical diagnostics,
failure reason, end-to-end worker time and process-tree RSS. Timing summaries
include failed work. Descriptive paired timing ratios use only jointly valid
cases, with their denominator and all 50 paired outcome transitions shown
alongside them. There is no comparison of raw penalized objective values across
different methods or statistical settings.

The report separately compares `legacy_v3` to `qr_lm_legacy_jacobian` and the
two new profiles. The first contrast includes the solver/controller, shared GNSS
interpolation/time/range arithmetic stabilization, and nuisance-coordinate
bookkeeping corrections, including code/TEC prior coordinates after ambiguity
recentering. Both new profiles use the forward numerical stabilization; it is
not part of the staged derivative effect or a change to the physical forces,
observation weights or intended statistical model. It is not a pure linear-algebra
replacement; identical-row equivalence is a separate gate. The second contrast
combines staged tangent derivatives with local long-double accumulation of
mean-force integration moments. Physical forces, quadrature weights and windows
are unchanged, but this is not a Jacobian-only contrast. Selected refinement
checks bound the combined numerical change without separating its contributions.
All 100 planned pairs remain visible. Valid pairs use
exactly matched Cartesian epochs, with position and velocity differences and
Frobenius differences for each covariance block in its own physical units.
There is no interpolation to hide an epoch-grid mismatch.

Carrier-phase prediction differences are the negative differences of native
phase-recovery residuals, including the fitted nuisance terms. The complete
epoch/PRN/signal sets, observation values, weights and ambiguity-track bounds
must match; an intersection-only comparison is rejected. The archived backend
already writes this diagnostic when native diagnostics are retained. The
harness indexes that existing file from the archived native XML and hashes it,
without modifying archived code. Direct code prediction differences remain
unavailable and are explicitly reported as such. These are numerical
comparisons, not accuracy errors against truth.

Required numerical checks remain objective/gradient correctness, rejection
rollback, full-prior preservation, explicit rank handling and final undamped
nuisance-marginalized covariance. The harness does not infer those checks from
process success. It requires converged, nuisance-marginalized covariance, matching
native/physical model identities, a retained state/covariance artifact, reference
isolation and a matching retained preprocessing-audit digest. The harness independently reads the retained Cartesian NPZ and verifies ordered finite epochs, six-state dimensions, finite values and positive-definite symmetric covariance; a hash or success flag alone is insufficient. The three profiles
must agree on that audit for each case. New profiles must retain numerical
diagnostics for review. Native engineering validation and the full
benchmark must finish before claiming v3.1 numerical or runtime improvements.

The report separately counts accepted physical steps that used empirically
floor-limited nuisance profiles at either endpoint. Such progress requires the
sum of endpoint resolution estimates to be at most 0.001 of predicted reduction,
with gain ratio above 0.0001 after subtracting that estimate. The empirical
estimate is not a rigorous error bound or proof of a nuisance minimum. These
profiles cannot establish convergence or accepted covariance; those still need
fresh strict nuisance stationarity. Missing legacy profile flags remain
unavailable, and failed or limited confirmation checks remain visible.

Harness tests exercise the exact 50/150 enumeration, strict configuration,
shared prospective inputs, source/input tampering, immutable failure resume,
incomplete and corrupted reports, PID reuse and CPU-affinity protection, real
archived-source subprocess imports, and whole-process-group timeout cleanup.


## Fast working storage and physical capacity

An optional `archive_dir` applies the same terminal-attempt archival policy to
all three profiles. Fit on a common fast filesystem, then clean generated
intermediates, copy every retained file and symlink, verify its complete byte
inventory, and atomically publish a link at the original attempt path. Original
artifact paths stay usable. The source is removed only after successful
verification. Interrupted copies/publication resume from `archive-index`;
failed fits receive identical preservation. Copy/verification costs are outside
fit timing and retained in archive receipts. Filesystem permission bits are not
part of byte identity across filesystems.

`preparation_dir` optionally keeps fresh preparation on a separate data volume.
`resources.physical_backing_path` enables a second disk guard for sparse virtual
disks: its free bytes must stay above `minimum_free_backing_bytes` (at least
40 GiB), checked before launch and once per second during the worker. This is
additional to the output filesystem's 64/16 GiB launch/run thresholds. Disk
exhaustion is a failed attempt, never successful convergence.

A common D/DrvFs working volume is the prepared deployment alternative when
physical C capacity cannot safely support further WSL disk allocation. It uses
the existing interfaces: set `output_dir` on D, leave `archive_dir` empty because
outputs already reside on permanent storage, and point `physical_backing_path`
at D without changing the 40 GiB reserve. All three profiles use the same policy.
The shared namespace mounts C, source trees, runtimes and inputs read-only,
binds `/tmp` and the Python temporary directory to D, and disables bytecode
writes. Host applications and WSL-managed metadata/swap remain outside this
namespace's write policy. The HTML report includes the pinned storage policy;
measured wall time includes DrvFs I/O and does not isolate intrinsic solver CPU
speed. A representative D-backed resource check remains required before freeze.

A runtime's optional `supplemental_sources` points to
`{"schema_version":1,"files":[{"path":"...","sha256":"..."}]}`. Every
listed file must be unique and inside that runtime source tree; hashes are
checked before and after each attempt. This pins native Fortran extensions
without changing the archived v3 source-hash algorithm. Full Python environment
inventories belong in the pinned execution context and startup verification.

The report separates `execution_complete` (150 terminal checkpoints) from
correctness gates. The execution context may supply `acceptance_gates`, each
with `gate`, `status`, `scope`, and a pinned `receipt`. Required gate identifiers
are `qr_independent_agreement`, `rank_and_invariance`, `objective_and_priors`,
`rollback_and_convergence`, `synthetic_derivatives`,
`flight_derivative_approximation`, `propagation_refinement`, and
`pipeline_and_provenance`. Missing or changed receipts keep release status
pending. Even with all receipts and attempts complete, the report says ready
for review; it does not infer correctness from terminal counts or certify a
complete flight Jacobian.

Memory in the comparison report comes from the outer harness, which samples the
worker and all recursive children. This includes forked native nuisance line-search
trials. Summed RSS can count copy-on-write pages more than once. Native parent RSS
and per-child `wait4` maximum RSS are separate diagnostics; adding separate maxima
is an upper bound, not a measured simultaneous peak.

Before launching the frozen benchmark, run `scripts/verify_numerics_runtime.py`
inside the common read-only runtime namespace. It takes `--config`, `--receipt`
and an optional command after `--`. The execution context must pin both
`runtime_manifest` and `new_python_runtime_manifest`; each lists complete trees
with relative paths, sizes, SHA256 digests and symlink targets. The verifier
rejects changed bytes, added or missing files, changed aliases and writable runtime
mounts, then executes the supplied command in that same namespace. Bytecode caches
are excluded only when `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPYCACHEPREFIX` points
to an empty read-only directory. The startup verifier requires both, so existing
unpinned bytecode caches cannot be loaded.
Startup also verifies the pinned namespace wrapper, bubblewrap executable,
executing verifier, campaign controller and entrypoint hashes. A copied verifier
at a different path is rejected even when its bytes match the intended file.
The startup receipt supplements the per-attempt executable, library, source and
input checks. This verification runs outside measured fitting time.

Reports count objective changes that the controller identifies as numerically
unresolved, including accepted trials. Each such trial retains its actual and
predicted reduction, floor, damping history and gain ratio. Missing legacy flags
are unavailable rather than assumed resolved. Positive changes within the
numerical floor do not establish a resolved improvement; acceptance and final
undamped convergence diagnostics are reported separately.

Carrier-phase comparisons use the original observation coordinate:
`predicted_phase = input_m - residual_m`. The exporter captures `input_m` before
windup and ambiguity recentering. Legacy integer recentering shifts processed
observations and fitted ambiguities together, leaving the residual invariant.
The new full-float path therefore compares through the same original input and
residual. A direct comparison of `fitted_ambiguity_m` across these coordinate
choices would be misleading and is not used.

Online storage management preserves the accepted/current triangular factor and
the newest available factor as failure evidence. Only released `R.bin` files are
removed, after a streaming SHA256/size receipt is saved. All other diagnostics
remain. With `ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE=1`, the native process
losslessly compresses every completed generation's row ledger before releasing
its raw bytes. Gzip ledgers and receipts survive later-generation cleanup;
decompression must reproduce the original SHA256/byte count and pass CRC checks.
Python verifies native-produced gzip even when the original TSV is absent.
The earlier resource preflights used predecessor-row deletion with hash receipts,
so their final-ledger storage count is historical evidence, not the final policy.
Full-generation gzip storage must be counted before launch. A two-generation
24-hour native level-1 preflight retained all 1,458,623,998 original bytes in
56,989,663 compressed bytes, with independent SHA/CRC verification. Offline
streaming recompression of one exact 729,316,717-byte ledger measured 28,506,518
bytes at level 1 and 7,807,232 bytes at level 6. Level 6 cost an additional
0.816 seconds wall and 0.727 seconds CPU in that engineering comparison, which
included input decompression and ran alongside other engineering activity.
The selected final policy uses level 6 for its 72.6% storage reduction. Candidate
`51a9a4ac003aa51c` passed the native retention/arithmetic tests; an independent
check verified all 36 closed level-6 ledgers from its one-hour engineering replay
(68,361,224 original bytes, 5,014,946 compressed bytes). That replay failed
nuisance convergence, so its storage verification is separate from estimator
acceptance. The final frozen build must retain the validated policy.
Closed row-provenance TSV files are losslessly compressed with deterministic
gzip; the original is released only after decompression reproduces its exact
SHA256 and byte count. Receipts identify both forms. These online costs are part
of fitting time. Terminal compaction also preserves the accepted and newest
failure factors recorded by the online policy.

The new QR topology locally eliminates independent per-epoch VTEC jointly with
receiver clocks, retaining their conditional recovery information. This is an
algebraic elimination of the same weighted observation and Gaussian-prior rows;
global signal/TEC biases, float ambiguities and dynamic parameters remain in the
retained system. It must pass the independent MAP, covariance, objective and
rank gates under its own native build/topology identity before a final freeze.
Resource measurements from the earlier topology with globally retained VTEC are
engineering evidence for that topology. The subsequent local-VTEC preflight
measures its smaller factor and spool. Full-generation gzip integrity is now
verified separately; the numerical correctness gates still control final freeze.


## Long-running launch and final report

After preparation and the final freeze, use `scripts/run_numerics_campaign.py`
(or `python -m orbit_poc.numerics.campaign`) in the same verified runtime
namespace. It requires `--config` and `--startup-receipt`; the latter must be
the successful runtime verifier receipt for that exact configuration. For example,
inside the common namespace and with the frozen source on `PYTHONPATH`:

```text
<pinned-python> scripts/verify_numerics_runtime.py --config /frozen/config.json --receipt /runtime/startup.json -- <pinned-python> -m orbit_poc.numerics.campaign --config /frozen/config.json --startup-receipt /runtime/startup.json
```

The controller generates an inclusive report before the run and after completion,
failure or a catchable interruption. It invokes the existing serial `run` once;
`--max-attempts` is available only for an explicitly bounded partial invocation.
Each invocation retains its own exit/status receipt and immutable configuration,
startup verification and HTML/JSON report copies under `controller/`. The latest
report remains under `report/`.

SIGINT/SIGTERM unwind the existing worker-group cleanup before reporting. A signal
during final reporting is recorded while that report finishes. An uncatchable kill
can leave a running receipt; the next explicit invocation first refreshes the
inclusive report, then applies the unchanged checkpoint rules. Complete failures
are not retried, and an unfinished fit without a terminal checkpoint still requires
explicit recovery review. The controller never edits source, repairs checkpoints,
replaces cases, changes the freeze or starts a second run automatically. Report
failures receive their own diagnostics and a nonzero exit status.

Archive recovery verifies the complete published destination before removing any
remaining working copy. An interruption during that removal may leave a partial
backup; each remaining entry must match its prior path/byte/link proof before
cleanup resumes. Interrupted staging copies reuse only matching symlinks and
rebuild incomplete regular-file copies from the unchanged original.
