# Accepted-point nuisance warm starts

This optional candidate reuses nuisance parameter values only as a numerical
starting point for an LM trial. It changes no observations, weights, priors,
physical forces, convergence thresholds or covariance rules. It remains off by
default and makes no speedup or full-fit completion claim. The preceding
[cache-only full-fit experiment](../validation/nuisance-performance/wholefit01-results/index.html)
ended in two timeouts; those attempts and the frozen campaign remain unchanged.

The [candidate06 experiment](../validation/nuisance-warm-starts/candidate06-profiles03/index.html)
passed all 27 native fixed-trajectory profiles and all 15 comparisons, including
an independent replay of every comparison. The unchanged 106 native tests and
51 correction regressions also passed without failures or skips. This establishes
bounded import and nuisance-fitting agreement; the main perturbed-target fits
used the same iteration counts as their cold counterparts. No full-fit warm
experiment, general speedup or release readiness is established.

The first [real-profile validation](../validation/nuisance-warm-starts/candidate03-profiles01/index.html)
failed: three disabled cold profiles completed, 15 enabled cold-export profiles
failed their exact refresh checks, and nine dependent warm profiles were blocked.
The independent audit accepts the failure attribution only. That earlier
candidate was not validated for use; its failures remain preserved.
The later [launch audit](../validation/nuisance-warm-starts/candidate03-launch-limitation/index.html)
also found that the isolated launcher omitted prelaunch QR controls required for
the production datum path. The original failures remain recorded; they do not
establish behavior under the production backend's initialization.

The corrected-launch [candidate05 experiment](../validation/nuisance-warm-starts/candidate05-profiles02/index.html)
completed all 27 planned attempts: 21 strict profiles completed and six
perturbed-target imports rejected their cold-origin identity check. Independent
replay accepted nine comparisons (six export-inertness and three same-trajectory
warm comparisons) and rejected the six perturbed-target comparisons. No whole-fit
experiment or production use is admitted. Same-trajectory iteration counts were
6 to 6 for pulses, 6 to 6 for density, and 10 to 8 for the dedicated prior fixture;
these single attempts do not establish a general speedup.

Candidate05 canonicalizes only exact signed zero in encoded numeric identities.
The isolated launcher now supplies the production QR settings before native
parameter initialization and records the actual launch and datum evidence. The
native test suites passed all 106 tests and 51 correction regressions. The prior
fixture's original aggregate false status is preserved, alongside an independent
schema-aware reconciliation of its successful native execution; it is not a
replacement run or a relaxed scientific gate.

Candidate06 separates receiver-clock starting guesses from statistical prior
anchors. The native chart carries the versioned policy
`receiver-clock-starting-guess-excluded-v2`; only explicitly typed starting clocks
are excluded from cross-point cold-origin equality. Actual clock prior anchors,
non-clock baselines, support, weights and gauges remain exact. Snapshot values
and post-import refresh checks remain exact, and old-policy snapshots reject.
This uses no rounding tolerance. The measured candidate05 starting-clock
mismatches ranged from one to five ULPs; the numerical source operation was not
identified. All 128 focused candidate06 tests passed independently.

The candidate06 target comparisons retained these iteration counts:

| Profile | Cold target | Independent cold repeat | Full warm target | Clock-only warm target |
|---|---:|---:|---:|---:|
| Pulses | 7 | 7 | 7 | 7 |
| Density | 6 | 6 | 6 | 6 |
| Nonzero-prior fixture | 9 | 9 | 9 | 9 |

The same-trajectory prior fixture took 10, 8 and 8 iterations for cold, cold
repeat and warm respectively, so its apparent improvement over the first cold
run was also present in the cold repeat. These are single measurements in a
bounded protocol, not independent performance trials. Ionosphere initialization
remains cold. No additional whole-fit speed experiment was launched from these
results. Earlier source, binaries, failures and frozen campaigns remain intact.

A separately controlled worker enables the candidate with
`ORBIT_POC_NUISANCE_WARM_STARTS=1`. The default enabled mode is
`receiver_clock_signal_float_v1`, which transfers receiver clocks, signal-bias
values and float ambiguities. `ORBIT_POC_NUISANCE_WARM_MODE=receiver_clock_v1`
selects clocks alone. Existing public configuration schemas are unchanged;
workers that sanitize numerical environment overrides still do so. An ordinary
legacy run does not acquire warm-start behavior.

Ionosphere values remain at the target's cold initialization. No ionosphere
state, old QR factor, covariance, prior anchor, force-history state or
interpolation cache is carried in the warm snapshot. The target initializes its
own chart, preprocessing and gauge choices before the native importer validates
and assigns any permitted values. Unsupported gauge/chart or cold-origin changes
fail explicitly; they do not produce an unrecorded fallback.

## Accepted-state lifecycle

Every evaluation starts in a fresh native process after complete chronological
physical propagation. Enabled evaluations can export a candidate seed after
strict nuisance convergence and a fresh, undamped, full-rank linearization.
Export without an input seed is still a cold nuisance evaluation. It only writes
an inspectable snapshot after the existing profiling work.

The Python adapter imports a seed only for an exact `trial-NNN` label, with a
positive three-digit trial number, and only when both `tighter` and `covariance`
are false. Initial, repeat, closure-refinement, repeat-floor, refine-floor,
confirmation and final-covariance evaluations receive no seed. The actual
objective-floor measurements and final covariance gate therefore remain cold.

