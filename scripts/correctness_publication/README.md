# Bounded correctness-report publication

This is a presentation adapter for closed execution attempts07/08 using the
frozen candidate07 control protocol. It preserves the complete original audit,
summary and HTML as gzip files, and produces a compact HTML index and JSON
summary. It does not run the estimator, change an acceptance test, replace the
original collector or hide that collector's failure.

The source manifest binds the exact adapter and 53 fabricated tests to their
author and independent review receipts. The previous 49-test draft's two
attribution gaps and the review requesting changes are preserved in the
attempt07 provenance. The final adapter checks both original postprocessor
result hashes and the original transfer inventory.

Run the isolated presentation tests from the repository root:

```sh
TEST_OUTPUT=$(mktemp -d /tmp/orbit-publication-tests.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/correctness_publication \
  -q -p no:cacheprovider --basetemp "$TEST_OUTPUT/fixtures" \
  --junitxml "$TEST_OUTPUT/junit.xml"
```

The adapter uses Python's standard library; its tests require pytest. These
are fabricated identity, attribution, failure-preservation and size-limit
tests. They do not establish numerical correctness.

A separately sealed plan specifies a new output directory:

```sh
python scripts/correctness_publication/publish_bounded_retry.py \
  --plan /absolute/path/publication-plan.json --plan-sha256 PLAN_SHA256
```

The plan schema is `orbit-poc-bounded-retry-publication-plan-v1`. Its fields are
`schema`, `execution_attempt` (`07` or `08`), `candidate_control_version` (`07`),
`execution_root`, `output`, `artifacts` and `attachments`. `execution_root`
selects the actual execution; the retained `candidate07-*` filenames identify
the unchanged control version. Inputs must come from terminal validation and
postprocessing journals with verified owned-process cleanup.

The thirteen required artifact roles are `execution`, `pins`, `source_freeze`,
`pipeline`, `postprocess`, `postprocess_plan`, `launch`, `postprocess_launch`,
`audit`, `summary`, `html`, `independent_review` and `transfer_inventory`.
Each pin records an absolute local `path`, stored `sha256` and `bytes`,
`encoding` (`identity` or `gzip`), and `original_sha256` and `original_bytes`.
Attachments use an explicit safe relative `name` and the same `artifact` pin.
The independent review must bind the exact source and both terminal journals.
The transfer inventory must bind the original report bytes and execution root.
A changed summary cannot bypass the original postprocessor's result hash by
merely refreshing its direct file pin.

Stored artifacts are limited to 16 MiB each and the output to 64 MiB; expanded
inputs are limited to 64 MiB each. The compact summary and HTML each have a 1 MiB
limit and fail instead of truncating. Every planned step remains present,
including missing and failed checks. Strict nuisance convergence and audited
numerical-floor-limited progress retain separate statuses. The output does not
authorize covariance, assess full release acceptance or reclassify the frozen
150-attempt benchmark.

Complete published artifacts have private paths tokenized before compression.
The manifest distinguishes the original hash/size from the published expanded
and compressed hash/size. Original raw evidence remains outside Git. The
publication adapter never changes those original files.
