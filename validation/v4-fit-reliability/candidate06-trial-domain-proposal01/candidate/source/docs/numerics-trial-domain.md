# Synthetic fitted-reference trial rejection

Candidate06 changes the Python error boundary around the existing forward
closure evaluator. It retains candidate04's native executable, force models,
OU/pulse constraints, QR scaling, LM update formula, budgets and convergence
thresholds. Candidate05 is not an ancestor.

The original one-hour cold density fit stopped on its first LM trial. An
independent augmented least-squares reconstruction agrees with the saved damped
step, including all 61 OU prior rows. The maximum log-density correction was
20.3769829508 despite the nonzero OU penalty. Damping in scaled coordinates can
redistribute corrections among coupled parameters; it does not bound each
physical coordinate or its exponential.

The first propagation closure produced finite states, including strongly
nonelliptic osculating states. GROOPS then fitted a mean equinoctial reference to
those generated positions. An isolated replay using the exact archived binary
orbit, unchanged native object files and original fitting loop reproduced the
failure: update 1 made the semi-major axis negative and eccentricity greater
than one; update 2 made all six fitted elements nonfinite. The existing precise
reference guard then emitted `Nonfinite equinoctial reference input`.

The adapter recognizes that exact terminal error only after a normal native
exit code 1 in synthetic reference propagation, with a preceding completed,
finite generated closure and a nonelliptic osculating-state witness. This
extra witness conservatively qualifies an already failed evaluation; it is not
a new trajectory acceptance cut. The adapter records the native error, input
orbit/configuration hashes and state diagnostics in
`trial-domain-failure.json`, preserving the failed propagation files.

The typed failure is recoverable only inside the optimizer's candidate
evaluation block. The trial is rejected, no accepted state or factor is
installed, and the original damping increase applies. Initial, repeated,
refined, confirmation and final-covariance evaluations remain fatal. An
untyped error with the same reason remains fatal, as do unknown errors, input
errors, crashes, timeouts and resource failures. There is no density clipping,
alternate propagation path or covariance from a failed trial.

Tests use the archived failed closure as a byte-pinned fixture, exercise actual
closure error wiring, verify rollback and the unchanged damping sequence, and
check that all nontrial phases remain fatal. They are focused implementation
tests, not substitutes for the prescribed correctness suite or either original
cold full fit. Full-fit success and release readiness require fresh independent
validation; the historical density failure remains a failure.
