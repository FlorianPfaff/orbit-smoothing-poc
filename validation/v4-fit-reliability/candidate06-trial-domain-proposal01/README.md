# Candidate06 proposal: reject the evidenced invalid density trial

This is a static, pre-validation source and evidence proposal for [PR #9](https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9), following publication commit `d3d82ed450b43901f9b749f5c4086a6e69211b24`. The published candidate04 pulse pass and density failure remain unchanged.

**All new candidate06 native correctness checks and both original-initialization cold fits are pending in this packet. It grants no launch, covariance or release authority.** Later operational evidence belongs in a separate append-only publication.

## Change and measured cause

The archived density proposal agrees with an independent augmented least-squares reconstruction to about 1e-12 in native coordinates; its 61 OU prior rows were retained. The exact isolated native reference-fit replay leaves the elliptic domain at its first update (negative semi-major axis, eccentricity 1.5387796) and produces nonfinite fitted elements at its second update. That explains the unchanged guard failure; it is not a successful orbit fit.

Candidate06 changes only two existing production Python files, `backend.py` and `optimizer.py`. The adapter classifies the exact evidenced synthetic reference propagation failure only with the required preceding finite closure and nonelliptic-state evidence. The optimizer can reject that typed exception only while evaluating a trial, preserve its accepted state/factor and use the original damping increase. Initial, confirmation, refinement and final-covariance failures, unknown native errors, crashes and resource failures remain fatal. No density clipping is introduced.

The exact production files, parent versions, text patch, added regression test, small archived fixture and documentation are under `candidate/`. Native binary SHA is `28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d`; candidate06 Python source snapshot SHA is `24c41840ad687aef76111e213b027c8ff613463313ccd7fb8fbf759e253db739`. The full source inventory is included, but the 492-file source tree, binary, runtime inventories, observational datasets and row spools are not copied.

## What the evidence establishes

The focused Python suite passed 67/67 after a fixture-only correction; its earlier 66/67 result and exact failed test source are preserved. Independent source review approves this minimal correction for the prescribed validation, not as completed validation. Final pure correctness controls passed 165/165, cold controls 50/50, and the sequence driver 63/63. These are control/fixture tests, not the 106 native tests, 51 correction regressions, four refinements, two objective/prior checks or two nuisance replays.

Earlier sequence tests exposed four failures plus one error and remain included. The failed first cold-control review and corrected reviewer predicates are retained. Every listed attempt remains explicit in `summary.json` and the HTML report. The isolated native replay is a completed diagnostic with its original supervisor/result, not a new native workload launched while assembling this packet.

## Verification and boundaries

Run `python3 -B verify_packet.py --packet /path/to/packet` using only the standard library. Add `--verify-originals` on the original host to compare copied evidence with its original paths. Output is JSON on stdout; redirect it outside the immutable packet. The manifest inventories every packet file except itself, verifies exact copies, patch reconstruction, changed-source pins, test counts, reviews, failure inclusion and report links. `external-pins.json` identifies omitted references; portable verification does not claim to verify those external files.

Historical delivery/review fields are preserved verbatim, even where a later source/control review supersedes an earlier pending or rejected review. The report does not treat file presence or an approval outside its stated scope as numerical success. Physical models, priors, weights, hyperparameters, budgets, correctness thresholds, original cold inputs and all frozen benchmarks remain unchanged.
