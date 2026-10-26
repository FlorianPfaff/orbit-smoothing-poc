Candidate07: reject the measured unevaluable numerical closure trial

Status: source and tests written only. No Python import, compilation, native
execution or test execution has been performed for this candidate. Candidate06
and every prior outcome remain preserved. Both full cold fits and the complete
required correctness suite remain mandatory before calling this fix verified.

Parent: /mnt/d/orbit-v41-density-trial-candidate06/source, copied with ordinary
recursive copying (no hardlinks). Native executable remains exactly
28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d.
No native source, force, observation weight, prior, hyperparameter, convergence
threshold, iteration limit, wall limit or compatibility default changed.

Measured trigger
candidate06-cold02/cold-density/fit/point-005-trial-002/closure-03 returned normal
native exit1. The physical_correction solve failed to certify its returned
binary64 state: relative residual1.0644281392730035e-05, required2e-12,
iterations120, column0, duration3595seconds. The preceding closure's own tangent
passed (maximum residual9.8285642212607614e-13,3iterations). Trial1 had already
been correctly rejected as physical_trial_domain. Trial2 became native_failure
because the legacy classifier recognizes the old six-state error spelling.
Accepted iterations0, covariance false. These receipts do not determine the
underlying numerical cause or prove stronger damping will produce convergence.

Exact change
backend.py adds wide_tangent_closure_failure_evidence. It accepts only the pinned
native binary, synthetic_complete_v1, normal integer exit1 without timeout, a
finite preceding generated N-by-6 state with at least2epochs, a bounded log with
one PreprocessingVariationalEquation stage and one error, the exact four native
stack frames and terminal residual-error grammar. Only finite residual above
the unchanged2e-12, exactly120iterations, physical_correction column0 and finite
positive duration qualify. Other errors, unsupported contexts and native crashes
remain fatal. The generic legacy native_failure_reason is unchanged.

_close only considers this evidence after at least one successful generated
closure and an actual NativeExecutionError cause. It retains failed artifacts
and writes trial-closure-failure.json with parsed residual details and original
reference, config, binary and log hashes. It throws a distinct
NumericalTrialClosureFailure; the older PhysicalTrialDomainFailure behavior and
receipt remain unchanged.

The optimizer catches the new type only around candidate evaluation. It records
the rejection and evidence, leaves actual reduction/gain unknown, preserves the
accepted point and uses the existing damping update. It does not accept the
failed trajectory. The type is fatal at initialization, repeated objective,
refinement, confirmation or finish. A generic exception with the same reason
string is not made recoverable. Existing legacy error policies remain intact.

Tests written
test_numerics_trial_closure.py contains54 parametrized cases (not collected or
run): original log/XML/execution and preceding-state identity, strict parser
exclusions, finite preceding closure requirement, API evidence/rollback,
unchanged accepted linearization and damping, fatal nontrial stages and untyped
errors, and unchanged trial/wall budgets without false convergence. Fixtures
are actual failed-run outputs; monkeypatched API/optimizer tests are explicitly
unit harnesses, never claimed native replays. Old tests are copied unchanged.

Next required validation
Independent source review, focused/new and existing regression tests, complete
required native/propagation/objective/nuisance correctness checks, and both cold
full fits with original GNSS-only initialization in fresh output directories.
Preserve every failure. No historical frozen campaign executable/result is
replaced by this candidate.
