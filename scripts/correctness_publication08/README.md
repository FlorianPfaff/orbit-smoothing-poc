# Execution08 presentation helpers

These are the exact archived external helpers for the closed failed execution08.
They preserve full compressed reports and failed profiles; they do not run or
replace numerical acceptance gates. `source-manifest.json` binds source bytes
and independent fixture-test receipts. The original failed collector is retained.

The scripts record the actual execution paths and existing SSH/runtime layout.
They are provenance for this run, not a portable dataset downloader. Reproducing
that archival operation requires the recorded inputs, paths, source/data hashes
and the independently pinned reporting interpreter. Never use these scripts to
infer that the scientific checks passed.

`test_publish_failed_points08.py` has seven fabricated tests;
`test_preserve_failed_replay08.py` has twelve. The copied bounded adapter's
53 tests are published in `../correctness_publication/`. These tests use no
native solver. The objective appendix imports the exact bounded helper from
its recorded control directory; reproduce that layout before running its tests.
With a matching layout and pytest, use an external test-output directory:

```sh
TEST_OUTPUT=$(mktemp -d /tmp/orbit-publication08-tests.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/correctness_publication08 \
  -q -p no:cacheprovider --basetemp "$TEST_OUTPUT/fixtures" \
  --junitxml "$TEST_OUTPUT/junit.xml"
```

The static plot uses existing Matplotlib and exports the exact 49 source hashes,
CSV and render-runtime identity. It depicts only generations4–52 of one failed
profile; the complete history remains linked from the report.
