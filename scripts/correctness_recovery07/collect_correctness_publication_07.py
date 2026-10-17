#!/usr/bin/env python3
"""Collect closed numerical receipts into a NEW compact publication directory.

Never executes estimators, changes source, writes Git, or upgrades gate status.
The output is a sanitized evidence bundle, not byte-identical original receipts;
the manifest preserves both original and published hashes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

MAX_FILE = 16*1024*1024
MAX_TOTAL = 64*1024*1024
METHODS = ('log_drag_ou', 'pulses')
REPLAYS = ('nuisance-replay','nuisance-replay-candidate1-point012')
SCOPED = ('synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses',
          'flight-refinement', 'eccentric-24h-refinement')
SCOPE = ('Compact numerical engineering evidence only. No full 150-attempt '
         'benchmark completion, scientific accuracy, accepted covariance, or '
         'release claim is inferred. Earlier failures and missing receipts remain explicit.')


def require(value, message):
    if not value: raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def finite(value):
    value = float(value)
    require(math.isfinite(value), 'Nonfinite JSON number')
    return value


def read(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= MAX_FILE, 'Missing/oversized compact receipt: '+str(path))
    raw = path.read_bytes()
    require(len(raw) <= MAX_FILE, 'Receipt grew beyond compact limit')
    return raw


def decode(raw):
    value = json.loads(raw, object_pairs_hook=pairs, parse_float=finite,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
    require(isinstance(value, dict), 'Receipt is not a JSON object')
    return value


def path_token(value):
    return 'private-path-sha256:'+sha(value.encode())


def scrub(value):
    if isinstance(value, dict): return {scrub(k): scrub(v) for k,v in value.items()}
    if isinstance(value, list): return [scrub(v) for v in value]
    if not isinstance(value, str): return value
    # A leading file path can introduce a diagnostic rather than constitute the
    # whole value. Preserve its numerical/error suffix (including new lines).
    leading=re.match(r'^(?:/(?!/)|[A-Za-z]:[\\/]).*?(?=:\s|\r?\n)',value,re.DOTALL)
    if leading:
        return path_token(leading[0])+scrub(value[len(leading[0]):])
    if value.startswith('/') or re.match(r'^[A-Za-z]:[\\/]', value):
        return path_token(value)
    value=re.sub(r'''(?<![A-Za-z0-9_])(-[IL])((?:/(?!/)|[A-Za-z]:[\\/])[^\s<>"'&]+)''',
        lambda m:m[1]+path_token(m[2]),value)
    # Quoted paths may contain spaces; preserve the surrounding error text.
    value=re.sub(r'''(["'])(/(?!/)[^"']+|[A-Za-z]:[\\/][^"']+)\1''',
        lambda m: m[1]+path_token(m[2])+m[1],value)
    return re.sub(r'''(?<![A-Za-z0-9_:/])(?:[A-Za-z]:[\\/][^\s<>"'&]+|/(?!/)[^\s<>"'&]+)''',
        lambda m: path_token(m[0]),value)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def confined(path, root):
    path = Path(path).resolve()
    require(path.is_relative_to(root.resolve()), 'Evidence path escapes selected root')
    return path


def final_generation(folder, kind):
    matches = []
    for path in folder.glob('qr.*.'+kind+'.json'):
        match = re.fullmatch(r'qr\.(\d+)\.'+re.escape(kind)+r'\.json', path.name)
        if match: matches.append((int(match[1]),path))
    return max(matches)[1] if matches else None


def load_renderer(control):
    path = control/'render_correctness_report_07.py'
    spec = importlib.util.spec_from_file_location('publication_renderer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def collect(root, previous, audit_path, report, output, *, run=None, control=None, source=None, binaries=None):
    root, previous, audit_path, report, output = map(lambda p: Path(p).absolute(), (root,previous,audit_path,report,output))
    run=Path(run or root/'validation-07').absolute();control=Path(control or root/'control').absolute()
    renderer,renderer_path=load_renderer(control)
    recovery=renderer.load_recovery_helper()
    extra_paths=set()
    scopes=[run,control,previous,report]
    def safe(path):
        path=Path(path).absolute()
        for scope in scopes:
            if path.is_relative_to(scope):
                confined(path,scope)
                return path
        if path==audit_path or path in extra_paths:
            return path
        raise ValueError('Receipt outside allowlisted roots')
    def raw_read(path): return read(safe(path))
    require(not output.exists() and not output.is_symlink(), 'Output must be a NEW directory')
    pipeline_raw=raw_read(run/'pipeline.json');pipeline=decode(pipeline_raw)
    require(pipeline.get('status') in ('passed','failed') and pipeline.get('finished_at'),'Validation07 is not closed')
    require(pipeline.get('final_cleanup',{}).get('verified') is True,'Owned-workload cleanup incomplete')
    pinpath=control/'candidate07-pins.json'
    pins_raw=raw_read(pinpath);pins=decode(pins_raw)
    required=pipeline.get('required_pins') or {}
    require(required.get('path')==str(pinpath) and required.get('sha256')==sha(pins_raw)
            and required.get('bytes',len(pins_raw))==len(pins_raw),'Required source/input/control freeze changed')
    recovery_paths={}
    def read_pin(pin,role):
        path=Path(pin['path']).absolute();extra_paths.add(path)
        raw=raw_read(path);require(sha(raw)==pin['sha256'],'Recovery provenance pin changed: '+role)
        recovery_paths[role]=path
        return decode(raw)
    proof=recovery.validate_recovery(pipeline,pins,read_pin)
    execution=proof['execution'];paths=execution['paths']
    require(Path(paths['root']).resolve()==root.resolve() and Path(paths['run']).resolve()==run.resolve()
            and Path(paths['control']).resolve()==control.resolve(),'Collector layout differs from admitted execution')
    source=Path(source or paths['source']).absolute();binaries=Path(binaries or paths['binaries']).absolute()
    require(source.resolve()==Path(paths['source']).resolve() and binaries.resolve()==Path(paths['binaries']).resolve(),'Collector source/build override differs from execution')
    scopes.append(binaries)
    for protected in (root/'source',root/'source-02',source,run,control,binaries,previous,report):
        require(not output.resolve().is_relative_to(protected.resolve()),'Collector cannot write inside an input root')
    # Historical scientific failure is distinct from the interrupted03 build.
    prior_pin=pipeline.get('prior_failed_validation') or {}
    frozen_prior=pins.get('input_artifacts',{}).get('prior_validation') or {}
    require(prior_pin.get('sha256')==frozen_prior.get('sha256')
            and recovery.host_path(prior_pin.get('path',''),execution).resolve()==recovery.host_path(frozen_prior.get('path',''),execution).resolve(),
            'Previous scientific-failure pin differs')
    prior_path=recovery.host_path(prior_pin['path'],execution).absolute();extra_paths.add(prior_path)
    prior_raw=raw_read(prior_path);prior=decode(prior_raw)
    require(sha(prior_raw)==prior_pin['sha256'],'Preserved validation02 pin changed')
    reuse=prior.get('reused_build') or {};first_pin=reuse.get('prior_pipeline') or {}
    first_path=recovery.host_path(first_pin.get('path',''),execution).absolute();extra_paths.add(first_path)
    first_raw=raw_read(first_path);first=decode(first_raw)
    require(first_pin.get('sha256')==sha(first_raw),'Historical validation02 does not bind validation01')
    history={'01':first_path,'02':prior_path,'03':recovery_paths['interrupted_pipeline03']}
    history.update({'04':recovery_paths['failed_pipeline04'],'05':recovery_paths['failed_pipeline05'],'06':recovery_paths['failed_pipeline06']})
    for suffix,old in (('01',first),('02',prior)):
        require(old.get('status')=='failed' and old.get('final_cleanup',{}).get('verified') is True
                and old.get('resume',{}).get('status')=='resumed' and not old.get('resume_error') and not old.get('resume_withheld'),
                'Prior scientific/infrastructure failure did not close cleanly')
    prior_builds=[v for v in first.get('steps',[]) if isinstance(v,dict) and v.get('name')=='build']
    require(len(prior_builds)==1 and prior_builds[0].get('status')=='passed' and prior_builds[0].get('returncode')==0,'Historical successful build is not unique')
    require(first.get('source')==prior.get('source') and first.get('native')==prior.get('native')
            and reuse.get('native')==prior.get('native') and reuse.get('source_sha256')==prior.get('source',{}).get('sha256')
            and reuse.get('build_step')==prior_builds[0],'Historical reused source/build identities disagree')
    builds=[v for v in pipeline.get('steps',[]) if isinstance(v,dict) and v.get('name')=='build']
    native=pipeline.get('native') or {}
    if native or pipeline.get('status')=='passed':
        require(len(builds)==1 and builds[0].get('status')=='passed' and builds[0].get('returncode')==0,'Fresh candidate build is not uniquely successful')
    else:
        require(len(builds)<=1 and pipeline.get('status')=='failed','Incomplete build cannot establish native acceptance')
    require(not pipeline.get('reused_build'),'Validation07 must use its separate fresh build')
    for filename,key in (('validate_candidate_07.py','driver_sha256'),('with_correctness_namespace_04.py','wrapper_sha256')):
        require(sha(raw_read(control/filename))==pins.get(key),'Control freeze changed: '+filename)
    require(pipeline.get('helper_sha256')==pins['driver_sha256'] and pipeline.get('wrapper',{}).get('sha256')==pins['wrapper_sha256'],'Executed control identity differs from freeze')
    for path in history.values():
        scopes.append(path.parent)
        require(not output.resolve().is_relative_to(path.parent.resolve()),'Collector cannot write inside historical input root')
    audit_raw = raw_read(audit_path); audit = decode(audit_raw)
    require(audit.get('schema') == 'orbit-poc-correctness-independent-audit07-v1'
        and type(audit.get('passed')) is bool, 'Independent audit is absent/invalid')
    summary_raw = raw_read(report/'summary.json'); summary = decode(summary_raw)
    html_raw = raw_read(report/'index.html')
    require(summary.get('schema') == 'orbit-correction-evidence-report07-v1', 'Unexpected report schema')
    require(summary.get('pipeline',{}).get('evidence',{}).get('sha256') == sha(pipeline_raw), 'Report pipeline is stale')
    require(summary.get('independent_audit',{}).get('evidence',{}).get('sha256') == sha(audit_raw), 'Report audit is stale')
    require(summary.get('pipeline',{}).get('status') == pipeline['status'], 'Report changes pipeline status')
    require(summary.get('independent_audit',{}).get('record') == audit, 'Report changes audit outcome')
    safe(control/'render_correctness_report_07.py')
    renderer, renderer_path = load_renderer(control)
    require(summary.get('renderer_sha256') == sha(raw_read(renderer_path)), 'Renderer identity changed')
    # Constrain every fixed receipt before the renderer can inspect it.
    for name in SCOPED: safe(run/name/'result.json')
    for method in METHODS:
        safe(run/('objective-'+method)/'validation.json')
        safe(previous/(method+'-staged')/'validation.json')
    safe(run/'native-tests.xml')
    for replay in REPLAYS: safe(run/replay/'receipt.json')
    fresh_summary=renderer.collect(run,previous,control,audit_path)
    fresh_summary['created_at']=summary.get('created_at')
    require(fresh_summary == summary, 'Report no longer matches complete current receipts')
    require(renderer.document(summary).encode() == html_raw, 'HTML does not match the complete report summary')
    artifact_map={};dependency_records=[];dependency_originals={};dependency_states={}
    allowed_sources={'independent_verifier_source':control/'verify_correctness_results_07.py',
        'recovery_verifier_source':control/'recovery_evidence_07.py',
        'backend_validator_source':source/'src/orbit_poc/numerics/backend.py'}
    allowed_replay_sources={
        'prescribed_replay_profile_nuisance-replay':recovery.host_path(pins['input_artifacts']['old_nuisance_replay']['path'],execution).resolve(),
        'prescribed_replay_profile_nuisance-replay-candidate1-point012':recovery.host_path(pins['input_artifacts']['candidate1_nuisance_replay']['path'],execution).resolve()}
    for role in ('old_replay_variational','old_replay_reference','old_replay_density','new_replay_variational','new_replay_reference','new_replay_density'):
        allowed_replay_sources['prescribed_replay_input_'+role]=recovery.host_path(pins['input_artifacts'][role]['path'],execution).resolve()
    allowed_provenance={**recovery_paths,'candidate07_pins':pinpath}
    for pin in audit.get('input_artifacts',[]):
        require(isinstance(pin,dict) and isinstance(pin.get('path'),str)
            and pin.get('status') in ('available','missing','invalid'), 'Invalid audit dependency pin')
        path=Path(pin['path']).absolute();role=pin.get('role');is_source=role in allowed_sources or role in allowed_replay_sources
        if role in allowed_replay_sources:
            require(path.resolve()==allowed_replay_sources[role], 'Unexpected prescribed replay source dependency')
        elif role in allowed_provenance:
            require(path.resolve()==allowed_provenance[role].resolve(),'Unexpected recovery pin dependency')
            safe(path)
        elif is_source:
            require(path == allowed_sources[role], 'Unexpected audited source dependency')
            confined(path,source if role=='backend_validator_source' else control)
        else:
            require(path.is_relative_to(run), 'Numerical audit dependency escapes selected run')
            safe(path)
        key=str(path.resolve())
        if key in artifact_map:
            require(all(artifact_map[key].get(k)==pin.get(k) for k in ('status','sha256','bytes')), 'Conflicting duplicate audit pins')
        artifact_map[key]=pin
        raw=None;status='missing';parse_error=None
        if path.is_file():
            raw=read(path)
            dependency_originals[path]=sha(raw)
            status='available'
            if not is_source:
                try: decode(raw)
                except (ValueError,UnicodeError) as error: status='invalid';parse_error=type(error).__name__
        require(status == pin['status'], 'Audited dependency status changed: '+str(path))
        dependency_states[path]=status
        if raw is not None:
            require(pin.get('sha256') == sha(raw), 'Audited dependency hash changed: '+str(path))
            if 'bytes' in pin: require(pin['bytes']==len(raw), 'Audited dependency byte count changed')
        dependency_records.append({'source_path':path_token(str(path)),'role':role,'status':status,
            'sha256':sha(raw) if raw is not None else None,'bytes':len(raw) if raw is not None else None,'parse_error':parse_error})
    require(artifact_map.get(str((run/'pipeline.json').resolve()),{}).get('sha256') == sha(pipeline_raw), 'Audit does not pin final pipeline')
    # Closed failed audits are publishable; absence/failure is never converted
    # into a pass. Existing selected receipts must still match report identities.
    report_receipts = [(summary.get('objectives',{}).get(m,{}), run/('objective-'+m)/'validation.json') for m in METHODS]
    report_receipts += [(summary.get('synthetic_refinement',{}).get(m,{}),run/('synthetic-refinement-'+m)/'result.json') for m in METHODS]
    report_receipts += [(summary.get('additional_refinement',{}).get(key,{}),run/name/'result.json') for key,name in (('density_24h','eccentric-24h-refinement'),('flight_april24','flight-refinement'))]
    report_receipts += [(summary.get('nuisance_replays',{}).get(name,{}),run/name/'receipt.json') for name in REPLAYS]
    report_receipts += [(summary.get('native_tests',{}),run/'native-tests.xml')]
    report_receipts += [(summary.get('correction_regression_tests',{}),run/'correction-regression-tests.xml')]
    for item,path in report_receipts:
        pin = item.get('evidence',{})
        require(pin.get('sha256') == (sha(raw_read(path)) if path.is_file() else None), 'Report receipt changed: '+path.name)
        require(pin.get('status') != 'missing' if path.is_file() else pin.get('status') == 'missing', 'Report missing status changed')
    files, records, missing, originals = {}, [], [], dict(dependency_originals)
    def add(path, destination, *, required=False, xml=False):
        path = Path(path)
        safe(path)
        if not path.is_file():
            require(not required, 'Required compact receipt absent: '+str(path))
            pin=artifact_map.get(str(path.resolve()))
            missing.append({'destination':destination,'status':'missing','source_path':path_token(str(path)),
                'independent_audit_coverage':'pinned_dependency' if pin else 'not_in_audit_inventory'}); return
        require(destination not in files, 'Duplicate publication destination')
        raw = raw_read(path); originals[path] = sha(raw)
        pin=artifact_map.get(str(path.resolve()))
        if pin: require(pin.get('sha256')==sha(raw), 'Copied receipt differs from audit dependency')
        publication_status='available'
        if xml:
            try:
                require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'JUnit entities forbidden')
                tree = ET.fromstring(raw)
                require(tree.tag in ('testsuite','testsuites'),'Unexpected JUnit root')
                for parent in tree.iter():
                    for child in list(parent):
                        if child.tag in ('system-out','system-err'): parent.remove(child)
                    parent.attrib = {k:scrub(v) for k,v in parent.attrib.items()}
                    if parent.text: parent.text = scrub(parent.text)
                    if parent.tail: parent.tail = scrub(parent.tail)
            except (ValueError,UnicodeError,ET.ParseError) as error:
                require(not required,'Required provenance XML is invalid')
                publication_status='invalid'
                tree=ET.Element('invalidReceipt',{'publication_receipt_status':'invalid',
                    'original_sha256':sha(raw),'original_bytes':str(len(raw)),
                    'parse_error_type':type(error).__name__})
                tree.text='Malformed terminal JUnit retained as invalid evidence; original contents not published. This is not a test-result document.'
            published = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
        else:
            try: published = encoded(scrub(decode(raw)))
            except (ValueError,UnicodeError) as error:
                require(not required,'Required provenance JSON is invalid')
                publication_status='invalid'
                published=encoded({'publication_receipt_status':'invalid','original_sha256':sha(raw),'original_bytes':len(raw),
                    'parse_error_type':type(error).__name__,'scope':'Malformed terminal metadata retained as an explicit failure; original contents not published.'})
        require(len(published) <= MAX_FILE, 'Sanitized receipt too large')
        files[destination] = published
        records.append({'destination':destination,'original_sha256':sha(raw),'original_bytes':len(raw),
            'published_sha256':sha(published),'published_bytes':len(published),
            'publication_status':publication_status,'independent_audit_coverage':'pinned_dependency' if pin else 'not_in_audit_inventory',
            'transformation':('invalid original receipt represented by hash-only descriptor' if publication_status=='invalid'
                else 'absolute paths tokenized; JUnit stdout/stderr omitted' if xml else 'canonical JSON; absolute paths tokenized')})
    add(run/'pipeline.json','provenance/pipeline-07.json',required=True)
    for suffix,path in history.items():
        add(path,'historical/pipeline-'+suffix+'.json',required=True)
        if suffix!='03':add(path.parent/'native-tests.xml','historical/native-tests-'+suffix+'.xml',xml=True)
    for method in METHODS:
        add(prior_path.parent/('objective-'+method)/'validation.json','historical/validation02-objective-'+method+'.json')
    add(prior_path.parent/'nuisance-replay/receipt.json','historical/validation02-nuisance-replay.json')
    add(run/'native-tests.xml','native-tests.xml',xml=True)
    add(run/'correction-regression-tests.xml','correction-regression-tests.xml',xml=True)
    for name in ('candidate07-pins.json','candidate07-control-validation.json','candidate07-independent-control-review.json'):
        add(control/name,'provenance/'+name,required=True)
    for role,path in recovery_paths.items():
        add(path,'provenance/'+role+'.json',required=True)
    if native:
        manifest=binaries/(Path(native['path']).name+'.build-manifest.json')
        require(sha(raw_read(manifest))==native['build_manifest_sha256'],'Build manifest pin changed')
        require(decode(raw_read(manifest)).get('executable_sha256')==native['sha256'],'Build/binary identity disagrees')
        add(manifest,'provenance/build-manifest.json',required=True)
    else:
        missing.append({'destination':'provenance/build-manifest.json','status':'not_produced','reason':'No native executable identity recorded before terminal infrastructure failure'})
    for name in SCOPED: add(run/name/'result.json','refinements/'+name+'.json')
    for method in METHODS:
        folder = run/('objective-'+method)
        add(folder/'validation.json','objectives/'+method+'/validation.json')
        add(folder/'source.json','objectives/'+method+'/source.json')
        add(previous/(method+'-staged')/'validation.json','historical/objective-'+method+'.json',required=True)
        # Explicit, shallow allowlist includes partially failed endpoint folders
        # absent from the harness's completed-profile list. Never recurse into
        # native/, closure grids, datasets, proposals, logs, or row spools.
        for point in sorted(folder.glob('point-*')):
            require(point.is_dir() and re.fullmatch(r'point-\d+-[A-Za-z0-9_.-]+',point.name), 'Unexpected endpoint name')
            confined(point,folder)
            dest='objectives/'+method+'/'+point.name+'/'
            for name in ('qr.profile.json','closure.json','profile.execution.json'):
                candidate = point/name; confined(candidate,folder); add(candidate,dest+name)
            for kind in ('factor','nuisance_line_search'):
                selected = final_generation(point,kind)
                if selected:
                    confined(selected,folder); add(selected,dest+selected.name)
                    if kind == 'factor':
                        cost = Path(str(selected).replace('.factor.json','.profile.json'))
                        confined(cost,folder); add(cost,dest+cost.name)
    for replay in REPLAYS:
        for name in ('receipt.json','qr.profile.json'):
            add(run/replay/name,replay+'/'+name)
        for kind in ('factor','nuisance_line_search'):
            selected = final_generation(run/replay,kind)
            if selected:
                confined(selected,run); add(selected,replay+'/'+selected.name)
                if kind == 'factor':
                    cost = Path(str(selected).replace('.factor.json','.profile.json'))
                    confined(cost,run); add(cost,replay+'/'+cost.name)
    add(audit_path,'independent-audit.json',required=True)
    add(report/'summary.json','summary.json',required=True)
    files['index.html'] = renderer.document(scrub(summary)).encode()
    originals[report/'index.html'] = sha(html_raw)
    records.append({'destination':'index.html','original_sha256':sha(html_raw),'original_bytes':len(html_raw),
        'published_sha256':sha(files['index.html']),'published_bytes':len(files['index.html']),
        'transformation':'same renderer and complete sanitized summary; self-contained HTML'})
    manifest_record = {'schema':'orbit-poc-correctness-publication-bundle07-v1',
        'created_at':datetime.now(timezone.utc).isoformat(),'scope':SCOPE,
        'reported_pipeline_status':pipeline['status'],'reported_audit_passed':audit['passed'],
        'reported_evidence_status':summary.get('candidate_evidence_status'),
        'reported_nuisance_replays':{name:summary.get('nuisance_replays',{}).get(name,{}).get('status','missing') for name in REPLAYS},
        'release_acceptance':'not_assessed','frozen_campaign_reclassified':False,
        'prior_attempt03_classification':'interrupted_before_native_validation','campaign_resume':'not_applicable',
        'execution_host':execution['host'],
        'collector_sha256':sha(read(Path(__file__))), 'renderer_sha256':sha(read(renderer_path)),
        'native_sha256':native.get('sha256'),'source_inventory_sha256':pipeline.get('source',{}).get('sha256'),
        'files':records,'missing_receipts':missing,
        'verified_independent_audit_dependencies':dependency_records,
        'audit_coverage_policy':'Only explicitly pinned dependency bytes are tied to the independent audit. Other copied receipts are labelled not_in_audit_inventory and do not inherit audit success. Source/build/control pins are separate provenance checks.',
        'omitted_by_design':['raw datasets','binary executables','row spools','trajectory arrays','raw logs','private files referenced by receipts'],
        'privacy':'Absolute local paths replaced by stable SHA256 tokens; original byte hashes remain. This bundle is not a raw-receipt copy.'}
    files['manifest.json'] = encoded(manifest_record)
    files['README.txt'] = (SCOPE+'\n\nOpen index.html. All reported statuses are copied, not promoted. '
        'manifest.json records original and published hashes. Historical failures are retained. '
        'Local paths are tokenized; bulky/private referenced files are not included.\n').encode()
    require(sum(map(len,files.values())) <= MAX_TOTAL, 'Bundle exceeds compact total limit')
    for path, expected in originals.items(): require(sha(read(path)) == expected, 'Evidence changed during collection')
    for path,status in dependency_states.items():
        require(path.is_file() == (status != 'missing'), 'Audited dependency availability changed during collection')
    # Validate everything before creating the new destination. No deletion,
    # replacement, Git action, or write inside any input root is performed.
    output.mkdir(parents=True,exist_ok=False)
    for destination,raw in files.items():
        target=output/destination; target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream: stream.write(raw)
    return manifest_record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','previous','audit','report','output'): parser.add_argument('--'+name,type=Path,required=True)
    for name in ('run','control','source','binaries'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    result=collect(args.root,args.previous,args.audit,args.report,args.output,run=args.run,control=args.control,source=args.source,binaries=args.binaries)
    print(json.dumps({'bundle_created':True,'reported_pipeline_status':result['reported_pipeline_status'],
        'reported_audit_passed':result['reported_audit_passed'],'files':len(result['files'])}))


if __name__ == '__main__': main()
