"""Read-only bounded terminal10 transfer, separate from scientific controls."""
from pathlib import Path
import argparse,base64,datetime,gzip,hashlib,importlib.util,json,socket,subprocess,sys
sys.dont_write_bytecode=True
MAX_FILE=16*1024*1024
MAX_EXPANDED=64*1024*1024
MAX_TOTAL=64*1024*1024

def require(ok,message):
    if not ok:raise ValueError(message)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def record(path):
    path=Path(path);require(path.is_file() and not path.is_symlink(),'Missing or symlinked receipt: '+str(path))
    require(path.stat().st_size<=MAX_EXPANDED,'Expanded file exceeds64MiB')
    raw=path.read_bytes();require(len(raw)<=MAX_EXPANDED,'Expanded file grew beyond limit');return raw

def read_pin(pin):
    raw=record(pin['path']);require(sha(raw)==pin['sha256'],'Artifact pin changed');return json.loads(raw)

def lineage10(plan,execution,pins,frozen,control):
    require(plan.get('execution_attempt')=='10' and plan.get('candidate_control_version')=='09','Actual execution/control versions differ')
    require(frozen.get('execution_attempt')=='10' and frozen.get('control_version')=='09','Frozen actual execution attribution differs')
    supplement_raw=record(control/'installer-correction10.json')
    require(sha(supplement_raw)==plan['installer_correction_sha256'],'Immediate correction pin differs')
    supplement=json.loads(supplement_raw)
    require(supplement.get('schema')=='orbit-poc-installer-correction10-v1'
        and supplement.get('execution_attempt')=='10' and supplement.get('control_version')=='09','Wrong immediate correction version')
    require(supplement['new_source_freeze']==pins['new_source_freeze']
        and frozen['immediate_previous_source_freeze']==supplement['previous_source_freeze'],'Source transition pins differ')
    before=read_pin(supplement['previous_source_freeze'])
    require(before['commit']==plan['previous_source_commit']==frozen['immediate_previous_source_commit']
        and before['commit']!=frozen['commit'],'Immediate predecessor commit differs')
    require(set(before['source']['files'])==set(frozen['source']['files'])
        and before['regression_suite']==frozen['regression_suite']
        and frozen['regression_suite']['expected_count']==51,'Source paths or51 regressions differ')
    changes={k:{'before':before['source']['files'][k],'after':v} for k,v in frozen['source']['files'].items() if before['source']['files'][k]!=v}
    require(set(changes)=={'groops/extension/positionRemainder.py'} and changes==supplement['changes'],'Immediate correction is not installer-only')
    failed=read_pin(supplement['failed_pipeline'])
    require(supplement['failed_pipeline']['sha256']==plan['previous_validation_sha256']
        and failed.get('status')=='failed' and failed.get('finished_at')
        and failed.get('final_cleanup',{}).get('verified') is True and failed.get('source')==before['source'],
        'Immediate failed09 attribution differs')
    pin=execution['runtime_artifacts']['recovery10_supplementary_receipt']
    require(pin['path']==str(control/'execution10-supplementary-verification.json')
        and pin['sha256']==plan['supplementary_verification_sha256'],'Executed supplementary verification differs')
    verified=read_pin(pin)
    require(verified.get('schema')=='orbit-poc-installer-correction10-verification-v1'
        and verified.get('passed') is True and verified.get('new_source_commit')==frozen['commit']
        and verified.get('immediate_previous_source_commit')==before['commit']
        and verified.get('source_sha256')==frozen['source']['sha256']
        and verified.get('changes')==changes and verified.get('generated_tree_byte_equivalence') is True,
        'Supplementary verification/source attribution differs')
    return {'execution_attempt':'09','source_commit':before['commit'],'validation_sha256':supplement['failed_pipeline']['sha256'],
        'status':'failed','installer_correction_sha256':sha(supplement_raw),'supplementary_verification_sha256':pin['sha256'],
        'changes':changes,'control_basis_note':'Unchanged control09 retains cumulative source07/execution08 basis; actual immediate predecessor is separately pinned failed execution09.'}


