V3 publication helper (scratch only; outside frozen scientific source)
===================================================================

Nothing has been harvested. The campaign must first finish synthetic primary,
synthetic stress, float-ambiguity flight, and the separate native AR reference.
The collector requires their completed manifests/reports, both frozen selections
and evaluation-input freezes, the protocol, acceptance gates, and complete driver
records. Failed fits and unavailable SLR are allowed and remain explicit; missing
planned fits, incomplete calibration or a mismatched hash block publication.
Readiness checks all 1,650 unique case/method rows (1,600 synthetic primary, 20
stress, 24 float flight and 6 native AR) against each frozen input case list. It
requires both stages and reports to identify the expected source and protocol.
A complete design can contain failures; it need not have 1,650 valid fits.

Python 3.11+ is required. Read-only checks use only its standard library.
Collection also requires matplotlib and numpy; the configured remote orbit-poc
Python environment supplies them. Keep harvest_v3.py and render_v3_figures.py
together. No estimator is imported or executed.

Read-only check on the remote campaign host:

  python harvest_v3.py --check-only \
    --source /mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/campaign-v3-03 \
    --expected-source 3b434b8c6d185187cc394795f901d082abd8fd2d38e6a7202feb0c52a105e33e \
    --output /mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/publication/v3

Exit 2 means results are not ready. The JSON lists missing/inconsistent records
and planned original/derived output paths. It does not create the output directory.
Candidate 03 requires the explicit --expected-source value above; the older f2
default deliberately fails this identity check. Neither value changes the source
identity recorded in original manifests or derived reports.

ONLY AFTER check-only reports ready:true and all intended results exist:

  python harvest_v3.py --collect \
    --source /mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/campaign-v3-03 \
    --expected-source 3b434b8c6d185187cc394795f901d082abd8fd2d38e6a7202feb0c52a105e33e \
    --output /mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/publication/v3

The target must not exist and must end in /v3. Existing v2 or v3 outputs are never
overwritten. Collection stages outside the raw campaign, checks copied/result
hashes again, binds copied manifest bytes to the read-only readiness snapshot,
and renames the complete bundle into place. A failed collection
keeps an unpublished staging directory with incomplete-harvest.json.
The collector renders the fixed figures inside that staging directory before
source re-verification, inventory hashing and the final rename. A rendering
failure therefore leaves no published partial bundle. Never invoke the renderer
against a published directory; it refuses any existing publication.json.

From the local WORKSPACE root, after successful collection:

  rsync -a gpuserver6000:/mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/publication/v3/ \
    outputs/orbit-smoothing-poc/runs/v3/

The new landing page is runs/v3/index.html. Its v2 link is ../../results.html,
and all four report links stay relative inside the bundle. Existing report HTML
is self-contained in candidate 03 and is copied byte-for-byte. No repo-root report,
v2 files, runtime sources, git index, commit or remote repository is modified by
the helper. runs/ is currently gitignored; the parent task must deliberately add
the compact runs/v3 deliverable after inspecting its file sizes and inventory.

Preservation and scope:

* Original protocol, calibration, acceptance, input-freeze, run, driver, and
  report files retain their exact bytes. JSON larger than 1 MiB is stored in a
  deterministic gzip container, with original-payload and container SHA256 both
  recorded. Original paths/hashes are never rewritten. Separate file-inventory
  entries map remote source locators to local publication paths.
* Gate evidence and selected acquisition/generation, nominal-initialization and
  SLR correction manifests are copied by hash. The input freezes still carry
  every declared raw-data hash. Bulky raw observations, native builds, fitted
  trajectory/covariance arrays and per-epoch calibration arrays stay external.
* Existing raw-data bytes are not all reread by harvesting. Actual source
  manifests, score-result checkpoints and native executable identity are
  verified. Runtime preparation/evaluation already performed raw hash checks.
* Derived metrics.jsonl includes every evaluation fit's case, method, exact
  result references, timing, peak RSS and compact metrics. calibration-scores
  retains all candidates, arc/mask rows, expansion rounds and failures. Revisited
  candidates are explicit rows; they are not independent data.
* The landing report emphasizes the predeclared primary cell, seed-paired CIs,
  fixed-epoch coverage and missing/failing seeds, calibration restrictions, and
  the separate five-seed mixed-force stress test. Flight SLR and GPS-derived GNV
  agreement remain distinct. Native AR is a separate reference. A completed
  bundle makes no automatic superiority or flight-truth-coverage claim.
