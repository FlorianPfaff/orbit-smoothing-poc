Source03: narrow reader correction for preserved verified_row_compression_v1 evidence.
SOURCE ONLY: no tests, imports, gzip decompression or numerical audit executed by the author.

The actual source02 audit preserved candidate06's density failure but was unable to
reach the passed pulse selected audit because nested_pins demanded removed raw TSVs
from the two replay receipts. Their retained gzip archives are not missing data.

Only exact v1 receipt objects receive special handling. The new reader requires the
explicit compressed manifest pin, validates its exact bytes/hash, streams the gzip
through EOF/CRC within declared and absolute resource bounds, and checks reconstructed
raw bytes/hash without restoring the raw file. Original raw attribution is exported
separately, never added as a falsely read physical file. If raw exists it must also
match. Ordinary missing pins remain pending. Unknown fields/policies, changed hashes,
size/CRC errors and conflicting attribution remain failures. No correctness,
optimizer, covariance, rank or physical threshold changes.

Eleven new temporary-byte fixture tests cover successful missing-raw reconstruction,
existing-raw mismatch, ordinary missing pins, missing gzip, archive hash and manifest
mismatch, raw hash/size/expansion mismatch, CRC/truncation, receipt fields, unknown
policy, resource bounds, repeated receipt and conflicting attribution. All prior
source02 tests and frozen fixtures remain, apart from the test module name.

Use the separately pinned candidate06-terminal-input-manifests02/selected-inputs.json.
It retains all 398 original pins and adds 14 actual replay archive pins. The two
receipts contain 14 archive entries in total; none was already explicitly pinned.
This count corrects the earlier informal 7+8 estimate; actual receipts own identity.

Parent owns independent source review, serial test qualification and execution.
Source02 and its actual unsuccessful selected audit remain unchanged.
