# Candidate06: reject the evidenced failed density trial

This candidate is copied from corrected candidate04. Candidate05 is unrelated and is not inherited. Only `source/src/orbit_poc/numerics/backend.py` and `optimizer.py` change existing production code. Native sources, the candidate04 executable, statistical models, priors, weights, parameter scaling, numerical thresholds and iteration/time/resource limits are unchanged.

The one-hour cold density fit produced a valid scaled-LM proposal whose large log-density correction made its generated reference trajectory unsuitable for the native mean equinoctial fit. Independent augmented least-squares reconstruction verifies the step and OU rows. An exact isolated native replay found the first reference-fit update makes a negative semi-major axis and eccentricity 1.5387796; the second makes all six fitted elements nonfinite. The unchanged precise-reference guard then throws the original error.

The Python adapter records that exact known propagation failure with a preceding finite generated closure and conservative nonelliptic-state evidence. A dedicated exception can be rejected only in the optimizer candidate-evaluation block. The optimizer preserves its accepted state/factor and applies its original damping increase. Initial, repeat, refinement, confirmation and final-covariance failures remain fatal. Unknown native failures, bad inputs, crashes, timeouts and resource failures remain fatal. Density is not clipped.

## Evidence and tests

- `parent-copy.json`: all 484 original source files verified and copied exactly before edits.
- `source-snapshot.json`: frozen complete 492-file candidate inventory and change list.
- `candidate06-python-domain.patch`: production/test/documentation text changes; archived binary fixture is inventoried separately.
- `evidence/reference-domain-analysis01.json`: archive-only trajectory evidence.
- `evidence/reference-domain-analysis02.json`: exact native replay findings, superseding analysis01's unresolved element attribution.
- `evidence/native-reference-probe01/`: original loop, instrumentation, original-object/dependency hashes, exact binary input, trace and owned-supervision receipts. One isolated diagnostic, 95.95 seconds including build/hash checks, about 203 MiB peak process-tree RSS, CPU4 and one thread. This diagnostic is not the production executable or a full fit.
- `tests/unit01/`: preserved initial development failure (66 passed; one new fixture omitted required time globals). Its exact source version and complete logs remain.
- `tests/unit02/`: 67 focused Python tests passed with no failures, errors or skips after a fixture-only correction. Existing optimizer/backend tests included.
- External independent proposal analysis: `/mnt/d/orbit-v41-density-review06/proposal-audit01.json`.
- External independent exact replay review: `/mnt/d/orbit-v41-density-review06/reference-replay-review01.json`.

## Required next validation

No production native rebuild is required: use candidate04 native SHA `28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d`, recording candidate06's distinct Python source snapshot and runtime identity. Verify these identities before any new run.

The parent must independently review this source and focused suite, prepare separate controls/outputs, run the complete prescribed correctness suite unchanged (including native tests, four refinements, both objective/prior checks and both original nuisance replays), and then rerun both exact one-hour cold fits from their original GNSS-only initialization. Keep all original input identities, priors, masks, weights, budgets and strict final covariance checks. No warm-state donor, physical-state override or frozen benchmark substitution is authorized by this candidate. A new failure must remain a failure.

The candidate has not passed those new native gates or either full-fit rerun. Neither these focused tests nor the small diagnostic establish release readiness, accuracy improvements or covariance validity.