A candidate export cannot become the donor during evaluation. Only the existing
optimizer's `accept(point)` hook can install it, after independent rank
certification and successful retention maintenance. Rejected candidates,
post-native graph/support failures, failed profiling and failed acceptance leave
the existing donor untouched. Accepting a floor-limited point clears the donor;
that point cannot supply a warm seed or authorize covariance. A later eligible
strict acceptance can establish a new donor.

The immutable context binds the scientific job settings, source identity,
actual native binary bytes and pinned base-input contents. It excludes changing
physical trial values and output directories. Source-point support and physical
state identities are recorded separately. The adapter checks the scientific
job/preparation description and base-file identities before capture, acceptance
and import. Seed and companion files must be regular files without symlinks;
their SHA-256 digests, inode/device identities, size and timestamps must remain
unchanged. Both files are rechecked at acceptance and import. An altered,
missing, stale or mismatched seed stops the operation.

A separate [composed controller test](../validation/nuisance-warm-starts/candidate06-controller/index.html)
exercises the real optimizer and Python backend through acceptance, rejection,
objective-floor checks, confirmation and final covariance. All seven cases
passed independent replay and recorded 173 mocked native-call environments.
Native outputs and physical closure are synthetic in these cases, so this adds
Python control-flow evidence only. The first fixture-serialization failures are
preserved alongside the corrected fixture and successful replay. It does not
establish native whole-fit convergence, covariance or performance.

## Native controls and evidence

The adapter owns these native environment fields:

- `ORBIT_POC_NUISANCE_WARM_STARTS`: `0` or `1`.
- `ORBIT_POC_NUISANCE_WARM_MODE`: one of the two explicit modes above.
- `ORBIT_POC_NUISANCE_WARM_OUTPUT`: fresh per-point binary output path.
- `ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256`: immutable scientific context.
- `ORBIT_POC_NUISANCE_WARM_INPUT`: optional accepted seed path.
- `ORBIT_POC_NUISANCE_WARM_INPUT_SHA256`: required when an input is supplied.

Inherited input, output, mode and context fields cannot select a donor behind the
optimizer's back. The serial worker temporarily removes all inherited
`ORBIT_POC_NUISANCE_WARM*` fields around each native invocation and supplies only
its own controlled profile fields. It restores the parent environment even on
failure. Propagation, proposal evaluation and the separate dense covariance
exporter receive none of those inherited controls. This boundary is designed for
the existing serial worker, not concurrent native calls sharing process-global
environment state.

Each point writes `nuisance-warm-state.bin.json` using schema
`orbit-poc-native-nuisance-warm-state-v1`. It records the mode, context, native
chart and cold-origin hashes, source generation, imported seed identity,
eligibility, coordinate count and target ionosphere/prior-anchor invariants.
Eligible strict results also write `nuisance-warm-state.bin`. Ineligible
floor-limited results write a companion with no binary payload. Physical-point
metadata records the candidate export and import identity; optimizer decisions
remain the authority for acceptance.

## Validation boundary

The focused Python tests exercise accepted-only promotion, rejected-candidate
rollback, floor-limited revocation, protected cold labels, tampering, missing and
symlinked files, scientific-context changes, rank/retention/graph failures and
inherited-environment suppression. These offline fixtures do not establish
native import/export correctness or faster full-orbit estimation. The candidate06
native profiles separately establish import/export agreement on their fixed
trajectories, including objective and diagnostic covariance checks. A separately
frozen native full-fit experiment remains necessary to establish complete
optimizer integration, orbital covariance or whole-fit performance. No
correctness threshold is relaxed for this candidate.

## Isolated validation harness

`scripts/run_nuisance_warm_profiles.py` prepares and executes a separate,
immutable experiment from the preserved one-hour GNSS profile preparation and
a verified candidate build record. It does not operate on a benchmark campaign.
The preparation supplies source and perturbed-target trajectories, each with
an independently closed cold repeat, for pulses and log density. A third
fixture attempts to activate the existing code/TEC zero-mean priors solely to
check nonzero full-coordinate bookkeeping. In the first experiment, changing
their constraint standard deviations created no code/TEC constraint rows. The
checker rejected this unexercised requirement; that failed fixture is retained.

The 27 planned attempts cover disabled collection, cold export in both modes,
same-state full imports, and perturbed-target full and clock-only imports.
Each native fit uses one CPU, one numerical thread, a 900-second limit and an
8 GiB process-tree limit. Missing donors block their dependents. Existing
attempts are never overwritten or automatically resumed.

```text
python scripts/run_nuisance_warm_profiles.py prepare \
  --preparation /absolute/path/preparation.json \
  --build-record /absolute/path/candidate-build-result.json \
  --output /absolute/path/new-experiment
python scripts/run_nuisance_warm_profiles.py run \
  --freeze /absolute/path/new-experiment/freeze.json
python scripts/check_nuisance_warm_profiles.py COLD WARM COLD_REPEAT \
  --output /absolute/path/new-comparison.json
```

The checker binds results to the frozen inputs, executable, source, runtime,
execution controls and donor. Export-only collection must leave scientific
artifacts unchanged. Ordinary comparisons require strict nuisance convergence,
fresh undamped full rank, matching observation support and weights, objectives
within the target's independently measured cold floor, code/phase prediction
differences below 1% of their assumed noise, and diagnostic marginal-covariance
agreement below the existing relative tolerance of `1e-8`.

These profiles hold the physical trajectory fixed. Their covariance blocks are
diagnostic linearization outputs, not accepted orbital covariance. They do not
establish whole-fit convergence, a speedup, or release readiness. Full nonlinear
validation must retain the cold initialization, repeated objective, refinement,
confirmation and final covariance checks described above.
