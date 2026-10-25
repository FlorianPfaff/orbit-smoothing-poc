# Next full-fit regressions after recovery14

Start with **two existing one-hour synthetic cold full fits**, one pulse and one density, using the corrected candidate04 executable (`28c725765201e470…`). The exact archived requests and hashes are in [plan.json](plan.json). This is a plan only; no new fit was launched and no execution manifest is frozen.

The eight-check result establishes local propagation, objective/prior and nuisance-replay correctness. It does not establish that the outer orbit optimizer finishes. The next useful evidence is a complete initial nuisance solve, physical optimization and fresh undamped confirmation.

1. Run both one-hour engineering cases from their original retained-observation GNSS-only bootstrap, with no saved physical state from `point-029-confirmation` and no nuisance donor. Preserve their existing masks and hyperparameters. The density case is tau = 7,200 s, sigma = 0.3; do not replace it with the long-case density settings.
2. Qualify candidate05 separately before attributing run14's success to it. Then compare its conditional-design OFF/ON modes on these same two full fits (four additional attempts). Require complete strict endpoints and final independent cold nuisance checks; retain cold controls if warm starts are subsequently integrated.
3. Return to the exact **72-hour quiet/normal 500 km pulse** and **48-hour quiet/normal 500 km density** cases after a versioned candidate addresses the measured cold-nuisance bottleneck and completes the exact fixed-point solve strictly. These are the eventual long-case regression targets, not immediate identical reruns.

Both long whole fits already timed out using the same candidate04 executable validated in run14. Candidate05's four cold diagnostics also timed out. Matched prefix equivalence supports further engineering, but neither a successful endpoint nor a whole-fit speedup. Warm starts between accepted physical trials cannot fix a first cold solve that never completes.

Keep **7,200 seconds, 8 GiB, one numerical thread, 32 accepted iterations and 96 trials** per fit. Preserve all convergence thresholds: 30 micrometres in position, density update below 1e-4, pulse update below 1e-8 m/s, scaled gradient below 1e-8, and nuisance updates below 1e-8 m for two consecutive updates with fresh full confirmation. Floor-limited progress cannot authorize covariance. Use a fresh undamped complete factor and marginalize nuisance uncertainty.

Before launch, prepare a new full-fit control adapter and independently audit its frozen identities, relocated input aliases, isolation and output routing. The current long-case runner accepts only the two exact long cases; changing its accepted case set is control implementation work. Retain all failed attempts, run serially under current-host admission, and leave every frozen v3.1/v4 benchmark untouched.

The one-hour cases are existing engineering regressions sharing data, not independent scientific trials or replacements for long-case failures. Successful short cases would demonstrate bounded optimizer completion only. Flight and multi-day capability remain unproved.
