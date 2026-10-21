# Candidate 1: preserved failed correctness validation

This candidate did **not** resolve the v3.1 objective correctness failure. Its source commit is `4a8014a92afbfac944d22c529554bfa41f14c559`; the native executable SHA256 is `fcfbc385917227084d11e3330c1e6da4d0d6df82f0e683ead2276ce70e16d2b8`.

The native suite passed all 88 tests with no skips. Both one-hour synthetic refinements, the April 24 flight refinement and the retained eccentric 24-hour refinement passed their unchanged limits. The pulse objective passed at consecutive step sizes 1 and 0.5.

The density objective failed at the negative repeat for step size 0.25 because the nuisance solve rejected inconsistent symmetric curvature. The exact earlier fixed-orbit nuisance replay also failed. These failures remain failures; a numerical-floor profile does not establish strict convergence or accepted covariance.

Open [the HTML report](index.html) for every reported outcome and the previous failure. [The manifest](manifest.json) records original and published hashes, missing or invalid evidence, and audit coverage. Absolute local paths were tokenized; bulky data, row spools and raw logs remain outside Git. The README and supplementary provenance below are separate from the collector manifest.

The earlier validation attempt failed in pytest file-descriptor capture before running tests; its successful build and infrastructure failure are both retained. The retry changed capture handling only. The original acceptance limits, weights, priors, hyperparameters and physical input state were unchanged.

This is bounded numerical engineering evidence. It does not establish scientific accuracy, a complete flight Jacobian, completion of the 150-attempt benchmark, or release readiness. The frozen benchmark uses its original executable and remains separate.
