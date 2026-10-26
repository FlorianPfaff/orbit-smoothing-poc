SOURCE ONLY; no imports, AST, tests, Python or native execution performed.

Measured issue: sequence02 correctly failed but incorrectly described the correctly failed cold aggregate as disagreeing with its failed density stage. The aggregate says failed; its pulse stage passed and density stage failed. The original records remain unchanged.

sequence.patch contains the one-line reporting correction. sequence.py is a separate copied candidate, NOT a launch-ready sequence: no new plan/review/freeze has been created, and old numerical output paths remain protected. Do not use it to replay or overwrite sequence02. Apply the correction only to separately prepared future controls or use the source review to explain the original published outcome.

tests.patch strengthens two existing error-attribution assertions and adds two status/return-code combinations. The original sequence tests and eleven-stage handoff tests are retained beside the candidate. Proposed qualification, only after root admits the serial slot: run the copied test_sequence and test_eleven_stage_contract unittest modules against this directory using the pinned existing interpreter and the prior controlled test environment. All controller calls are mocked and fixtures are temporary. No tests have been run here.

The density failure is unchanged. The correct sequence outcome remains failed, with cold-pulses passed and cold-density failed. No covariance, release readiness or scientific success is granted. The independent post-terminal numerical audit and publication of all eleven correctness plus two cold outcomes remain separate tasks.
