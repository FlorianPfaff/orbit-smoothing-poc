#!/usr/bin/env python3
"""Publish compact, byte-preserved evidence from an already completed v3 campaign.

Readiness uses only the standard library; collection also requires matplotlib
and numpy for fixed predeclared figures. Run on the campaign host, then copy the
completed bundle into runs/v3, or run locally against a mounted campaign root.
--check-only is read-only. Collection never invokes estimators or changes sources.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import gzip
import hashlib
from html import escape
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile

CAMPAIGNS = {"synthetic": ("synthetic", "primary", 1600),
             "stress": ("synthetic", "stress", 20),
             "flight": ("flight", "primary", 24),
             "flight_ar_reference": ("flight", "flight_ar_reference", 6)}
GATES = ("external_baseline", "model_correctness", "pipeline_correctness", "numerical_accuracy")
SOURCE_F2 = "f2b41a4b7650e26a450e2934801e3be44b680e4ccf16be14ff5c81d80ee611cd"
SOURCE_03 = "3b434b8c6d185187cc394795f901d082abd8fd2d38e6a7202feb0c52a105e33e"
PRIMARY_METHODS = ("groops_log_drag_ou", "groops_pulses")
NATIVE_74863 = "74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453"
FIGURE_STEMS = ("primary-paired-rmse", "primary-fixed-epoch-coverage", "secondary-whole-arc-rmse")
DERIVED = ("index.html", "summary.json", "metrics.jsonl", "calibration-scores.jsonl",
           "failures.jsonl", "raw-artifact-locators.jsonl", "file-inventory.json", "publication.json",
           "figures/figure-manifest.json") + tuple(
               f"figures/{stem}.{extension}" for stem in FIGURE_STEMS for extension in ("png", "svg"))
POSTPROCESSING = ("postprocessing/harvest_v3.py", "postprocessing/render_v3_figures.py")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n")


def jsonl(path, rows):
    with Path(path).open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False)+"\n")


def source_path(root, path):
    value = Path(path)
    return value if value.is_absolute() else root/value


def original_files():
    files = ["protocol.json", "acceptance-gates.json", "campaign-driver.json",
             "driver-synthetic.json", "driver-flight.json"]
    for stage in ("synthetic", "flight"):
        files += [f"calibration-{stage}.json", f"calibration-input-preparation-{stage}.json",
                  f"evaluation-input-freeze-{stage}.json"]
    for campaign in CAMPAIGNS:
        files += [f"run-{campaign}.json", f"report-{campaign}/index.html", f"report-{campaign}/report.json"]
    return files


def readiness(root, expected_source):
    """Check only compact manifests. No output writes and no native/raw-data reads."""
    errors, documents, identities = [], {}, {}
    for name in original_files():
        path = root/name
        if not path.is_file():
            errors.append(f"Missing {name}")
        else:
            try:
                payload = path.read_bytes()
                identities[name] = hashlib.sha256(payload).hexdigest()
                if not payload.strip():
                    raise ValueError("Empty required file")
                if path.suffix == ".json":
                    document = json.loads(payload)
                    if not isinstance(document, dict) or not document:
                        raise ValueError("Required manifest must be a nonempty object")
                    documents[name] = document
            except (ValueError, OSError) as error:
                errors.append(f"Unreadable {name}: {error}")
    protocol = documents.get("protocol.json", {})
    protocol_hash = protocol.get("protocol_hash")
    if protocol:
        if canonical({k:v for k,v in protocol.items() if k != "protocol_hash"}) != protocol_hash:
            errors.append("Frozen protocol hash is invalid")
        if protocol.get("source", {}).get("sha256") != expected_source:
            errors.append("Unexpected frozen runtime source")
        if protocol.get("native_binary", {}).get("sha256") != NATIVE_74863:
            errors.append("Unexpected native binary")
        if protocol.get("config", {}).get("primary_cell") != ["leo500", "disturbed", "blackout"]:
            errors.append("Primary cell differs from the accepted plan")
    gates = documents.get("acceptance-gates.json", {})
    if gates:
        if gates.get("protocol_hash") != protocol_hash or gates.get("evidence_hash") != canonical(
                {k:v for k,v in gates.items() if k != "evidence_hash"}):
            errors.append("Acceptance evidence identity/hash is invalid")
        if not all(gates.get("gates", {}).get(name, {}).get("passed") is True for name in GATES):
            errors.append("One or more required numerical gates have not passed")
    driver = documents.get("campaign-driver.json", {})
    if driver and (driver.get("status") != "complete" or
            [(row.get("stage"),row.get("status")) for row in driver.get("stages", [])] !=
            [("synthetic","complete"),("flight","complete")]):
        errors.append("Campaign driver has not completed both stages")
    for stage in ("synthetic", "flight"):
        stage_driver = documents.get(f"driver-{stage}.json", {})
        if stage_driver and (stage_driver.get("status") != "complete" or
                stage_driver.get("stage") != stage or stage_driver.get("protocol_hash") != protocol_hash):
            errors.append(f"{stage} driver has not completed this frozen protocol")
        prepared=documents.get(f"calibration-input-preparation-{stage}.json",{})
        expected_preparations=48 if stage=="synthetic" else 12
        if prepared and (prepared.get('status')!='prepared' or prepared.get('protocol_hash')!=protocol_hash
                or prepared.get('prepared_cases')!=expected_preparations
                or len(prepared.get('prepare_results',[]))!=expected_preparations):
            errors.append(f"{stage} calibration input preparation is incomplete")
        calibration = documents.get(f"calibration-{stage}.json", {})
        selection_keys = ("protocol_hash", "selections", "evidence", "calibration_adequate",
                          "calibration_disclosures", "boundary_diagnostics")
        if calibration and (not calibration.get("complete") or calibration.get("protocol_hash") != protocol_hash
                or calibration.get("source_hash") != expected_source or calibration.get("stage") != stage
                or not all(key in calibration for key in selection_keys)
                or calibration.get("selection_hash") != canonical({key:calibration[key] for key in selection_keys})):
            errors.append(f"{stage} calibration selection is incomplete or inconsistent")
        frozen = documents.get(f"evaluation-input-freeze-{stage}.json", {})
        if frozen and (frozen.get("status") != "frozen" or frozen.get("protocol_hash") != protocol_hash
                or frozen.get("source_hash") != expected_source or frozen.get("stage") != stage
                or frozen.get("native_binary") != protocol.get("native_binary")
                or frozen.get("selection_hash") != calibration.get("selection_hash")
                or frozen.get("input_freeze_hash") != canonical({k:v for k,v in frozen.items() if k != "input_freeze_hash"})):
            errors.append(f"{stage} evaluation input freeze is inconsistent")
    for campaign,(stage,kind,count) in CAMPAIGNS.items():
        run = documents.get(f"run-{campaign}.json", {})
        summary = documents.get(f"report-{campaign}/report.json", {})
        selection = documents.get(f"calibration-{stage}.json", {}).get("selection_hash")
        if run and (not run.get("complete") or run.get("status") != "complete"
                or run.get("stage") != stage or run.get("campaign") != kind
                or run.get("expected_fits") != count or len(run.get("runs", [])) != count
                or run.get("source_hash") != expected_source
                or run.get("acceptance_evidence_hash") != gates.get("evidence_hash")
                or run.get("protocol_hash") != protocol_hash or run.get("selection_hash") != selection):
            errors.append(f"{campaign} did not attempt the complete frozen design")
        if summary and (not summary.get("orchestration_complete") or not summary.get("planned_design_complete")
                or summary.get("status") != "complete" or summary.get("stage") != stage
                or summary.get("source_hash") != expected_source
                or any(summary.get(key) != count for key in ("observed_fits", "expected_fits", "planned_fit_rows"))
                or summary.get("missing_planned_fits") != 0 or summary.get("metrics_error")
                or summary.get("protocol_hash") != protocol_hash or summary.get("selection_hash") != selection):
            errors.append(f"{campaign} report does not match its completed design/selection")
        if run:
            try:
                methods = ("groops_pulses_ar",) if kind == "flight_ar_reference" else PRIMARY_METHODS
                if sorted(run["methods"]) != sorted(methods):
                    raise ValueError("Wrong or duplicate methods")
                cases = run["planned_cases"]
                case_keys = [canonical(case) for case in cases]
                expected_keys = {(key, method) for key in case_keys for method in methods}
                actual_keys = [(canonical(row["case"]), row["method"]) for row in run["runs"]]
                frozen = documents[f"evaluation-input-freeze-{stage}.json"]
                frozen_keys = [canonical(row["case"]) for row in frozen["prepare_results"] if row["campaign"] == kind]
                if (len(case_keys) != count // len(methods) or len(set(case_keys)) != len(case_keys)
                        or len(actual_keys) != count or set(actual_keys) != expected_keys
                        or sorted(frozen_keys) != sorted(case_keys)
                        or frozen["campaign_case_counts"].get(kind) != len(case_keys)):
                    raise ValueError("Missing, duplicate or unfrozen case/method row")
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"{campaign} exact frozen fit design is invalid: {error}")
    return {"ready":not errors, "errors":errors, "documents":documents,
            "original_file_sha256":identities, "expected_source":expected_source,
            "protocol_hash":protocol_hash, "expected_evaluation_fits":sum(value[2] for value in CAMPAIGNS.values())}


class Collector:
    """Keep original bytes; compression changes the container, never the payload."""
    def __init__(self, source, destination):
        self.source, self.destination = source,destination
        self.inventory, self.sources, self.paths, self.results = [],{}, {}, {}

    def verify(self,path,expected):
        path=Path(path)
        if str(path) in self.sources:
            if self.sources[str(path)]!=expected: raise ValueError(f"Conflicting source hashes: {path}")
        else:
            if sha(path)!=expected: raise ValueError(f"Changed source artifact: {path}")
            self.sources[str(path)]=expected
        return path

    def copy(self, path, relative, expected=None):
        path=Path(path); relative=Path(relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Publication path escapes the bundle")
        identity=sha(path)
        if expected is not None and identity != expected:
            raise ValueError(f"Changed source artifact: {path}")
        if str(path) in self.paths:
            return self.paths[str(path)]
        self.sources[str(path)]=identity
        compressed=path.suffix==".json" and path.stat().st_size > 1024*1024
        if compressed: relative=Path(str(relative)+".gz")
        target=self.destination/relative; target.parent.mkdir(parents=True,exist_ok=True)
        existed=target.exists()
        if compressed and not existed:
            with path.open("rb") as stream, target.open("wb") as raw:
                with gzip.GzipFile(fileobj=raw,mode="wb",filename="",mtime=0) as zipped:
                    shutil.copyfileobj(stream,zipped)
        elif not existed:
            shutil.copyfile(path,target)
        if compressed:
            with gzip.open(target,"rb") as stream:
                if hashlib.file_digest(stream,"sha256").hexdigest()!=identity:
                    raise ValueError("Compressed payload changed or destination collision")
        elif sha(target)!=identity:
            raise ValueError("Copied bytes changed or destination collision")
        if target.stat().st_size > 95*1024*1024:
            raise ValueError(f"Compact publication artifact exceeds 95 MiB: {relative}")
        entry={"source_path":str(path),"source_sha256":identity,"source_bytes":path.stat().st_size,
            "published_path":relative.as_posix(),"published_sha256":sha(target),
            "published_bytes":target.stat().st_size,"encoding":"gzip_original_bytes" if compressed else "original_bytes"}
        self.inventory.append(entry);self.paths[str(path)]=relative.as_posix()
        return relative.as_posix()

    def indexed(self, index):
        path=source_path(self.source,index["result_path"])
        expected=index["result_sha256"]
        if str(path) not in self.results:
            self.verify(path,expected)
            result=read(path)
            if result.get("status")!=index.get("status") or result.get("request_hash")!=index.get("request_hash"):
                raise ValueError(f"Result checkpoint identity changed: {path}")
            self.results[str(path)]=(expected,result)
        old,result=self.results[str(path)]
        if old!=expected: raise ValueError("Conflicting hashes for one result")
        return result


def text(value):
    if value is None: return "unavailable"
    if isinstance(value,float): return f"{value:.6g}"
    if isinstance(value,(list,dict,tuple)): return escape(json.dumps(value,sort_keys=True))
    return escape(str(value))


def table(headers,rows):
    return "<table><thead><tr>"+"".join(f"<th>{escape(h)}</th>" for h in headers)+"</tr></thead><tbody>"+"".join(
        "<tr>"+"".join(f"<td>{text(v)}</td>" for v in row)+"</tr>" for row in rows)+"</tbody></table>"


def figure(stem,description):
    return (f'<figure><a href="figures/{stem}.svg"><img src="figures/{stem}.png" '
            f'alt="{escape(description,quote=True)}"></a><figcaption>{escape(description)} '
            f'· <a href="figures/{stem}.svg">SVG</a></figcaption></figure>')


def load_renderer():
    spec=importlib.util.spec_from_file_location('v3_fixed_figures',Path(__file__).with_name('render_v3_figures.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def render_publication_figures(stage,collector):
    """Derived figures enter the same atomic staging transaction as every manifest."""
    if (stage/'publication.json').exists():raise ValueError('Cannot add figures after publication hashing')
    module=load_renderer()
    collector.copy(Path(__file__),POSTPROCESSING[0])
    collector.copy(Path(module.__file__),POSTPROCESSING[1])
    return module.render_bundle(stage)


def landing(summary,metrics,paths):
    def link(label,source): return f'<a href="{escape(paths[source],quote=True)}">{escape(label)}</a>'
    root=summary["campaign_source_directory"]
    primary=summary["primary_paired_comparisons"]
    sections=["<h1>GROOPS orbital disturbance comparison · v3</h1>",
        "<p>The frozen computations have been attempted. Method validity, failed fits and uncertainty calibration are reported below; execution completion alone does not establish superiority.</p>",
        '<p><a href="../../results.html">Published v2 report</a> · <a href="summary.json">Compact v3 summary</a> · <a href="file-inventory.json">Original-byte provenance map</a></p>',
        "<p><strong>Primary scenario:</strong> 500 km, disturbed atmosphere, 11–13 h blackout; 50 independent paired seeds. Other cells are secondary. The atmospheric latent variable is an effective drag correction, not an independently verified density measurement.</p>",
        "<h2>Primary paired comparison</h2>",
        "<p>Differences are method A minus method B. Confidence intervals resample independent seeds, never correlated trajectory epochs. Invalid or unavailable pairs are explicit.</p>",
        table(["Metric","A","B","Valid/planned pairs","Failed/missing","Mean A−B","Paired 95% interval"],
            [[r["metric"],r["method_a"],r["method_b"],f'{r["valid_seed_pairs"]}/{r["planned_seed_pairs"]}',
              r["failed_or_missing_seed_pairs"],r["mean_difference_a_minus_b"],r["bootstrap_95_interval"]] for r in primary]),
        figure(FIGURE_STEMS[0],"Primary RMSE differences use density minus pulses; intervals resample independent paired seeds."),
        "<h2>Uncertainty and calibration limitations</h2>",
        "<p>Covariance is local Gaussian uncertainty conditional on selected hyperparameters, fixed observation weights/products and the modeled forces. It excludes hyperparameter-selection uncertainty. Coverage intervals are Wilson intervals across independent seeds at each fixed epoch; these multiple diagnostics are not a multiplicity-adjusted hypothesis test.</p>",
        table(["Method","Blackout hour","Covered/valid","Planned","Wilson 95% interval","Failed/unavailable","Interval below nominal 95%"],
            [[r["method_id"],r["hours_since_start"],f'{r["successes"]}/{r["trials"]}',r["planned_seeds"],r["interval"],
              r["failed_or_unavailable_seeds"],r["interval_wholly_below_nominal"]] for r in summary["primary_coverage"]]),
        figure(FIGURE_STEMS[1],"Coverage and Wilson intervals at the fixed blackout entry, midpoint and exit epochs."),
        "<details><summary>Coverage intervals wholly below nominal 95% across all synthetic cells and stress</summary>"+
        table(["Campaign","Cell","Method","Hour","Covered/valid","Wilson 95% interval","Failed/unavailable"],
            [[r['campaign'],r['cell_id'],r['method_id'],r['hours_since_start'],str(r['successes'])+'/'+str(r['trials']),
              r['interval'],r['failed_or_unavailable_seeds']] for r in summary.get('coverage_intervals_wholly_below_nominal',[])])+"</details>",
        "<pre>"+text(summary["calibration"])+"</pre>",
        "<p>An improving unresolved calibration boundary prevents superiority claims. Narrower intervals or smaller normalized errors alone do not establish better uncertainty calibration.</p>",
        "<h2>Secondary cells and mixed-force stress</h2>",
        figure(FIGURE_STEMS[2],"All 15 secondary cells, in frozen order, retain missing pairs. Panels use separate x scales."),
        "<p>The separate 500 km stress test injects unmodeled radial/cross-track acceleration. Its five paired seeds per coverage pattern are exploratory evidence about errors outside the density model.</p>"]
    for name in ("synthetic","stress"):
        sections.append("<p>"+link(name+" complete report",str(Path(root)/f"report-{name}/index.html"))+"</p>")
    sections += [table(["Stress cell","Metric","A","B","Valid/planned pairs","Failed/missing","Mean A−B","95% interval"],
        [[r["cell_id"],r["metric"],r["method_a"],r["method_b"],f'{r["valid_seed_pairs"]}/{r["planned_seed_pairs"]}',
          r["failed_or_missing_seed_pairs"],r["mean_difference_a_minus_b"],r["bootstrap_95_interval"]]
         for r in summary["stress_paired_comparisons"]]),
        "<h2>Independent flight evidence: SLR</h2>",
        "<p>May 7–12 is a limited quiet/storm event study. May 11 has only six raw normal points before screening. SLR is withheld from fitting; pass/station/geometry scores include their stated covariance and corrections. Overlapping groups are not independent samples.</p>"]
    flight=[r for r in metrics if r["campaign"]=="flight"]
    sections.append(table(["Date","Coverage","Method","Usable SLR points","SLR RMS (m)","Formal points","Predictive NLL","Evaluation status"],
        [[r["case"].get("date"),r["case"].get("coverage"),r["method"],
          r["metrics"].get("native_slr",{}).get("normal_points"),r["metrics"].get("native_slr",{}).get("range_rms_m"),
          r["metrics"].get("formal_prediction",{}).get("observations"),r["metrics"].get("predictive",{}).get("nll"),r["evaluation_status"]] for r in flight]))
    sections += ["<h2>GPS-derived GNV1B agreement</h2>",
        "<p>GNV1B shares underlying GPS information. Disagreement is not truth error and supplies neither Cartesian NEES nor flight truth coverage.</p>",
        table(["Date","Coverage","Method","Matched epochs","Position disagreement RMS (m)"],
            [[r["case"].get("date"),r["case"].get("coverage"),r["method"],
              r["metrics"].get("reference_agreement",{}).get("matched_epochs"),
              r["metrics"].get("reference_agreement",{}).get("position_rms_m")] for r in flight]),
        "<p>"+link("Float-ambiguity flight comparison",str(Path(root)/"report-flight/index.html"))+"</p>",
        "<h2>Additional native ambiguity-resolution reference</h2>",
        "<p>The official native 20-minute pulse/ambiguity-resolution configuration is a separate reference, outside the primary float-ambiguity comparison.</p>",
        "<p>"+link("Native ambiguity-resolution report",str(Path(root)/"report-flight_ar_reference/index.html"))+"</p>",
        "<h2>Failures, resources and provenance</h2>",
        '<p><a href="metrics.jsonl">Per-fit compact metrics/resources</a> · <a href="failures.jsonl">All failed, invalid, excluded and incomplete records</a> · <a href="calibration-scores.jsonl">Every calibration candidate/arc/holdout score</a> · <a href="raw-artifact-locators.jsonl">Bulky raw artifact locations and declared hashes</a> · <a href="figures/figure-manifest.json">Figure inputs, renderer versions and hashes</a></p>',
        "<p>Original manifests and reports are copied without rewriting their paths or hashes. Large JSON files may be gzip containers of the exact original bytes. Their remote paths are documented locators; the provenance map supplies the separate local publication paths.</p>",
        "<p>Native peak RSS excludes the wrapper and filesystem caches; elapsed times depend on concurrency and host contention. Approximate native state sensitivities and all numerical diagnostics remain in the linked acceptance evidence.</p>",
        "<details><summary>Per-campaign validity, scope and limitations</summary><pre>"+
        text(summary.get("campaign_diagnostics",{}))+"</pre></details>",
        "<pre>"+text({k:summary[k] for k in ("protocol_hash","source_hash","native_binary_sha256","failure_counts","superiority_claim_issued")})+"</pre>"]
    return "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Orbital comparison v3</title><style>body{font:16px/1.5 system-ui;max-width:1200px;margin:3rem auto;padding:0 1.3rem}table{border-collapse:collapse;width:100%;font-size:.85rem}td,th{padding:.5rem;border-bottom:1px solid #ddd;text-align:left}h2{margin-top:2rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}figure{margin:1.5rem 0}figure img{display:block;width:100%;height:auto}figcaption{font-size:.85rem;color:#555}</style><body>"+"".join(sections)+"</body></html>"


def collect(root,output,ready):
    if not ready["ready"]: raise ValueError("Campaign not ready: "+"; ".join(ready["errors"]))
    if output.exists(): raise ValueError("Choose a new output directory; existing v2/v3 publications are never overwritten")
    if output.name != "v3": raise ValueError("Publication output must end in /v3, keeping v2 separate")
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".v3-harvest-",dir=output.parent))
    collector=Collector(root,stage); docs=ready["documents"]
    try:
        for name in original_files(): collector.copy(root/name,name,ready["original_file_sha256"][name])
        native=docs["protocol.json"]["native_binary"]
        collector.verify(source_path(root,native["path"]),native["sha256"])
        # Additional compact status/manifests, never job directories or native arrays.
        for pattern in ("*input-preparation-*.json","precalibration-input-launch*.json"):
            for path in sorted(root.glob(pattern)): collector.copy(path,path.name)
        for gate in docs["acceptance-gates.json"]["gates"].values():
            for artifact in gate.get("artifacts",[]):
                path=source_path(root,artifact["path"])
                collector.copy(path,Path("acceptance-evidence")/(artifact["sha256"]+path.suffix),artifact["sha256"])
        raw_rows,metrics,failures,calibration_rows=[],[],[],[]
        for phase in ("synthetic","flight"):
            calibration_preparation=docs[f"calibration-input-preparation-{phase}.json"]
            for row in calibration_preparation['prepare_results']:
                index=row['result_record'];prepared=collector.indexed(index)
                collector.copy(source_path(root,index['result_path']),
                    Path('data-manifests')/(index['result_sha256']+'.json'),index['result_sha256'])
                acquisition=source_path(root,index['result_path']).parent/'observations/data_manifest.json'
                if acquisition.is_file():
                    collector.copy(acquisition,Path('data-manifests')/(sha(acquisition)+'.json'))
            frozen=docs[f"evaluation-input-freeze-{phase}.json"]
            for item in frozen["inputs"]:
                raw_rows.append({"stage":phase,"declaration_source":f"evaluation-input-freeze-{phase}.json",**item})
                path=source_path(root,item["path"])
                if path.suffix==".json" and item["role"] in {
                    "acquisition_generation_manifest","nominal_initialization","slr_auxiliary_manifest"}:
                    collector.copy(path,Path("data-manifests")/(item["sha256"]+".json"),item["sha256"])
            for item in frozen.get("slr_auxiliary",[]):
                collector.copy(source_path(root,item["path"]),Path("data-manifests")/(item["sha256"]+".json"),item["sha256"])
            calibration=docs[f"calibration-{phase}.json"]
            for evidence in calibration["evidence"]:
                collector.verify(source_path(root,evidence["path"]),evidence["sha256"])
                raw_rows.append({"stage":phase,"usage":"calibration_evidence",
                    "declaration_source":f"calibration-{phase}.json",**evidence})
            for row in calibration["runs"]:
                current={"stage":phase,**row};calibration_rows.append(current)
                if row.get("result_record"):
                    index=row["result_record"]
                    collector.verify(source_path(root,index["result_path"]),index["result_sha256"])
                if not row.get("valid"):
                    failures.append({"phase":"calibration","failure_kind":"invalid_candidate_arc_holdout",**current})
        for campaign in CAMPAIGNS:
            for row in docs[f"run-{campaign}.json"]["runs"]:
                fit=collector.indexed(row["fit_record"])
                evaluation=collector.indexed(row["evaluation_record"]) if row.get("evaluation_record") else {}
                current={"campaign":campaign,"case":row["case"],"method":row["method"],"parameters":row.get("parameters"),
                    "status":fit.get("status"),"converged":fit.get("converged",False),
                    "covariance_valid":fit.get("covariance_valid",False),"evaluation_status":evaluation.get("status","not_run"),
                    "elapsed_seconds":fit.get("elapsed_seconds"),"peak_rss_bytes":fit.get("peak_rss_bytes"),
                    "metrics":evaluation.get("metrics",{}),"error":row.get("error") or evaluation.get("error") or fit.get("error"),
                    "source_fit_record":row["fit_record"],"source_evaluation_record":row.get("evaluation_record")}
                metrics.append(current)
                if not (fit.get("status")=="complete" and fit.get("converged") and fit.get("covariance_valid") and evaluation.get("status")=="complete"):
                    failures.append({"phase":"evaluation","failure_kind":"invalid_or_unavailable_fit_or_evaluation",**current})
                for result in (fit,evaluation):
                    for artifact in result.get("artifacts",[]):
                        raw_rows.append({"campaign":campaign,"declaration_source":result.get("record_path"),**artifact})
        synthetic=docs["report-synthetic/report.json"];stress=docs["report-stress/report.json"]
        primary_cell="/".join(synthetic["primary_cell"])
        primary=[r for r in synthetic["paired_metrics"] if r["cell_id"]==primary_cell and r["applicable"]]
        coverage=[{**r,"interval_wholly_below_nominal":bool(r["interval"] and r["interval"][1]<.95)}
                  for r in synthetic["fixed_epoch_coverage"] if r["cell_id"]==primary_cell]
        coverage_flags=[{"campaign":name,**row} for name,report in (("synthetic",synthetic),("stress",stress))
            for row in report["fixed_epoch_coverage"] if row.get("interval") and row["interval"][1]<.95]
        summary={"schema_version":3,"published_at_utc":datetime.now(timezone.utc).isoformat(),
            "campaign_source_directory":str(root),"protocol_hash":ready["protocol_hash"],
            "source_hash":docs["protocol.json"]["source"]["sha256"],
            "native_binary_sha256":docs["protocol.json"]["native_binary"]["sha256"],
            "execution_complete":True,"superiority_claim_issued":False,
            "primary_paired_comparisons":primary,"primary_coverage":coverage,
            "coverage_intervals_wholly_below_nominal":coverage_flags,
            "campaign_diagnostics":{name:{key:docs[f"report-{name}/report.json"].get(key) for key in
                ("stage","expected_fits","observed_fits","planned_fit_rows","missing_planned_fits",
                 "method_counts","all_fits_valid","numerical_gates_passed","calibration_adequate",
                 "calibration_disclosures","scope","limitations","interpretation")}
                 for name in CAMPAIGNS},
            "stress_paired_comparisons":[r for r in stress["paired_metrics"] if r["applicable"] and
                r["metric"] in ("whole_arc.position_rmse_m","gap.position_rmse_m","gap.position_nees")],
            "failure_counts":dict(collections.Counter(row["phase"] for row in failures)),
            "calibration":{phase:{key:docs[f"calibration-{phase}.json"].get(key) for key in
                ("selection_hash","calibration_adequate","calibration_disclosures","selections")}
                for phase in ("synthetic","flight")},
            "interpretation":"Execution is complete, including reported failures. Scientific validity requires reading the paired uncertainty, coverage and independent SLR results; superiority is not automatically inferred."}
        write(stage/"summary.json",summary);jsonl(stage/"metrics.jsonl",metrics)
        jsonl(stage/"calibration-scores.jsonl",calibration_rows);jsonl(stage/"failures.jsonl",failures)
        jsonl(stage/"raw-artifact-locators.jsonl",raw_rows)
        render_publication_figures(stage,collector)
        (stage/"index.html").write_text(landing(summary,metrics,collector.paths))
        write(stage/"file-inventory.json",{"original_files":collector.inventory,
            "policy":"Original bytes preserved. Original hashes and remote locators inside files are never rewritten. Gzip containers retain original payload hashes separately.",
            "large_external_data_reverified_by_harvest":False})
        for path,expected in collector.sources.items():
            if sha(path)!=expected: raise ValueError(f"Source changed during collection: {path}")
        files={str(p.relative_to(stage)):sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}
        if any((stage/name).stat().st_size>95*1024*1024 for name in files):
            raise ValueError("A derived publication file exceeds the 95 MiB cap")
        write(stage/"publication.json",{"schema_version":3,"files":files,"bundle_content_hash":canonical(files),
            "protocol_hash":ready["protocol_hash"],"collector_sha256":sha(__file__),
            "derived_files":list(DERIVED),"postprocessing_sources":list(POSTPROCESSING),
            "collected_original_files":len(collector.inventory),
            "bulky_native_outputs_remain_external":True,"preserves_existing_v2":True})
        stage.rename(output)
    except Exception as error:
        write(stage/"incomplete-harvest.json",{"status":"failed","error":str(error),"output_not_published":True})
        raise RuntimeError(f"Collection failed; diagnostics retained at {stage}: {error}") from error
    return {"status":"published","output":str(output),"files":len(files)+1,"scientific_superiority_claim":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='Existing completed campaign root on this host')
    parser.add_argument('--output',type=Path,default=Path('outputs/orbit-smoothing-poc/runs/v3'))
    parser.add_argument('--expected-source',default=SOURCE_F2)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only',action='store_true',help='Read-only readiness check and planned outputs; never publishes')
    mode.add_argument('--collect',action='store_true',help='Explicitly collect only after complete results exist')
    args=parser.parse_args()
    root=args.source.resolve();output=args.output.resolve()
    if output==root or root in output.parents: parser.error('Publication must be outside the raw campaign tree')
    status=readiness(root,args.expected_source)
    if args.check_only:
        print(json.dumps({k:v for k,v in status.items() if k!='documents'} | {
            'mode':'check_only','output_writes':False,'destination':str(output),
            'planned_original_files':original_files(),'planned_derived_files':list(DERIVED),
            'planned_postprocessing_sources':list(POSTPROCESSING),
            'bulky_exclusions':['native source/builds','raw spacecraft/GPS/SLR data','native fit directories','trajectory/covariance arrays','per-epoch calibration covariance arrays']},indent=2))
        return 0 if status['ready'] else 2
    print(json.dumps(collect(root,output,status),indent=2))
    return 0


if __name__=='__main__': raise SystemExit(main())