def capture(plan):
    require(plan.get('schema')=='orbit-poc-terminal10-transfer-plan-v1','Unknown transfer plan')
    root=Path(plan['root']);require(root.is_absolute() and '..' not in root.parts,'Invalid root')
    run=root/'validation-09';post=root/'postprocess-09-01';control=root/'control'
    initial={rel:record(root/rel) for rel in ('validation-09/pipeline.json','postprocess-09-01/pipeline.json')}
    require({rel:sha(raw) for rel,raw in initial.items()}==plan['journals'],'Terminal journal identity differs')
    pipeline=json.loads(initial['validation-09/pipeline.json']);finished=json.loads(initial['postprocess-09-01/pipeline.json'])
    require(pipeline.get('schema')=='orbit-poc-correctness-validation09-run-v1'
        and pipeline.get('status') in ('passed','failed') and pipeline.get('finished_at')
        and pipeline.get('final_cleanup',{}).get('verified') is True,'Native validation not terminal and clean')
    require(finished.get('schema')=='orbit-poc-correctness-postprocess09-run-v1'
        and finished.get('status') in ('completed','failed') and finished.get('finished_at')
        and isinstance(finished.get('steps'),list) and len(finished['steps'])<=3
        and [s.get('name') for s in finished['steps']]==['audit','report','collect'][:len(finished['steps'])]
        and all(s.get('cleanup_verified') is True for s in finished['steps']),
        'Postprocessing not terminal and clean')
    binding=finished.get('validation_pipeline')
    require((isinstance(binding,dict) and binding.get('sha256')==plan['journals']['validation-09/pipeline.json'])
        or (binding is None and finished['status']=='failed'),'Postprocessing belongs to another validation')
    execution_raw=record(control/'candidate09-execution.json');pins_raw=record(control/'candidate09-pins.json')
    require(sha(execution_raw)==plan['execution_sha256'] and sha(pins_raw)==plan['pins_sha256'],'Execution or pins differ')
    execution=json.loads(execution_raw);pins=json.loads(pins_raw)
    require(pipeline.get('execution',{}).get('path')==str(control/'candidate09-execution.json')
        and pipeline['execution']['sha256']==plan['execution_sha256']
        and pipeline.get('required_pins',{}).get('sha256')==plan['pins_sha256'],'Executed identities differ')
    require(execution['paths']['root']==str(root) and execution['paths']['run']==str(run),'Execution layout differs')
    helper=control/'recovery_evidence_09.py';require(sha(record(helper))==pins['recovery_verifier_sha256'],'Frozen mapping helper changed')
    spec=importlib.util.spec_from_file_location('terminal10_mapping',helper);mapping=importlib.util.module_from_spec(spec);spec.loader.exec_module(mapping)
    prior=read_pin(mapping.mapped_pin(pins['candidate03_pins'],execution))
    sourcefreeze=read_pin(mapping.mapped_pin(pins['new_source_freeze'],execution))
    require(sourcefreeze.get('schema')=='orbit-poc-candidate09-source-freeze-v1'
        and sourcefreeze['commit']==plan['source_commit']
        and sourcefreeze['source']==pipeline.get('source')
        and sourcefreeze['source']['sha256']==plan['source_sha256'],'Source freeze/commit differs')
    immediate=lineage10(plan,execution,pins,sourcefreeze,control)
    require(isinstance(pins.get('input_artifacts'),dict) and len(pins['input_artifacts'])==14
        and pins['input_artifacts']==prior.get('input_artifacts'),'Original14 input identities differ')
    paths=[p for p in control.iterdir() if p.is_file() and p.suffix in ('.py','.json','.log')]
    paths.extend(p for p in run.iterdir() if p.is_file() and p.suffix in ('.json','.log','.xml'))
    for pattern in ('*/result.json','objective-*/validation.json','nuisance-replay*/receipt.json'):
        paths.extend(run.glob(pattern))
    failed=[]
    candidates=[]
    for point in sorted(p for p in run.glob('objective-*/point-*') if p.is_dir()):
        receipt=point/'profile.execution.json'
        if receipt.is_file():
            d=json.loads(record(receipt))
            if d.get('returncode')!=0 or d.get('timed_out'):candidates.append(('objective',point,d))
        else:
            steps=[s for s in pipeline.get('steps',[]) if s.get('name')==point.parent.name]
            require(len(steps)<=1,'Duplicate objective step')
            if steps and (steps[0].get('status')!='passed' or steps[0].get('returncode')!=0):
                candidates.append(('objective',point,{'status':'incomplete_point_missing_execution_receipt',
                    'execution_receipt_present':False,'objective_step':steps[0]}))
    for name in ('nuisance-replay','nuisance-replay-candidate1-point012'):
        replay=run/name
        if replay.is_dir():
            paths.extend(p for p in replay.iterdir() if p.is_file() and (p.suffix=='.json' or p.name in ('profile.xml','profile.log')))
        steps=[s for s in pipeline.get('steps',[]) if s.get('name')==name]
        require(len(steps)<=1,'Duplicate original replay step')
        if steps and (steps[0].get('status')!='passed' or steps[0].get('returncode')!=0):
            if (run/name).is_dir():candidates.append(('original_replay',run/name,steps[0]))
    for kind,point,status in candidates:
        selected=[p for p in point.iterdir() if p.is_file() and (p.suffix=='.json' or p.name in ('profile.xml','profile.log'))]
        for pattern in ('closure-*/propagate.execution.json','closure-*/propagate.log','closure-*/propagate.xml','closure-*/derivatives.json'):
            selected.extend(p for p in point.glob(pattern) if p.is_file())
        paths.extend(selected);external=[]
        for p in sorted(point.iterdir()):
            if p.is_file() and p.name.endswith(('.R.bin','.z.bin','.rhs.bin','.rows.tsv','.rows.tsv.gz')):
                require(not p.is_symlink(),'External factor is a symlink');h=hashlib.sha256();size=p.stat().st_size
                with p.open('rb') as f:
                    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                require(p.stat().st_size==size,'External factor changed during inventory')
                external.append({'path':str(p),'bytes':size,'sha256':h.hexdigest(),'storage':'external_only_not_transferred'})
        failed.append({'kind':kind,'point':str(point.relative_to(root)),'status_receipt':status,
            'selected_source_files':[str(p.relative_to(root)) for p in sorted(selected)],
            'external_native_artifacts':external,'row_spools_transferred':False})
    collect_steps=[s for s in finished['steps'] if s.get('name')=='collect']
    require(len(collect_steps)<=1,'Duplicate collector result')
    collector_complete=bool(collect_steps and collect_steps[0].get('returncode')==0
        and isinstance(collect_steps[0].get('result'),dict) and not collect_steps[0].get('result_error'))
    publication=post/'publication';publication_files=sorted(p for p in publication.rglob('*') if p.is_file()) if publication.exists() else []
    publication_inventory=[{'path':str(p.relative_to(root)),'sha256':sha(record(p)),'bytes':p.stat().st_size} for p in publication_files]
    paths.extend(p for p in post.rglob('*') if p.is_file() and 'publication' not in p.relative_to(post).parts)
    if collector_complete:
        manifest=publication/'manifest.json';require(collect_steps[0]['result'].get('path')==str(manifest),'Collector result belongs to another output')
        read_pin(collect_steps[0]['result']);paths.extend(publication_files)
    rows=[];raw_total=0;total=0;source_to_stored={}
    for p in sorted(set(paths)):
        require(p.is_relative_to(root),'Selected file outside execution root');raw=record(p);rel=str(p.relative_to(root));name=rel;packed=raw;encoding='identity'
        if p in (post/'independent-audit.json',post/'report/summary.json',post/'report/index.html') or len(raw)>MAX_FILE:
            packed=gzip.compress(raw,mtime=0);encoding='gzip';name+='.gz'
        require(len(packed)<=MAX_FILE,'Stored file exceeds16MiB');total+=len(packed);raw_total+=len(raw)
        require(total<=MAX_TOTAL,'Stored transfer exceeds64MiB');source_to_stored[rel]=name
        rows.append({'source':str(p),'relative':name,'encoding':encoding,'original_sha256':sha(raw),'original_bytes':len(raw),
            'sha256':sha(packed),'bytes':len(packed),'base64':base64.b64encode(packed).decode()})
        require(record(p)==raw,'Selected file changed during capture')
    for item in failed:item['selected_files']=[{'source':n,'stored':source_to_stored[n]} for n in item.pop('selected_source_files')]
    require(all(record(root/rel)==raw for rel,raw in initial.items()),'Terminal journals changed during transfer')
    return {'schema':'orbit-poc-terminal10-bounded-transfer-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'execution_attempt':'10','candidate_control_version':'09','remote_root':str(root),'hostname':socket.gethostname(),
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'source_commit':plan['source_commit'],'source_sha256':plan['source_sha256'],'execution_sha256':plan['execution_sha256'],
        'pins_sha256':plan['pins_sha256'],'journals':plan['journals'],'immediate_predecessor':immediate,'original14_input_artifacts':pins['input_artifacts'],
        'raw_bytes':raw_total,'transfer_bytes':total,'files':rows,'validation_status':pipeline['status'],
        'postprocess_status':finished['status'],
        'postprocess_validation_binding':'matched' if binding else 'not_recorded_before_failure',
        'postprocess_planned_steps':[next((s for s in finished['steps'] if s['name']==name),{'name':name,'status':'not_run'}) for name in ('audit','report','collect')],
        'native':pipeline.get('native'),'failed_profiles':failed,
        'collector_publication_complete':collector_complete,'collector_publication_inventory':publication_inventory,
        'collector_publication_transferred':collector_complete,'scientific_gate_substitution':False,
        'scope':'Exact terminal evidence, original14 identity and complete failed objective/replay histories. Native binaries, full source trees and raw row spools remain external.'}

