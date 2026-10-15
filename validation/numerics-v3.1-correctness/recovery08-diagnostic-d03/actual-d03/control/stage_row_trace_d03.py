#!/usr/bin/env python3
"""Fresh D03 source/runtime staging after attempt08 and its postprocessor stop."""
from pathlib import Path
import hashlib,json,copy,shutil,importlib.util,subprocess
R=Path('@EXECUTION_08_ROOT@')
D=Path('@REMOTE_DATA_ROOT@/orbit-v31-diagnostic-row-trace-03-PRIVATE_USER')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def artifact(p):return {'path':str(p),'sha256':sha(p)}
def require(ok,why):
    if not ok:raise RuntimeError(why)
def main():
    require(not (D/'control/diagnostic-execution.json').exists(),'No implicit execution staging retry')
    v=json.loads((R/'validation-07/pipeline.json').read_text())
    require(v.get('status')=='failed' and v.get('finished_at') and v.get('final_cleanup',{}).get('verified'),'Original validation is not terminal, failed and clean')
    p=json.loads((R/'postprocess-07-01/pipeline.json').read_text())
    require(p.get('status') in {'completed','failed'} and p.get('finished_at') and p.get('steps') and all(s.get('cleanup_verified') for s in p['steps']),'Original postprocessor is not terminal and clean')
    require(p.get('validation_pipeline',{}).get('sha256')==sha(R/'validation-07/pipeline.json'),'Postprocessor belongs to another validation')
    spec=importlib.util.spec_from_file_location('d03_owned_driver',R/'control/validate_candidate_07.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    old=d.load_execution(R/'control/candidate07-execution.json')
    d.admission(old)
    freeze=json.loads((R/'control/candidate07-source-freeze.json').read_text())['source']
    require(d.source_receipt(R/'source')==freeze,'Original source changed')
    require(not (D/'source').exists(),'Fresh source directory required')
    (D/'source').mkdir()
    for name,digest in freeze['files'].items():
        source=R/'source'/name;dest=D/'source'/name
        require(sha(source)==digest,'Source input changed: '+name)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);dest.chmod(0o444)
    require(d.source_receipt(D/'source')==freeze,'Copied source snapshot mismatch')
    wrapper=D/'control/with_correctness_namespace_04.py';require(not wrapper.exists(),'Fresh wrapper required')
    shutil.copyfile(old['paths']['wrapper'],wrapper)
    e=copy.deepcopy(old)
    for key in ('root','source','control','wrapper','native_source','build','binaries','run','temporary'):
        raw=e['paths'][key]
        require(raw==str(R) or raw.startswith(str(R)+'/'),'Unexpected owned path: '+key)
        e['paths'][key]=str(D)+raw[len(str(R)):]
    e['paths']['wrapper']=str(wrapper);e['paths']['run']=str(D/'diagnostic')
    e['paths']['upstream_repository']=str(R/'upstream.git')
    e['read_only_bindings'].append({'source':str(R),'target':str(R)})
    e['reserved_cpu_note']='D03 bounded diagnostic only: serial native CPU24, fresh build CPUs24-27, exact host admission and owned-process cleanup; no competing native workload; no administrative exclusive allocation claimed; original campaign on workstation2 untouched.'
    e['runtime_artifacts']['d03_original_validation']=artifact(R/'validation-07/pipeline.json')
    e['runtime_artifacts']['d03_original_postprocess']=artifact(R/'postprocess-07-01/pipeline.json')
    e['runtime_artifacts']['d03_stager']=artifact(__file__)
    for key in ('native_source','build','binaries','run','temporary'):
        require(not Path(e['paths'][key]).exists(),'Fresh diagnostic output required: '+key)
    path=D/'control/diagnostic-execution.json'
    with path.open('x') as f:json.dump(e,f,sort_keys=True,indent=2);f.write('\n')
    d.load_execution(path)
    for pin in e['runtime_artifacts'].values():require(sha(d.resolved_host_path(pin['path'],e))==pin['sha256'],'Runtime identity changed')
    # Complete pinned tree, no external object database dependency. Shallow
    # history remains acceptable because the exact commit tree is available.
    upstream=Path(e['paths']['upstream_repository']);require((upstream/'HEAD').is_file(),'Missing pinned upstream')
    require(not (upstream/'objects/info/alternates').exists(),'Upstream has external alternates')
    env=dict(__import__('os').environ)
    for name in list(env):
        if name.startswith('GIT_'):env.pop(name)
    raw=subprocess.check_output(['git','-C',str(upstream),'archive','--format=tar','7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'],env=env)
    require(hashlib.sha256(raw).hexdigest()=='8f9489d786332cb2d7af95f7e05c1447b8a1ca857457c130a67d39316f714363','Pinned upstream archive differs')
    receipt={'schema':'orbit-poc-d03-staging-v1','execution':artifact(path),'source_sha256':freeze['sha256'],'source_files':len(freeze['files']),'source_freeze':artifact(R/'control/candidate07-source-freeze.json'),'prior_pipeline':artifact(R/'validation-07/pipeline.json'),'prior_postprocess':artifact(R/'postprocess-07-01/pipeline.json'),'upstream_archive_sha256':hashlib.sha256(raw).hexdigest(),'upstream_archive_bytes':len(raw),'admission':d.admission(e),'scientific_acceptance':False}
    with (D/'control/staging.json').open('x') as f:json.dump(receipt,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps(receipt))
if __name__=='__main__':main()
