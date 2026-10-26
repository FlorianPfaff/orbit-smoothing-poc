Candidate07 correction archive (source-only publication material)

This archive preserves exact code and measured fixtures. It does not replace
repository production files, change defaults, or assert a completed candidate07
fit. Historical source README/status records retain their original source-only
wording; actual later results belong exclusively to the separately audited packet.

The candidate06 and07 source ledgers were checked against their actual source
files during this preparation. Their snapshot inventory comparison identifies
exactly two modified existing files and eight added files, with no removals.
All changed/added07 files are copied under candidate07/; the two06 bases are
under candidate06-base/. delta.json records both hashes and sizes. The portable
modified-existing-files.patch covers the two existing files only. Added files,
including the exact compressed archived orbit fixture, are supplied as complete
bytes; the preserved original full patch retains its original absolute labels.
The complete500-file07 and492-file06 snapshot inventories retain attribution.
This is not a standalone full repository and does not claim an apply operation
or test has been run during publication preparation.

source-snapshot.json byte SHA4b997bc... and canonical source identityb49cd393...
are different objects. The latter is SHA256 of compact sorted-key JSON for the
ordered snapshot.files array, exactly as cold-controls03 source_identity().
It is not the file SHA and not comparison.protocol.source_snapshot().

The only estimator change is a new typed numerical-trial-closure rejection for
an evidenced normal exit from the pinned wide tangent physical-correction
solver. It preserves the exact2e-12 residual limit,120iterations and native
binary28c725...; unknown failures remain fatal. Rejection is caught only around
trial evaluation; initialization, repetition, confirmation and covariance
failures remain fatal. Failed trial evidence is recorded and accepted state is
not installed from the failure. Native physics/statistics/weights/limits are
unchanged. Correctness, full cold fits and independent terminal audits are
separate evidence and must not be inferred from this archive.
