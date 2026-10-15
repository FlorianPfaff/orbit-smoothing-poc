# Reproducing the v3.1 correctness recovery

This recovery records separately frozen correction candidates after the work in
[PR #3](https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/3).
Attempts04/05 validate candidate
`e7c93a97603cddcbef2f163257a34f48577c5516` using the same 758 frozen source files,
14 prescribed input pins,
physical models, priors, weights, hyperparameters and acceptance limits. Its
fresh GROOPS checkout starts at
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`.
The original 150-attempt benchmark retains its own executable and results;
correctness-recovery results cannot replace its attempts.

Attempt06 validates a separately frozen query/reference precision correction.
It failed the prescribed objective gates. The newer residual-precision
candidate is undergoing attempt08. This is an intermediate publication snapshot
as of October 15, 2026 at 10:51 UTC: both objective checks have failed. One original
replay passed and the second is still running; terminal cleanup and independent
audit remain pending. Attempt08's
terminal results and independent audit are not part of this snapshot.
V3.1 correctness remains open.

## Runtime and preserved evidence

Attempt03 was interrupted during its build by a host restart. Its unfinished
pipeline, partial build and previous failures remain intact. The interruption
record ties the old process identities to the previous boot and records the
absence of a completed executable and native tests. It does not infer the
restart cause or invent a cleanup or campaign-resume receipt.

Attempt04 completed 633 compilation/link targets on `gpuserver4090`
(`workstation1`), but the executable's startup check required `GLIBC_2.38`
while the host supplied glibc 2.35. The build manifest and native tests were
therefore not produced. That failed build and all its evidence are preserved.

Attempt05 changes the isolated runtime, using the matching loader and 14 glibc
libraries from the already pinned conda sysroot package
`sysroot_linux-64-2.39-hc4b9eeb_6`. Bubblewrap mounts these files read-only onto
their canonical `/lib/x86_64-linux-gnu/` targets. The loader binds to the real
`ld-linux-x86-64.so.2` file; the existing `/lib64/ld-linux-x86-64.so.2` symlink
resolves to it. Host libraries remain unchanged at 2.35. A failed probe that
tried binding directly onto the loader symlink is also retained.

Before launch, probes verified the exact scientific Python imports, compiler
execution, a small C++ compile/run, all 16 canonical library access paths and
the failed04 executable's `--help`. A separate probe exercised the unchanged
production wrapper with only its five writable paths redirected to staging.
These establish runtime compatibility and isolation; they are not scientific
acceptance results. Attempt05 builds afresh and reuses no04 object or binary.

## Frozen configuration and execution

The actual attempt root is
`/mnt/seagate10tb/orbit-v31-correctness-05-florianpfaff`. The filenames
`candidate04-*`, `validate_candidate_04.py` and
`with_correctness_namespace_04.py` name the unchanged reviewed control protocol.
The execution configuration explicitly selects attempt05 directories, including
`validation-05`; the filename suffix does not identify the executed attempt.

| Frozen item | SHA256 |
| --- | --- |
| 758-file source inventory | `fb9560e7ea98e8f561034f856e9a977e324da7852325ff73b14bc0ae1125fbb9` |
| `control/candidate04-execution.json` | `41e0a8363dc8cd4adedf92afef222ae19ab697e906716db64cc622e4dc91dc01` |
| `control/candidate04-pins.json` | `83db29944e658b74638b4e3955a959cb93ee207f915034bb463407e8069edcff` |
| `validate_candidate_04.py` | `8db719ce6ae487ed9cfefb57eb1397bbe7c6b19ba516caab5e0c19802fe6ad57` |
| `with_correctness_namespace_04.py` | `aa678b5f49241f3eb327d364556637ce7998fba423770b588dbec609bee97472` |
| `staging/abi-probe-03/runtime-overlay.json` | `75f3828bb226088e870c01523f9bd6b57f32fd095cb7ec7fc465a8ff08077fe7` |

The detached launch at 2026-10-15 06:16:37 UTC recorded this driver invocation:

```sh
RECOVERY05=/mnt/seagate10tb/orbit-v31-correctness-05-florianpfaff
/usr/bin/python3 "$RECOVERY05/control/validate_candidate_04.py" \
  --execution "$RECOVERY05/control/candidate04-execution.json" \
  --pins "$RECOVERY05/control/candidate04-pins.json" \
  --pins-sha256 83db29944e658b74638b4e3955a959cb93ee207f915034bb463407e8069edcff
```

This is the recorded command, not a command to repeat in the occupied attempt
directory. A new reproduction needs fresh source, native-source, build, binary,
output and temporary directories, a new host/boot admission, and a separately
frozen execution configuration. The detached launcher records PID, boot,
process start time and exact argv. The driver verifies source/input/runtime
hashes and supervises each owned PID namespace through cleanup.

Canonical read-only aliases preserve the absolute paths embedded in original
requests, XML and the scientific Python environment. Bulky observations,
auxiliary files, compiler/runtime trees, row spools and build intermediates stay
outside Git. The input and runtime inventories identify their required bytes;
the 14 prescribed pins include both distinct replay XML files and each replay's
variational, reference and density inputs. Recreating an alias with different
contents is not a valid reproduction.

The build uses four jobs on CPUs 24–27; validation runs serially on CPU24.
Affinity, a host-local validation lock and admission checks prevent competing
owned native/orbit work. This is not an administrative reservation of the
machine: unrelated GPU workloads and background host load existed. Runtime
comparisons must retain that limitation. The original v3 campaign on
`gpuserver6000` is separate, and this recovery records no campaign resume.

## Required results and interpretation

The unchanged sequence requires 106 native tests without failures or skips;
four measurement refinements (both synthetic methods, flight and eccentric
24-hour); both objective/full-prior checks; and both exact nuisance-failure
replays. Refinement retains the 1%-of-noise limit. Objective directional checks
retain the `1e-4` criterion, including the numerical-resolution allowance, at
two consecutive perturbation scales. Missing, failed or timed-out checks must
remain visible in the audit and report.

Strict nuisance convergence requires two fresh undamped corrections below
`1e-8 m`. An independently supported numerical-floor result is recorded as
limited progress and cannot authorize covariance or full release readiness.
Neither a process exit code nor a successful runtime probe resolves the
correctness issue without the complete gate results and independent audit.

The byte-identical executed controls and their fabricated tests are in
[`scripts/correctness_recovery`](../scripts/correctness_recovery/).
`source-manifest.json` identifies their hashes; its three historical source
fixtures support AST comparisons that check the preserved numerical rules.
Those control tests exercise interruption, identity, replay attribution and
failed-result reporting without invoking a scientific fit.

From the repository root, use a Python environment with pytest and NumPy:

```sh
TEST_OUTPUT=$(mktemp -d /tmp/orbit-recovery-tests.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/correctness_recovery \
  -q -p no:cacheprovider --basetemp "$TEST_OUTPUT/fixtures" \
  --junitxml "$TEST_OUTPUT/junit.xml"
```

The directory contains 237 control tests and 60 history-assembly tests,
validated separately. Most fixtures and all output in this command go to the
temporary directory. A few driver tests explicitly create small temporary
directories beside their test source and automatically remove them. The
recorded publication test run redirected those explicit temporary directories
to `/tmp` through an external runner, leaving the test source unchanged.

The history assembler preserves the two terminal compact bundles byte for
byte, including failed and missing results:

```sh
python scripts/correctness_recovery/assemble_correctness_history.py \
  --plan /absolute/path/history-plan.json --plan-sha256 PLAN_SHA256
```

The sealed plan binds the assembler, frozen source inventory, actual execution
configuration, run journal, postprocessing journal and compact publication
manifest for each execution attempt. It also binds the independent attempt04
infrastructure review. Its output must be a new directory outside every input
root. The resulting `attempt-04/` and `attempt-05/` directories retain their
original report bytes; the new index and manifest distinguish execution
identities from protocol filenames. Assembly cannot promote numerical gates,
authorize covariance or reclassify the frozen benchmark.

## Preserved attempt05 result

**Attempt05 status: failed; the correctness issue remains open.**
The [preserved HTML history](../validation/numerics-v3.1-correctness/recovery04-05/index.html)
contains both the attempt04 startup failure and the completed attempt05 results.
Attempt05 used source `e7c93a97603cddcbef2f163257a34f48577c5516` and native binary
SHA256 `81fc448f50d1e8640611cc6fd7dce172333f272e862fab82280c429a48d58252`.

| Prescribed check | Attempt05 result |
| --- | --- |
| Native tests | 106 passed; zero failures, errors or skips |
| Four propagation/measurement refinements | Both synthetic methods, flight window and eccentric 24-hour case passed |
| Pulse objective/full-prior check | Passed the directional criterion at consecutive scales 1 and 0.5 |
| Density objective/full-prior check | Failed at `point-017-direction-0.125-1`; no passing pair of consecutive scales |
| Original near03 nuisance-failure replay | Passed with strict nuisance convergence; maximum fresh update `2.99e-10 m` |
| Candidate1 point012 nuisance-failure replay | Passed only as independently audited numerical-floor-limited progress; fresh update `5.16e-6 m`, above the `1e-8 m` strict threshold |

The density check completed scales 1, 0.5 and 0.25 with combined directional
discrepancies approximately `6.19e-3`, `1.56e-3` and `4.08e-4`, respectively,
each above the unchanged `1e-4` criterion. Its nuisance profiling then failed
at the positive `h=0.125` point. That failure remains in the report rather than
being replaced with a subsequent investigation or easier case.

The independent terminal audit agrees with the failed outcome. The second
replay's numerical-floor classification does not establish strict convergence,
authorize covariance or certify release readiness. These engineering checks
make no orbit-accuracy or speed claim and do not complete or replace the
separate 150-attempt benchmark.

The history's 222 files (17,255,244 bytes) were copied byte for byte into the
publication checkout. Its manifest SHA256 is
`9f0d0a4ac8c83855bc327ce964d9f26a91b3339d6c7534bcc488b90f9e44e2ad`.
Additional [review and runtime provenance](../validation/numerics-v3.1-correctness/recovery04-05-provenance/manifest.json)
records control tests, independent reviews, the retained failed ABI probe and
successful isolated-runtime probes. Absolute private paths in those additional
receipts are tokenized; their original and published hashes are recorded.

## Attempt06 correction and failed validation

Attempt06 changes numerical evaluation of query interpolation and the synthetic
equinoctial reference. It preserves the physical model, original 14 input pins,
original 106 native tests, objective/refinement/replay scripts and acceptance
limits. The correction has eleven changed or added files, including two new
regression-test files; these add a separate 18-test stage without replacing any
original test. The runtime overlay and namespace wrapper remain unchanged from
attempt05. Source, native source, build, binary and output directories are new.

The validated source commit is
`163cc929f9e02a5c18da63c17a04724461ebcfb0`, with 764 files and inventory SHA256
`194b460ab90ed2eb3818af16324086f8cd0fe9aecd77308cd9ff45de23da660a`.
The publication branch applies the same eleven-file correction as commit
`3541f25101400178872ce514aafe3f82c9416b69`. These are distinct commit identities:
the [equivalence receipt](../validation/numerics-v3.1-correctness/recovery06-provenance/candidate06-publication-source-equivalence.json)
verifies the exact before/after file hashes, rather than asserting equality of
the entire publication and validation trees.

The execution root is
`/mnt/seagate10tb/orbit-v31-correctness-06-florianpfaff`. The frozen pins SHA256 is
`61b42ed6b71a2696e89782d59ae30eaf0e6c8355d3bbf24ed01cd24e3bb03776`.
The driver uses `validate_candidate_06.py` and `validation-06`; the unchanged
wrapper retains its `_04.py` filename. A detached finite postprocessor uses
the separate reporting Python and produces its audit, HTML report and compact
bundle after the exact driver process and owned workloads terminate.

The required suite closed on 2026-10-15 at 07:27:15 UTC, with verified cleanup.
The postprocessor completed at 07:27:24 UTC and reported scientific status
`failed`. The fresh native executable SHA256 is
`37c0d22c843d2a160e7537086a8440c5c79d550d71fc7c9172ca5994d6f30e2f`.
The [attempt06 HTML report](../validation/numerics-v3.1-correctness/recovery06/index.html)
retains every failed and missing check.

| Prescribed check | Attempt06 result |
| --- | --- |
| Original native tests | 106 passed; zero failures, errors or skips |
| Separate correction regressions | 18 passed; zero failures, errors or skips |
| Four propagation/measurement refinements | Both synthetic methods, flight window and eccentric 24-hour case passed |
| Density objective/full-prior check | Failed at `point-001-nonzero-full-prior`; no completed prior check or directional scale |
| Pulse objective/full-prior check | Full-pulse prior and scale 1 passed; failed at `point-008-direction-0.5--1-repeat`, leaving scale 0.5 incomplete |
| Original near03 nuisance-failure replay | Strict convergence; maximum fresh update `2.99e-10 m` |
| Candidate1 point012 nuisance-failure replay | Strict convergence; maximum fresh update `3.54e-10 m` |

The pulse scale-1 directional discrepancy plus numerical-resolution allowance
was `1.32e-6`, below the unchanged `1e-4` limit. One passing scale does not meet
the required consecutive-scale criterion. Neither objective gate passed, and
the [independent terminal audit](../validation/numerics-v3.1-correctness/recovery06-provenance/terminal06-independent-audit-01.json)
agrees with that failed outcome. The two original replays now both meet the
strict threshold; the earlier attempt05 floor-only classification remains in
its original report. This does not authorize covariance, certify v3.1 release
readiness or complete the separate 150-attempt numerical benchmark.

The compact attempt06 bundle was copied byte for byte: 99 files, 34,776,823
bytes, manifest SHA256
`84f7945d4101b87c1033be4cdb90b966b869ecf0eb418e67b583786cc2cb9b63`.
The [additional provenance manifest](../validation/numerics-v3.1-correctness/recovery06-provenance/manifest.json)
records transfer/copy integrity, launch identities, control reviews, numerical
source reviews and the independent terminal audit. The unchanged attempt04/05
history remains in its separate directory. Bulky source data, binaries and row
spools remain outside Git.

The byte-identical attempt06 controls and fabricated tests are in
[`scripts/correctness_recovery06`](../scripts/correctness_recovery06/), with their
own source manifest. All 262 fabricated control tests passed in both the author
and independent review snapshots. To run them from the repository root:

```sh
TEST_OUTPUT=$(mktemp -d /tmp/orbit-recovery06-tests.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/correctness_recovery06 \
  -q -p no:cacheprovider --basetemp "$TEST_OUTPUT/fixtures" \
  --junitxml "$TEST_OUTPUT/junit.xml"
```

Use a Python environment with pytest and NumPy. As with the earlier controls,
a few tests create automatically removed fixtures beside their test source;
the recorded test runs used independent `/tmp` source snapshots. Control-test
success verifies orchestration and reporting behavior, not scientific success.

## Separate exact attempt05 point017 diagnostic

After the required attempt06 suite and its postprocessor closed, a separately
sealed diagnostic replayed the exact attempt05 density failure at
`point-017-direction-0.125-1`. It used the corrected attempt06 executable and
the four original profile/variational/reference/density pins. It did not rerun,
replace or reclassify either prescribed objective gate.

The [supplemental evidence](../validation/numerics-v3.1-correctness/recovery06-supplemental-point017/manifest.json)
records strict nuisance convergence: two fresh corrections of
`2.5480153014779906e-10 m`, below `1e-8 m`; 56 ambiguity half-integer crossings
were exercised. The owned run completed in 45.52 seconds, with verified
cleanup. The separate independent audit verified the six search receipts,
unchanged observation support, exact input/native identities and fresh final
factor. A preceding launcher preflight rejected an incorrect expected runner
digest before creating a plan or starting a native job. That rejection is
preserved separately from the subsequently successful diagnostic.

The runner and its 45 fabricated lifecycle tests are published separately in
[`scripts/correctness_supplemental06`](../scripts/correctness_supplemental06/).
Both author and independent test runs passed all 45 tests. Use the same pytest
command above with that directory substituted to verify orchestration. Running
the native diagnostic additionally requires its exact terminal plan, input
pins and the pinned `/usr/bin/python3` control interpreter; it cannot be
launched against an unfinished required suite.

This supplemental success isolates progress on the old failure. The required
attempt06 density first-profile and pulse repeat failures remain unresolved.
Their failed statuses remain preserved through the subsequent diagnostic and
correction work; covariance and release readiness remain unestablished.

## Bounded arithmetic diagnosis after attempt06

The separate [diagnostic report](../validation/numerics-v3.1-correctness/recovery06-diagnostics/report.html)
preserves D01's compiler failure before an accepted diagnostic executable,
followed by D02's completed trace build. D02's trace-disabled and trace-enabled
fixed-orbit replays both failed as before. Their 104 exact numerical-equivalence
checks across eight generations passed. These checks establish that the
instrumentation preserved the measured calculations; they do not establish
nuisance convergence.

The independent Decimal analysis examined five selected observation rows. It
reproduced the native arithmetic and identified two individual-row reduction
sign reversals. This selected-row evidence does not establish a full-objective
descent direction, stationarity, covariance validity or orbit accuracy. The
complete bounded analysis, failed runs, input hashes, trace inventory and
independent reviews are preserved. The raw 12 MB trace and native row spools
remain outside Git.

The diagnostic package contains 183 files plus its manifest, with 7,023,811
bytes of published content. Its manifest SHA256 is
`fb6114260ad344b1600c67930750191325b120e232b47342cba10623ce60d5b7`.
Both independent publication reviews verified its attribution and limitations.

## Residual-precision candidate and closed attempt07

The [complete-residual precision correction](numerics-complete-residual-precision.md)
is frozen at commit
[`8e4d36f7c47d57acdb9fa30d15a6005189bbf221`](https://github.com/FlorianPfaff/orbit-smoothing-poc/commit/8e4d36f7c47d57acdb9fa30d15a6005189bbf221),
on branch `numerics-v3.1-correctness-04`. Its 771-file inventory SHA256 is
`774d6d777e1f5caf09b5599a8b469e421327f2e1f962eb75a5af17b0bc8bf8c2`.
The publication branch applies the exact eleven-file change as
`e37022bdd87913779319692246de6bcb34a002d8`; the two commits have distinct
identities. The attempt07 provenance includes the exact before/after file
equivalence receipt. The original 106-test suite, prescribed inputs, physical
models, priors, weights and numerical acceptance limits remain unchanged. A
separate correction stage now contains 40 regression tests, including the
earlier 18.

Attempt07 failed its first clone step with exit128 on October 15, 2026 at
09:21 UTC because its fresh execution root lacked `upstream.git`. No native
binary, native-test pass or scientific validation result was produced.
Owned cleanup was verified. Its independent terminal review confirms this
infrastructure classification.

The finite postprocessor preserved a failed audit and generated the original
summary and HTML. Its collector then failed because the 20,604,509-byte HTML
exceeded the unchanged 16 MiB receipt limit. That failed collector journal is
retained. The separate [bounded attempt07 report](../validation/numerics-v3.1-correctness/recovery07-08/attempt-07/index.html)
lists clone failure and all twelve unrun steps. It stores the complete original
audit, summary and HTML as compressed, path-tokenized copies, with original and
published hashes and sizes. This changes presentation only: it does not modify
the frozen collector, its limit, any original journal or any scientific gate.

The bounded attempt07 package contains 34 files plus its manifest, totaling
3,276,140 bytes. Its manifest SHA256 is
`88273c4015092238bbb7584b3505f322befb606584e86a04cf8439624b14c42f`.
The unchanged controls are in
[`scripts/correctness_recovery07`](../scripts/correctness_recovery07/), with a
source manifest binding all twenty files to 285 passing author and independent
fabricated tests. The separate
[`scripts/correctness_publication`](../scripts/correctness_publication/)
adapter passed 53 author and independent tests. Its initial attribution gaps,
review requesting changes and subsequent corrected review remain in provenance.

From the repository root, use a Python environment with pytest and NumPy:

```sh
TEST_OUTPUT=$(mktemp -d /tmp/orbit-recovery07-tests.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/correctness_recovery07 \
  -q -p no:cacheprovider --basetemp "$TEST_OUTPUT/fixtures" \
  --junitxml "$TEST_OUTPUT/junit.xml"
```

Run the presentation tests separately with `scripts/correctness_publication`
substituted. Those tests need pytest but no numerical runtime. The tests check
control or publication behavior and do not establish scientific acceptance.

## Closed attempt08: required suite failed

Attempt08 used the same frozen candidate source and all twenty byte-identical
candidate07 controls in a fresh execution root. Its `candidate07-*`,
`validation-07` and `postprocess-07-01` names identify the control version;
the execution root and launch identities distinguish attempt08 from attempt07.
An independently staged complete upstream mirror was checked inside the native
namespace before launch. This retry did not reuse a failed build or replace
the closed attempt07 record.

The suite ended on October 15, 2026 at 10:56 UTC with verified owned-process
cleanup. Independent terminal audit confirmed the failed scientific result:

| Required check | Actual result |
| --- | --- |
| Original native tests | 106 passed; zero failures, errors or skips |
| Separate correction regressions | 40 passed; zero failures, errors or skips |
| Four propagation/measurement refinements | All passed |
| Density full OU prior | Passed, 61 rows, nonzero cost 4.848917841373497 |
| Full pulse prior | Passed, 6 rows, cost 0.053929305673915545; exact residual agreement |
| Density objective | Failed point006, generation52, fresh update 19.460792563 nm |
| Pulse objective | Failed point003, generation80, fresh update 17.741946472 nm |
| First original nuisance replay | Strict convergence, fresh update 0.299056172 nm |
| Second original nuisance replay | Failed generation14, fresh update 32.511868781 nm |

Neither objective completed a directional-derivative scale. Both failed final
objective profiles rejected all seventeen trials, with no accepted numerical
floor qualification. The second original replay also failed; it has no accepted
final nuisance profile. These updates exceed the unchanged 10 nm nuisance
threshold. Passing prior checks, earlier accepted steps or small damped steps
do not establish convergence.

The native executable SHA256 is
`dba44217a63c655cafebee130ffb6f81ab23e3e72ad82d9ba68dd09784d60f6c`;
its build manifest SHA256 is
`8218ea268e5dd5f5adf11c26ff6d63c82505bc76bfe43d0fae9ff870be242bf7`.
The exact source remains commit `8e4d36f7c47d57acdb9fa30d15a6005189bbf221`.

The [attempt08 report](../validation/numerics-v3.1-correctness/recovery07-08/attempt-08/index.html)
contains every planned step, exact inputs, source/build/launch identities,
refinement and prior measurements, original replay attribution and the
independent terminal audit. Its 75-file manifest SHA256 is
`64ebdc5f7dbecf18990a879240827986f92868be828b79a357f8611b892dbef1`.
The original collector again rejected the oversized generated HTML. Its failed
journal is preserved; the separately reviewed presentation stores the full
original audit, summary and HTML as compressed copies with original and
transformed hashes. No frozen control or reporting limit was changed.

The [objective failure appendix](../validation/numerics-v3.1-correctness/recovery07-08/attempt-08-failure-details/index.html)
retains all 52 density and 80 pulse generations, including complete compact
profile, factor, search and available retirement receipts. Its 802-file
manifest is `f5afa0cdd56b96be232ee041044d20eb896d19350c6fef5b2e7c29cc0715b596`.
The last generation has no superseding-factor retirement receipt; that absence
is explicit. Raw row spools and binary factors remain external, with hashes.
The [second replay appendix](../validation/numerics-v3.1-correctness/recovery07-08/attempt-08-replay-failure/index.html)
separately preserves all fourteen generations of the failed original replay.

A [static density-point diagnostic](../validation/numerics-v3.1-correctness/recovery07-08/attempt-08-density-point006-plot/late-iterations.svg)
shows only late generations4–52, with the unchanged strict threshold and
recorded accepted step sizes. The accompanying CSV and input manifest bind all
49 plotted JSON records. The full history remains the primary evidence; this
plot makes no new numerical acceptance or trajectory-accuracy claim.

Correctness remains unresolved. These failed gates cannot authorize covariance
or establish full release readiness. Further arithmetic diagnosis is separate
from this closed attempt. The original v3 campaign and frozen 150-attempt
benchmark retain their own executables, inputs and results; benchmark completion
remains an additional deliverable.