def verify_return(value,plan):
    require(value.get('schema')=='orbit-poc-terminal10-bounded-transfer-v1'
        and value.get('remote_root')==plan['root']
        and all(value.get(k)==plan[k] for k in ('journals','pins_sha256','execution_sha256','source_commit','source_sha256')),
        'Returned transfer attribution differs')
    require(value.get('immediate_predecessor',{}).get('source_commit')==plan['previous_source_commit']
        and value['immediate_predecessor'].get('validation_sha256')==plan['previous_validation_sha256']
        and value['immediate_predecessor'].get('installer_correction_sha256')==plan['installer_correction_sha256']
        and value['immediate_predecessor'].get('supplementary_verification_sha256')==plan['supplementary_verification_sha256'],
        'Returned immediate lineage attribution differs')
    require(isinstance(value.get('original14_input_artifacts'),dict) and len(value['original14_input_artifacts'])==14,
        'Original14 transfer identity is missing')


def restore(value,output):
    output=Path(output);require(not output.exists(),'Local output must be new')
    require(value.get('schema')=='orbit-poc-terminal10-bounded-transfer-v1'
        and value.get('execution_attempt')=='10' and value.get('candidate_control_version')=='09','Transfer attribution differs')
    pending={};records=[];total=0;raw_total=0
    for row in value['files']:
        relative=Path(row['relative']);require(not relative.is_absolute() and '..' not in relative.parts and str(relative) not in pending,'Unsafe or duplicate output')
        packed=base64.b64decode(row['base64'],validate=True);require(len(packed)==row['bytes']<=MAX_FILE and sha(packed)==row['sha256'],'Stored transfer changed')
        require(row['encoding'] in ('identity','gzip') and row['original_bytes']<=MAX_EXPANDED,'Bad expanded transfer')
        if row['encoding']=='gzip':
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:raw=stream.read(MAX_EXPANDED+1)
        else:raw=packed
        require(len(raw)==row['original_bytes'] and sha(raw)==row['original_sha256'],'Expanded transfer changed')
        expected_source=Path(value['remote_root'])/(str(relative)[:-3] if row['encoding']=='gzip' else str(relative))
        require(str(expected_source)==row['source'],'Stored path and original source attribution differ')
        pending[str(relative)]=packed;total+=len(packed);raw_total+=len(raw);require(total<=MAX_TOTAL,'Local transfer exceeds64MiB')
        records.append({k:v for k,v in row.items() if k!='base64'})
    require(total==value['transfer_bytes'] and raw_total==value['raw_bytes'],'Transfer total differs');output.mkdir(parents=True)
    for name,raw in pending.items():p=output/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    return {**value,'files':records,'local_root':str(output),'local_match_verified':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--remote',action='store_true')
    parser.add_argument('--plan',type=Path);parser.add_argument('--plan-sha256');parser.add_argument('--output',type=Path)
    parser.add_argument('--manifest',type=Path);parser.add_argument('--envelope',type=Path);args=parser.parse_args()
    if args.remote:
        import sys
        print(json.dumps(capture(json.load(sys.stdin))));return
    require(all((args.plan,args.plan_sha256,args.output,args.manifest,args.envelope)),'Missing local plan/output arguments')
    require(not any(p.exists() for p in (args.output,args.manifest,args.envelope)),'Local outputs must be new')
    raw=args.plan.read_bytes();require(sha(raw)==args.plan_sha256,'Transfer plan changed');plan=json.loads(raw)
    # The exact code is sent on stdin and the sealed plan is a single literal JSON argument.
    import shlex
    code=Path(__file__).read_text();command='/usr/bin/python3 -c '+shlex.quote(code)+' --remote'
    with args.envelope.open('xb') as f:
        result=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','ConnectTimeout=10','gpuserver4090',command],input=raw,stdout=f,stderr=subprocess.PIPE)
    require(result.returncode==0,'Remote transfer failed: '+result.stderr.decode())
    value=json.loads(args.envelope.read_bytes());verify_return(value,plan)
    value=restore(value,args.output)
    args.manifest.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'files':len(value['files']),'bytes':value['transfer_bytes'],'manifest_sha256':sha(args.manifest.read_bytes())}))

if __name__=='__main__':main()
