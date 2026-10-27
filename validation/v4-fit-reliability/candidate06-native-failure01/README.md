# Candidate06 native106 failure — preserved outcome and diagnosis

The completed native106 stage **failed: 102 passed, 4 failed, no errors or skips**. The original failure logs and all four fixture receipts are included unchanged. This archive does not reclassify that gate or authorize cold fits, covariance or release.

All four assertions expected 17 ordinary nuisance-search trials and observed zero. The new validation controls set `ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY=1`; these unchanged original fixtures intentionally invalidate the zero-update replay, so the existing opt-in branch rejects them before ordinary trials. Historical local and remote executions of the same 106 tests passed with the same native binary and relevant test source, with this option unset (default 0). The separately archived 37-test suite explicitly verifies the 0-versus-17 behavior for default, 0 and 1. Full runtime identity across historical runs is not claimed.

Two read-only audits support this diagnosis. A separate controls repair is proposed: run the unchanged original106 compatibility suite with explicit flag 0, add the unchanged 37 option tests as a required separate gate, and preserve production flag 1. No source, assertion, numerical threshold, frozen benchmark or current run was changed by this publication work. No fresh native experiment is claimed here.

This is a static archive of one completed stage. Remaining correctness stages are not certified by this packet; their own terminal receipts determine outcomes. The current failed aggregate must not open the cold-fit gate. The earlier candidate06 proposal remains immutable and pending as dated.

The failed stage exited with code 1, verified owned-process cleanup, about 855.7 seconds supervised wall time and 401,186,816 bytes peak process-tree RSS. It was not recorded as a timeout or memory-limit failure. The scientific command took about 136.6 seconds; controller identity checks account for the remaining stage time.

Evidence:

- `report.json`: bounded claims, identity pins and status.
- `evidence/current/`: original JUnit, logs, supervisor/strict receipts, frozen plan, four fixture outputs and preserved parent files.
- `evidence/history-audit/` and `evidence/independent-audit/`: both diagnoses; the earlier auditor-only failed assumption is retained.
- `evidence/prior/`: both prior106 JUnit files, explicit37 JUnit, remote354 audit and attribution/environment records. Publication14 covered eight other checks; it did not rerun native106.
- `evidence/source/` and `evidence/controls/`: unchanged source and control bytes supporting the diagnosis. The installed native header includes existing instrumentation, so only its flag parser and search body are asserted identical to the overlay.
- `provenance.json`: exact source locations and SHA-256 for every copied original.
- `external-artifacts.json`: external binary, inventory and larger historical receipt pins. Bulk data and row spools are not included.

Portable verification (Python standard library only; executes no archived code):

```text
python3 -s -B verify_packet.py --packet .
python3 -s -B verify_packet.py --packet . --verify-originals
```

The second command additionally requires the original local files. `artifact-manifest.json` pins every packet file except itself. Its externally recorded SHA-256 is the trust anchor. Passing publication verification confirms the archived evidence and claims are internally consistent; it does not convert failed scientific checks to passes.

Publication target: [existing draft PR #9](https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9). No push or PR mutation was performed by this packager.
