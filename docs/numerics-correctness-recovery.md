# Reproducing the v3.1 correctness recovery

This recovery validates candidate
`e7c93a97603cddcbef2f163257a34f48577c5516` after the work in
[PR #3](https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/3).
Attempt05 uses the same 758 frozen source files, 14 prescribed input pins,
physical models, priors, weights, hyperparameters and acceptance limits. Its
fresh GROOPS checkout starts at
`7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee`.
The original 150-attempt benchmark retains its own executable and results;
correctness-recovery results cannot replace its attempts.

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

**Actual result status: failed; the correctness issue remains open.**
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