* publication.json hashes copied and derived files. No file may exceed 95 MiB.
  Validation evidence belongs to the publication context, not frozen scientific runtime.
* Fixed figures read only the completed compact summary and synthetic report,
  never trajectories, truth or fit arrays. They display primary whole-arc and
  blackout RMSE differences, primary 11/12/13-hour coverage, and all 15 secondary
  whole-arc RMSE comparisons. The comparison orientation is always density minus
  pulses. Existing paired-seed CIs and Wilson intervals are displayed without
  recomputing scientific statistics. Missing pairs retain the 50-seed denominator;
  unavailable means/CIs remain unavailable. Secondary orbit panels use separate
  x scales and say so explicitly. No automatic significance claim is added.
* Each figure has PNG and editable SVG outputs. figures/figure-manifest.json
  records exact compact input hashes, renderer hash, library versions and figure
  hashes. Inputs/figure paths are relative to the bundle/manifest so the atomic
  rename cannot create stale staging paths. Exact postprocessing helper sources
  are included under postprocessing/, independently of frozen scientific runtime.

Before collection, run only the scratch unit checks:

  python work/v3/publication/test_harvest_v3.py
  python work/v3/publication/test_render_v3_figures.py

These test readiness refusal, byte/hash preservation, gzip payload verification,
identical-content deduplication, changed-source rejection, and relative report
links using temporary fictitious files. Additional checks use 1,650 explicitly
fictional excluded rows to verify readiness without equating validity and execution,
reject duplicate/unfrozen rows, enforce candidate 03 identity, and prevent source
changes between readiness and collection. Stress denominators and per-campaign
limitations remain visible. Figure checks reject epoch-based bootstrap intervals
and coverage estimates or confidence levels inconsistent with their counts. They do not harvest a scientific run.

Optional visual QA (requires matplotlib/numpy):

  python work/v3/publication/render_v3_figures.py --fixture --output NEW_QA_DIR

This explicitly fictional fixture is marked on every figure and in its filenames
and manifest. It includes missing pairs, unavailable means/CIs and zero-trial
coverage. Keep fixture outputs in scratch, never in runs/v3 or scientific evidence.
The checked fixture figures are under work/v3/publication/figure-qa/ (first layout)
and figure-qa-02/ (final layout), with remote persistent copies under
validation-current/figure-qa-01 and figure-qa-02. These are QA, not experiment data.

Read-only campaign status monitor
--------------------------------

monitor_v3.py prints a single operational JSON snapshot without writing any file.
It reads only protocol/gate manifests, driver resource records, and compact
result-record.json checkpoints. It never opens result.json, job request contents,
calibration scores, scientific reports, truth arrays, GNV or SLR observations.
Request-file timestamps identify uncheckpointed work without interpreting it.

  python monitor_v3.py \
    --root /mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/campaign-v3-02 \
    --config /home/florianpfaff/codex-runs/orbit-comparison-v3-20261013/production-config-02.json

The explicit config verifies the frozen settings and restricts process discovery
to this campaign. The monitor is mirrored alongside harvest_v3.py on the remote
host. It runs once; it does not schedule itself or launch/resume anything. Redirect
stdout outside the frozen campaign if a status snapshot should be retained.

The 1,920 initial calibration fits are not a final completion denominator: two
possible boundary expansions can add candidates, with checkpoint reuse reducing
unique jobs. The fixed evaluation design has 1,650 fits, including stress and AR.
Failed/invalid/excluded/incomplete terminal checkpoints are shown explicitly;
uncheckpointed jobs may be running, queued or interrupted and are never called
failed based on age. Checkpoint counts are operational observations and do not
replace scientific reports or result-file hash verification.

Actionable concerns cover failed driver phases, malformed checkpoint identities,
violations of the frozen worker-budget rule, duplicate matching drivers and live
memory below the 8 GiB reserve. Resource caps use 3.5 GiB per native worker and are
recomputed between phases, not continuously enforced as hard RSS limits. A single
failed fit remains a reported experimental outcome rather than a reason to tune
settings or silently rerun it.

  python work/v3/publication/test_monitor_v3.py

Three fictional tests cover workload counts, worker-budget arithmetic, and the
separation of running jobs from failures without parsing request/result contents.
