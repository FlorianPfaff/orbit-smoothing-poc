#!/usr/bin/env python3
"""One finite dependency stage for the already running candidate03 campaign.

No scheduler, estimator launch, retry, external publication or outcome ranking.
All writes are in the requested publication parent; campaign/source reads only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

SOURCE = "3b434b8c6d185187cc394795f901d082abd8fd2d38e6a7202feb0c52a105e33e"
PROTOCOL = "502db43a34ac769f29f087be2a0c8d7c8c73afb1769d1339162ff87a26c9ad9c"
NATIVE = "74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453"
COLLECTOR = "8765d404ecffa4f34359e0286ad3c0767676270db69caccfffba32ab01924834"
RENDERER = "8fe08102f6fbd6d77af5cb184e104d024a2b834cac0b27cc4a51b0684dcc6a10"
CAMPAIGNS = {"synthetic": 1600, "stress": 20, "flight": 24, "flight_ar_reference": 6}
GATES = ("external_baseline", "model_correctness", "pipeline_correctness", "numerical_accuracy")
FIGURES = ("primary-paired-rmse", "primary-fixed-epoch-coverage", "secondary-whole-arc-rmse")
MAX_ARTIFACT_BYTES = 95*1024*1024


def now(): return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha(path):
    with Path(path).open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path): return json.loads(Path(path).read_bytes())


def atomic_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix="."+path.name+"-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def inside(path, parent): return path == parent or parent in path.parents


def member(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative or not path.parts:
        raise ValueError("Unsafe relative artifact path: "+str(relative))
    current = root
    for part in path.parts:
        current = current/part
        if current.is_symlink(): raise ValueError("Symlinks are not allowed in a verified bundle/source")
    if not current.is_file(): raise ValueError("Missing artifact: "+str(current))
    return current


def json_artifact(bundle, name):
    candidates = [bundle/name, bundle/(name+".gz")]
    existing = [path for path in candidates if path.exists()]
    if len(existing) != 1: raise ValueError("Missing/ambiguous JSON artifact: "+name)
    path = member(bundle, str(existing[0].relative_to(bundle)))
    payload = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(payload), path, hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Settings:
    campaign: Path
    project: Path
    collector: Path
    output: Path
    python: str = sys.executable
    poll_seconds: float = 30
    max_wait_hours: float = 336

    @property
    def control(self): return self.output.parent/".v3-handoff-03"

    def validate_paths(self):
        if self.output.name != "v3" or self.output.is_symlink() or self.control.is_symlink():
            raise ValueError("Output must be a nonsymlink directory ending in /v3")
        for protected in (self.campaign, self.project, self.collector.parent):
            if inside(self.output, protected) or inside(protected, self.output) or inside(self.control, protected):
                raise ValueError("Publication and control files must be outside campaign/source/helper directories")
        if not 0 < self.poll_seconds <= 60 or not 0 < self.max_wait_hours <= 8760:
            raise ValueError("Polling must be at most 60 seconds; the finite wait limit must be at most one year")

    def binding(self):
        return {"campaign": str(self.campaign), "project": str(self.project), "collector": str(self.collector),
            "output": str(self.output), "source_sha256": SOURCE, "protocol_hash": PROTOCOL,
            "native_sha256": NATIVE, "collector_sha256": COLLECTOR, "renderer_sha256": RENDERER}


@contextmanager
def exclusive_lock(control):
    if control.is_symlink() or (control/"handoff.lock").is_symlink():
        raise ValueError("Handoff control/lock cannot be a symlink")
    control.mkdir(parents=True, exist_ok=True)
    with (control/"handoff.lock").open("a+") as stream:
        try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError("Another handoff/collector holds this destination lock")
        yield stream.fileno()


class Journal:
    def __init__(self, settings):
        self.settings = settings; self.path = settings.control/"status.json"
        self.previous = read(self.path) if self.path.exists() else None
        if self.previous and self.previous.get("binding") != settings.binding():
            raise ValueError("Existing handoff binding differs; existing status is preserved")
        self.sequence = max([int(p.stem.split("-", 1)[0]) for p in settings.control.glob("[0-9]*-*.json")] or [0])
        self.collection_started = bool(self.previous and self.previous.get("collection_started"))

    def record(self, status, phase, **details):
        self.sequence += 1
        result = {"schema_version": 1, "status": status, "phase": phase, "recorded_at_utc": now(),
            "pid": os.getpid(),
            "binding": self.settings.binding(), "collection_started": self.collection_started,
            "sequence": self.sequence, "helper_sha256": sha(__file__),
            "scientific_superiority_claim": False, "external_publication_performed": False,
            "estimators_launched": False, **details}
        atomic_json(self.settings.control/f"{self.sequence:06d}-{status}.json", result)
        atomic_json(self.path, result)
        return result


def verify_helpers(settings):
    if sha(settings.collector) != COLLECTOR or sha(settings.collector.with_name("render_v3_figures.py")) != RENDERER:
        raise ValueError("Collector/renderer bytes differ from reviewed publication-audit-03")


def verify_protocol(settings):
    path = settings.campaign/"protocol.json"; protocol = read(path)
    if (protocol.get("protocol_hash") != PROTOCOL or canonical({k:v for k,v in protocol.items() if k != "protocol_hash"}) != PROTOCOL
            or protocol.get("source", {}).get("sha256") != SOURCE
            or protocol.get("native_binary", {}).get("sha256") != NATIVE):
        raise ValueError("Existing campaign is not the exact accepted candidate03 protocol/source/native build")
    return protocol


def verify_upstream(settings, protocol):
    files = {}
    for directory in ("src", "scripts", "groops/extension", "groops/templates", "configs"):
        for path in sorted((settings.project/directory).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".cpp", ".h", ".hpp", ".sh", ".xml", ".json", ".yaml", ".yml", ".txt"}:
                name = str(path.relative_to(settings.project)); files[name] = sha(member(settings.project, name))
    for name in ("pyproject.toml", "tudat-linux-64.lock.txt", "groops/linux-64.lock.txt", "groops/python-requirements.lock.txt"):
        if (settings.project/name).is_file(): files[name] = sha(member(settings.project, name))
    if len(files) != 89 or files != protocol["source"]["files"] or canonical(files) != SOURCE:
        raise ValueError("Frozen 89-file runtime snapshot changed before publication")
    if sha(protocol["native_binary"]["path"]) != NATIVE:
        raise ValueError("Native executable changed before publication")
    return {"source_files_rehashed": len(files), "source_sha256": SOURCE, "native_sha256": NATIVE,
            "bulky_raw_input_inventory_rehashed": False}


def driver_status(settings):
    path = settings.campaign/"campaign-driver.json"
    if not path.exists(): return "waiting", None
    driver = read(path); status = driver.get("status")
    if status in ("failed", "blocked", "interrupted"): return "failed", driver
    if status == "running": return "waiting", driver
    if status != "complete": raise ValueError("Unknown campaign driver status: "+str(status))
    if [(row.get("stage"), row.get("status"), row.get("protocol_hash")) for row in driver.get("stages", [])] != [
            ("synthetic", "complete", PROTOCOL), ("flight", "complete", PROTOCOL)]:
        raise ValueError("Terminal driver does not complete both accepted stages")
    return "complete", driver


def run_logged(argv, control, label, lock_fd):
    """Inherited flock survives a parent crash until its sole collector exits."""
    stdout, stderr = control/(label+".stdout.json"), control/(label+".stderr.log")
    with stdout.open("xb") as out, stderr.open("xb") as err:
        child = subprocess.Popen(argv, stdout=out, stderr=err, pass_fds=(lock_fd,))
        try: code = child.wait()
        except BaseException:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
            raise
    return {"argv": argv, "returncode": code, "stdout": str(stdout), "stdout_sha256": sha(stdout),
        "stderr": str(stderr), "stderr_sha256": sha(stderr)}


def verify_design_and_failures(bundle):
    """Cross-check compact archived records; no raw outcome arrays or reanalysis."""
    def rows(name):
        with member(bundle,name).open() as stream: values=[json.loads(line) for line in stream if line.strip()]
        if not all(isinstance(row,dict) for row in values): raise ValueError("Non-object row in "+name)
        return values
    def identity(row): return (row['campaign'],canonical(row['case']),row['method'])
    def counts(values): return Counter(canonical(row) for row in values)
    metrics=rows('metrics.jsonl'); failures=rows('failures.jsonl'); scores=rows('calibration-scores.jsonl')
    protocol,_,_=json_artifact(bundle,'protocol.json')
    actual={identity(row):row for row in metrics}
    if len(metrics)!=1650 or len(actual)!=1650: raise ValueError("Metrics require exactly 1650 unique case/method rows")
    expected,expected_scores,expected_failures={},[],[]
    for stage in ('synthetic','flight'):
        calibration,_,_=json_artifact(bundle,f'calibration-{stage}.json')
        keys=('protocol_hash','selections','evidence','calibration_adequate','calibration_disclosures','boundary_diagnostics')
        if (calibration.get('complete') is not True or calibration.get('source_hash')!=SOURCE
                or calibration.get('protocol_hash')!=PROTOCOL or calibration.get('stage')!=stage
                or calibration.get('selection_hash')!=canonical({key:calibration[key] for key in keys})):
            raise ValueError("Archived calibration selection identity is invalid: "+stage)
        for row in calibration['runs']:
            score={'stage':stage,**row}; expected_scores.append(score)
            if not row.get('valid'):
                expected_failures.append({'phase':'calibration','failure_kind':'invalid_candidate_arc_holdout',**score})
        frozen,_,_=json_artifact(bundle,f'evaluation-input-freeze-{stage}.json')
        if (frozen.get('status')!='frozen' or frozen.get('stage')!=stage or frozen.get('source_hash')!=SOURCE
                or frozen.get('protocol_hash')!=PROTOCOL or frozen.get('selection_hash')!=calibration['selection_hash']
                or frozen.get('native_binary')!=protocol['native_binary']
                or frozen.get('input_freeze_hash')!=canonical({key:value for key,value in frozen.items() if key!='input_freeze_hash'})):
            raise ValueError("Archived evaluation input freeze identity is invalid: "+stage)
        campaigns=('synthetic','stress') if stage=='synthetic' else ('flight','flight_ar_reference')
        frozen_total=0
        for name in campaigns:
            kind='primary' if name in ('synthetic','flight') else name
            methods=('groops_pulses_ar',) if name=='flight_ar_reference' else ('groops_log_drag_ou','groops_pulses')
            run,_,_=json_artifact(bundle,f'run-{name}.json'); report,_,_=json_artifact(bundle,f'report-{name}/report.json')
            if (run.get('complete') is not True or run.get('status')!='complete' or run.get('source_hash')!=SOURCE
                    or run.get('protocol_hash')!=PROTOCOL or run.get('stage')!=stage or run.get('campaign')!=kind
                    or run.get('selection_hash')!=calibration['selection_hash'] or report.get('selection_hash')!=calibration['selection_hash']
                    or sorted(run.get('methods',[]))!=sorted(methods) or run.get('expected_fits')!=CAMPAIGNS[name]):
                raise ValueError("Archived run identity/methods are invalid: "+name)
            planned=[canonical(case) for case in run['planned_cases']]
            frozen_cases=[canonical(row['case']) for row in frozen['prepare_results'] if row['campaign']==kind]
            frozen_total+=len(planned)
            planned_keys={(name,case,method) for case in planned for method in methods}
            run_keys=[(name,canonical(row['case']),row['method']) for row in run['runs']]
            if (len(planned)!=len(set(planned)) or len(planned_keys)!=CAMPAIGNS[name] or len(run_keys)!=CAMPAIGNS[name]
                    or set(run_keys)!=planned_keys or sorted(frozen_cases)!=sorted(planned)
                    or frozen['campaign_case_counts'].get(kind)!=len(planned)):
                raise ValueError("Archived case/method rows differ from frozen inputs: "+name)
            for row,key in zip(run['runs'],run_keys): expected[key]=row
        if len(frozen['prepare_results'])!=frozen_total:
            raise ValueError("Unlisted or duplicated frozen input cases: "+stage)
    if set(actual)!=set(expected): raise ValueError("Metrics rows differ from archived frozen case/method design")
    for key,metric in actual.items():
        row=expected[key]
        valid=(metric.get('status')=='complete' and metric.get('converged') is True
            and metric.get('covariance_valid') is True and metric.get('evaluation_status')=='complete')
        if (metric.get('source_fit_record')!=row['fit_record'] or metric.get('source_evaluation_record')!=row.get('evaluation_record')
                or metric.get('status')!=row['fit_record']['status']
                or metric.get('evaluation_status')!=(row.get('evaluation_record') or {}).get('status','not_run')
                or metric.get('parameters')!=row.get('parameters') or valid!=(row.get('valid') is True)):
            raise ValueError("Metrics checkpoint/validity differs from archived fit record: "+str(key))
        if not valid:
            expected_failures.append({'phase':'evaluation','failure_kind':'invalid_or_unavailable_fit_or_evaluation',**metric})
    if counts(scores)!=counts(expected_scores): raise ValueError("Archived calibration-score rows are missing, duplicated or changed")
    if counts(failures)!=counts(expected_failures): raise ValueError("Archived failure rows are missing, duplicated or changed")
    summary,_,_=json_artifact(bundle,'summary.json')
    if summary.get('failure_counts')!=dict(Counter(row['phase'] for row in failures)):
        raise ValueError("Summary failure counts differ from retained failure rows")
    return {'verified_metric_rows':len(metrics),'verified_calibration_rows':len(scores),'verified_failure_rows':len(failures)}


def verify_bundle(bundle, *, protocol_bytes=None, driver_bytes=None):
    """Verify exact archive members and gzip payloads; do not rank scientific results."""
    bundle = Path(bundle)
    manifest_path = member(bundle, "publication.json"); manifest = read(manifest_path)
    files = manifest.get("files", {})
    if (not files or manifest.get("bundle_content_hash") != canonical(files)
            or manifest.get("protocol_hash") != PROTOCOL or manifest.get("collector_sha256") != COLLECTOR):
        raise ValueError("Publication manifest identity or canonical content hash is invalid")
    actual = {str(path.relative_to(bundle)) for path in bundle.rglob("*") if path.is_file() or path.is_symlink()}
    if actual != set(files) | {"publication.json"}: raise ValueError("Publication contains missing or unlisted files")
    if any(member(bundle,name).stat().st_size>MAX_ARTIFACT_BYTES for name in actual):
        raise ValueError("Publication artifact exceeds the 95 MiB cap")
    if any("fixture-" in Path(name).name for name in files): raise ValueError("Fictional fixture output cannot enter the bundle")
    for name, expected in files.items():
        if sha(member(bundle, name)) != expected: raise ValueError("Publication file hash mismatch: "+name)
    originals = ["protocol.json", "acceptance-gates.json", "campaign-driver.json", "driver-synthetic.json", "driver-flight.json"]
    for stage in ("synthetic", "flight"):
        originals += [f"calibration-{stage}.json", f"calibration-input-preparation-{stage}.json", f"evaluation-input-freeze-{stage}.json"]
    for campaign in CAMPAIGNS: originals += [f"run-{campaign}.json", f"report-{campaign}/report.json"]
    for name in originals: json_artifact(bundle, name)
    for name in ("index.html", "metrics.jsonl", "calibration-scores.jsonl", "failures.jsonl", "raw-artifact-locators.jsonl"):
        member(bundle, name)
    summary, _, _ = json_artifact(bundle, "summary.json")
    protocol, _, protocol_payload = json_artifact(bundle, "protocol.json")
    driver, _, driver_payload = json_artifact(bundle, "campaign-driver.json")
    if (summary.get("source_hash") != SOURCE or summary.get("protocol_hash") != PROTOCOL
            or summary.get("native_binary_sha256") != NATIVE or summary.get("execution_complete") is not True
            or summary.get("superiority_claim_issued") is not False
            or protocol.get("source", {}).get("sha256") != SOURCE or protocol.get("native_binary", {}).get("sha256") != NATIVE
            or protocol.get("protocol_hash") != PROTOCOL or canonical({k:v for k,v in protocol.items() if k != "protocol_hash"}) != PROTOCOL
            or driver.get("status") != "complete"
            or [(row.get("stage"),row.get("status"),row.get("protocol_hash")) for row in driver.get("stages",[])] != [
                ("synthetic","complete",PROTOCOL),("flight","complete",PROTOCOL)]):
        raise ValueError("Bundle protocol/source/native/completion identity is inconsistent")
    if protocol_bytes is not None and protocol_payload != protocol_bytes: raise ValueError("Copied protocol differs from waiting campaign")
    if driver_bytes is not None and driver_payload != driver_bytes: raise ValueError("Copied terminal driver differs from waiting campaign")
    for name, count in CAMPAIGNS.items():
        report, _, _ = json_artifact(bundle, f"report-{name}/report.json")
        if (report.get("source_hash") != SOURCE or report.get("protocol_hash") != PROTOCOL
                or report.get("orchestration_complete") is not True or report.get("planned_design_complete") is not True
                or any(report.get(key) != count for key in ("expected_fits", "observed_fits", "planned_fit_rows"))
                or report.get("missing_planned_fits") != 0 or report.get("metrics_error")):
            raise ValueError("Publication report does not retain all frozen fits: "+name)
        member(bundle, f"report-{name}/index.html")
    gates, _, _ = json_artifact(bundle, "acceptance-gates.json")
    if (gates.get("protocol_hash") != PROTOCOL or gates.get("evidence_hash") != canonical({k:v for k,v in gates.items() if k != "evidence_hash"})
            or not all(gates.get("gates", {}).get(name, {}).get("passed") is True for name in GATES)):
        raise ValueError("Archived acceptance evidence is inconsistent")
    inventory, _, _ = json_artifact(bundle, "file-inventory.json")
    entries = inventory.get("original_files", [])
    if not entries or len(entries) != manifest.get("collected_original_files"):
        raise ValueError("Missing/inconsistent original-byte inventory")
    for entry in entries:
        if entry["published_path"] not in files: raise ValueError("Unlisted original-byte inventory member")
        path = member(bundle, entry["published_path"])
        if sha(path) != entry["published_sha256"] or path.stat().st_size != entry["published_bytes"]:
            raise ValueError("Original-byte inventory container changed")
        payload = path.read_bytes()
        if entry["encoding"] == "gzip_original_bytes": payload = gzip.decompress(payload)
        elif entry["encoding"] != "original_bytes": raise ValueError("Unknown original-byte encoding")
        if hashlib.sha256(payload).hexdigest() != entry["source_sha256"] or len(payload) != entry["source_bytes"]:
            raise ValueError("Archived original payload changed")
    figure_manifest, _, _ = json_artifact(bundle, "figures/figure-manifest.json")
    expected_figures = {f"{stem}.{extension}" for stem in FIGURES for extension in ("png", "svg")}
    if (figure_manifest.get("fictional_fixture") is not False or figure_manifest.get("renderer_sha256") != RENDERER
            or figure_manifest.get("source_hash") != SOURCE or figure_manifest.get("protocol_hash") != PROTOCOL
            or figure_manifest.get("statistics_recomputed") is not False or len(figure_manifest.get("figures", [])) != 6
            or {item["path"] for item in figure_manifest.get("figures", [])} != expected_figures):
        raise ValueError("Fixed figure manifest identity is invalid or fictional")
    for item in figure_manifest["figures"]:
        if sha(member(bundle/"figures", item["path"])) != item["sha256"]: raise ValueError("Figure hash mismatch")
    expected_inputs = {"summary.json", "report-synthetic/report.json"}
    actual_inputs = set()
    for item in figure_manifest.get("inputs", []):
        path = member(bundle, item["path"])
        raw = path.read_bytes(); payload = gzip.decompress(raw) if path.suffix == ".gz" else raw
        if hashlib.sha256(raw).hexdigest() != item["sha256"] or hashlib.sha256(payload).hexdigest() != item["uncompressed_payload_sha256"]:
            raise ValueError("Figure input hash mismatch")
        actual_inputs.add(item["path"].removesuffix(".gz"))
    if actual_inputs != expected_inputs or len(figure_manifest.get("inputs", [])) != 2:
        raise ValueError("Fixed figure input list is incomplete/duplicated")
    if sha(member(bundle, "postprocessing/harvest_v3.py")) != COLLECTOR or sha(member(bundle, "postprocessing/render_v3_figures.py")) != RENDERER:
        raise ValueError("Archived postprocessing sources are not the reviewed pair")
    design=verify_design_and_failures(bundle)
    return {"publication_sha256": sha(manifest_path), "bundle_content_hash": manifest["bundle_content_hash"],
        "verified_files": len(files), "verified_original_payloads": len(entries), "verified_figures": 6,
        "expected_evaluation_fits": 1650, "bulky_raw_input_inventory_rehashed": False, **design}


def handoff(settings, *, sleeper=time.sleep, monotonic=time.monotonic):
    settings.validate_paths()
    with exclusive_lock(settings.control) as lock_fd:
        journal = Journal(settings); phase = "initializing"
        if journal.previous and journal.previous.get("status") == "blocked": return journal.previous
        try:
            verify_helpers(settings); protocol = verify_protocol(settings)
            if journal.collection_started and not settings.output.exists():
                return journal.record("blocked", "interrupted_collection", reason="A collection was already attempted without a terminal bundle; no automatic retry", retained_staging=[str(p) for p in sorted(settings.output.parent.glob('.v3-harvest-*'))])
            phase = "waiting"; journal.record("waiting", phase, max_wait_hours=settings.max_wait_hours, poll_seconds=settings.poll_seconds)
            deadline = monotonic()+settings.max_wait_hours*3600
            while True:
                state, driver = driver_status(settings)
                if state == "failed":
                    return journal.record("blocked", "campaign_failed", reason="Existing campaign terminated without completing both stages; no retries", driver=driver, driver_sha256=sha(settings.campaign/"campaign-driver.json"))
                if state == "complete": break
                remaining = deadline-monotonic()
                if remaining <= 0: return journal.record("blocked", "wait_limit", reason="Finite wait deadline elapsed; campaign left untouched")
                sleeper(min(settings.poll_seconds, remaining))
            protocol_bytes = sha(settings.campaign/"protocol.json"); driver_bytes = sha(settings.campaign/"campaign-driver.json")
            phase = "verifying_upstream"; upstream = verify_upstream(settings, protocol)
            if settings.output.exists():
                phase = "verifying_existing_bundle"
                verified = verify_bundle(settings.output, protocol_bytes=protocol_bytes, driver_bytes=driver_bytes)
                if (journal.previous and journal.previous.get("status") == "complete"
                        and verified["publication_sha256"] != journal.previous["verification"]["publication_sha256"]):
                    raise ValueError("Previously completed bundle manifest changed")
                verify_upstream(settings, verify_protocol(settings)); verify_helpers(settings)
                return journal.record("complete", phase, verification=verified, upstream=upstream, reused_existing_bundle=True)
            base = [settings.python, str(settings.collector), "--source", str(settings.campaign), "--output", str(settings.output), "--expected-source", SOURCE]
            phase = "checking_readiness"; journal.record("running", phase, upstream=upstream)
            checked = run_logged(base+["--check-only"], settings.control, f"{journal.sequence:06d}-check", lock_fd)
            verify_helpers(settings)
            if checked["returncode"]: return journal.record("blocked", phase, command=checked, reason="Collector readiness failed; no collection or retries")
            check = read(checked["stdout"])
            if check.get("ready") is not True or check.get("protocol_hash") != PROTOCOL or check.get("expected_source") != SOURCE or check.get("expected_evaluation_fits") != 1650:
                raise ValueError("Collector readiness response has an inconsistent identity/count")
            phase = "collecting"; journal.collection_started = True
            journal.record("running", phase, readiness_command=checked, upstream=upstream)
            collected = run_logged(base+["--collect"], settings.control, f"{journal.sequence:06d}-collect", lock_fd)
            verify_helpers(settings)
            if collected["returncode"]: return journal.record("blocked", phase, command=collected, reason="Collector failed; no retries", retained_staging=[str(p) for p in sorted(settings.output.parent.glob('.v3-harvest-*'))])
            phase = "verifying_new_bundle"
            verified = verify_bundle(settings.output, protocol_bytes=protocol_bytes, driver_bytes=driver_bytes)
            verify_upstream(settings, verify_protocol(settings)); verify_helpers(settings)
            return journal.record("complete", phase, verification=verified, upstream=upstream,
                readiness_command=checked, collection_command=collected, reused_existing_bundle=False)
        except (KeyboardInterrupt, SystemExit) as error:
            return journal.record("interrupted", phase, reason=f"{type(error).__name__}: finite handoff interrupted; diagnostics retained")
        except Exception as error:
            return journal.record("blocked", phase, reason=f"{type(error).__name__}: {error}", retained_staging=[str(p) for p in sorted(settings.output.parent.glob('.v3-harvest-*'))])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("campaign", "project", "collector", "output"): parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--max-wait-hours", type=float, default=336)
    args = parser.parse_args()
    if args.output.is_symlink(): parser.error("Output cannot be a symlink")
    settings = Settings(**{**vars(args), **{name:getattr(args,name).resolve() for name in ("campaign","project","collector","output")}})
    def interrupted(signum, frame): raise KeyboardInterrupt("signal "+str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    try: result = handoff(settings)
    except Exception as error:
        print(json.dumps({"status":"not_started", "reason":f"{type(error).__name__}: {error}", "existing_records_preserved":True}), file=sys.stderr); return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "complete" else 130 if result["status"] == "interrupted" else 2


if __name__ == "__main__": raise SystemExit(main())
