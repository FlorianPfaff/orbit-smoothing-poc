# Execution10 terminal reporting helpers

These files preserve the separately reviewed bounded transfer and presentation code. They do not run an estimator or change numerical acceptance rules. The two files under `recovery09/` are exact fixture dependencies and provide the original path mapping and path-tokenization functions. The native validation keeps the separately pinned control09 implementation.

From the repository root, run the 55 current fabricated reporting tests with an external temporary directory:

```sh
TEST_OUTPUT=$(mktemp -d)
PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  scripts/correctness_execution10_reporting/test_transfer_terminal10_compact.py \
  scripts/correctness_execution10_reporting/test_publish_terminal10_02.py \
  -q -p no:cacheprovider --basetemp "$TEST_OUTPUT/fixtures" \
  --junitxml "$TEST_OUTPUT/junit.xml"
```

The terminal transfer requires a sealed plan naming the completed validation and postprocessor hashes, source and control pins, and the immediate failed09-to-execution10 installer correction. It refuses nonterminal or unclean execution. The publication helper requires that exact local transfer and an independently pinned terminal audit. Its index distinguishes actual execution10/source06 from the historical control09 compatibility lineage, while preserving the original collector files verbatim under `raw-report/`.

```sh
python transfer_terminal10_compact.py --plan TRANSFER_PLAN.json \
  --plan-sha256 PLAN_SHA256 --output NEW_TRANSFER_DIRECTORY \
  --manifest NEW_TRANSFER_MANIFEST.json --envelope NEW_TRANSFER_ENVELOPE.json
python publish_terminal10_02.py --plan PUBLICATION_PLAN.json \
  --plan-sha256 PLAN_SHA256
```

All output paths must be new. A report or successful collector does not authorize covariance, complete the separate150-fit benchmark, or establish release readiness. Exact code and independent review hashes are recorded in `source-manifest.json`.

The original `publish_terminal10.py` and its19-fixture tests are retained as the reviewed first draft. Its actual preflight rejected identity-HTML metadata and the collector README filename before creating output. Revision02 preserves all numerical classifications and fixes only those concrete publication-schema assumptions.
