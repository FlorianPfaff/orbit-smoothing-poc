Candidate07 density04 timeout — separate additive evidence packet

Suggested PR9 folder:
 validation/v4-fit-reliability/candidate07-density04-timeout
Existing packet02 remains unchanged at commit:
 a36da221f2bebd9dc223c1e8512925ab6e5fc532
 https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9
 https://github.com/FlorianPfaff/orbit-smoothing-poc/tree/a36da221f2bebd9dc223c1e8512925ab6e5fc532/validation/v4-fit-reliability/candidate07-sequence03

Outcome: all eleven previously passed correctness stages and the pulse cold03
producer strict full-fit pass remain preserved. Original density cold03 was
interrupted by the earlier boot change. Fresh original-GNSS density04 timed out
under the unchanged7200-second supervised budget. It recorded22 accepted
iterations in30 completed/logged trial outcomes; trial31 started native nuisance
estimation and remained incomplete. It has no strict full-fit result, accepted
density covariance or convergence confirmation. Its stopped history still says
running; actual supervisor/aggregate/detached terminals establish the timeout.

Timing must retain its scope:7200.168923458999 seconds is the supervised density
stage, including its own initialization and fitting;9841.040617729 seconds is
the detached caller including setup and closing identity verification. Peak
supervised process-tree RSS was386945024 bytes under an8GiB limit. There were
seven SIGTERM cleanup records targeting two distinct bwrap identities, with
verified kernel_ECHILD/empty-tree cleanup and no hard kill. No claim of
signal-free cleanup, uncontended timing, solver-only duration or speedup.

This is a one-hour synthetic leo500/quiet/normal engineering case, seed300000,
April24 filename convention, with original GNSS-only initialization. It is not
flight evidence or the frozen scientific comparison. Four saved mathematical
audits (scientific,selected,rank,export) are pending at this packet snapshot.
Their separately running collector/control qualification is not those audits.
The pulse tangent proposal is distinct stored-linearization diagnostic work,
not another full fit or density recovery, and its results are not imported here.

The fully independent terminal confirmation5d37... and scoped outcome review
4fd3... are copied byte-exact. The latter author also authored recoverycontrols04
and explicitly does not claim a fresh independent source review. The separate
PID-attribution addendum and raw worker observation clarify the distinct known
identity sets without rewriting either original review. Historical resource-
control deviation remains disclosed: earlier local PDF extraction/rendering
outside the admitted tree had unmeasured timing/numerical impact; no overlap
with this later fit, harmlessness or failure causation is inferred.

Assembly uses only small shell/jq operations and byte copies. No Python imports,
tests, native work, numerical reruns, browser rendering, Git writes or remote
operations were performed by this packet assembly. Original inputs/outputs,
failures and frozen protocols are unchanged. Exact copied-source and target
hashes/sizes are in inputs-manifest.json. The full8.4MiB frozen plan and native
binary are external exact pins, not silently omitted or claimed copied. Bulky
raw datasets, trajectory intermediates and row spools remain outside Git.

All packet files except top-level SHA256SUMS are individually hashed there.
assembly-source contains the actual assembler, static HTML and report source,
including exact input pins. The assembler refuses an existing output directory;
it must not be run into this completed packet. This packet awaits independent
content review before any publication. Publication adds a new folder only; it
must not replace packet02, old failed attempts or frozen campaign results.

No strict density covariance, scientific superiority, accuracy improvement,
release readiness, automatic rerun or modified tolerance is authorized here.
