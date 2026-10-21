# Whole-fit nuisance-cache protocol

The protocol was frozen before launch. At **2026-10-19T08:20:20.790910+00:00**, the cache-enabled attempt was running and the cache-disabled attempt was pending. This packet contains immutable controls and a bounded process-status observation; it contains no numerical results.

The two attempts use the original 24-hour **500 km, quiet atmosphere, normal tracking, pulse** case that timed out in campaign09. Both use candidate `8b6986943d7836c4f4cb03278069893d3b797a5bcbd2a3f4ba763a1b27a6fcb2`, with cache order **1 → 0**. Inputs, initialization, pulse interval (1,200 s), pulse standard deviation (10⁻⁴ m/s), physical models, weights and correctness thresholds are preserved. Each full fit retains the two-hour limit, 8 GiB process-tree limit, one numerical thread, 32 accepted iterations and 96 trials.

The [actual freeze](protocol/freeze.json), [input preparation](protocol/preparation.json), [source inventory](protocol/source-inventory.json), [runtime inventory](protocol/runtime-closures01.json) and [actual Python runtime](protocol/python-runtime-actual01.json) identify the planned execution. Its SHA-256 is `cb4e4a339361002723cf56053bed27dd521f9f51f097f18b1be148126b78a7e4`. The [independent launch review](controls/wholefit-concrete-launch-independent-review01.json) predates launch. [Copy provenance](manifest.json) records every published file and its source hash.

The original diagnostic exporter `643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6` is retained. Both arms share the recorded local runtime; six system-library or loader files differ from the historical remote runtime. This experiment does not establish equivalence to that historical runtime. One attempt per arm cannot support a statistical speedup claim. A timeout remains a failure, and progress cannot authorize covariance or establish whole-fit convergence.

The [first input-transfer failure](protocol/capture-inputs01.execution.json) and [its error](protocol/capture-inputs01.stderr) are retained: Python 3.10 rejected the streaming tar `compresslevel` argument before reading input files. The corrected gzip-stream capture succeeded with the original hashes. The earlier controller test-fixture failures are also preserved alongside their corrected checks.

Bulky inputs, executables, transfer archives and every live fit output stay outside this packet. The frozen v4 campaign remains separate. Later results require their own attributed report; the running/pending status here is fixed to the timestamp above.
