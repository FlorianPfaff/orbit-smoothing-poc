#!/usr/bin/env python3
"""Stage a fresh candidate09; never start native computation or reuse build outputs."""
from pathlib import Path, PurePosixPath
import argparse, copy, datetime, hashlib, importlib.util, json, os, subprocess, sys, tarfile

PREVIOUS=Path('@EXECUTION_08_ROOT@')
NEW=Path('@EXECUTION_09_ROOT@')
PREVIOUS_PINS_SHA='91b84d5a702c0b782f80cbebf68d2576c54797f809e9247eceaf4caeceee57d5'
PREVIOUS_PIPELINE_SHA='5b6c04dd19707a93da2e8bf2d8e01a9094f7501b1b5a668d0ada640b589be20a'
PREVIOUS_POST_SHA='df25875eb9f04c161bbea6ed493c4996a0101ad8081d4a7f84fa93bf25020165'
PREVIOUS_DRIVER_SHA='739d39ab68361dcf9233ceb5e8abfd92f68256bca39b18482df17909ab577d71'
COMMIT='7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'
TREE='097cb2de82c483262e82a1ef2ea8acde850a7ec2'
UPSTREAM_ARCHIVE_SHA='8f9489d786332cb2d7af95f7e05c1447b8a1ca857457c130a67d39316f714363'
MUTABLE=('native_source','build','binaries','run','temporary')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
def pin(path):return {'path':str(path),'sha256':sha(path)}
def require(ok,why):
    if not ok:raise RuntimeError(why)
def save(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
def digest(files):return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def safe_name(name):
    path=PurePosixPath(name)
    require(name and not path.is_absolute() and '..' not in path.parts and str(path)==name and '\\' not in name,'Unsafe archive name')
    require(path.parts[0]!='.git','Git internals cannot enter a source snapshot')
    return name

def unpack_source(archive,target,inventory):
    require(not target.exists() and not target.is_symlink(),'Fresh source required')
    files=inventory.get('files')
    require(isinstance(files,dict) and files and digest(files)==inventory.get('sha256'),'Invalid frozen source inventory')
    for name,value in files.items():
        safe_name(name);require(isinstance(value,str) and len(value)==64 and all(x in '0123456789abcdef' for x in value),'Invalid file digest')
    # Validate every member before creating any source path.
    with tarfile.open(archive,'r:*') as stream:
        members=stream.getmembers();names=[]
        for member in members:
            names.append(safe_name(member.name));require(member.isfile(),'Only regular frozen source files are supported')
        require(len(names)==len(set(names)) and set(names)==set(files),'Archive must contain the exact frozen source file set')
        for member in members:
            raw=stream.extractfile(member).read();require(hashlib.sha256(raw).hexdigest()==files[member.name],'Archive member hash mismatch: '+member.name)
        target.mkdir()
        for member in members:
            dest=target/member.name;dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as output:output.write(stream.extractfile(member).read())
            dest.chmod(0o444)

def check_terminal(validation,post):
    require(validation.get('status')=='failed' and validation.get('finished_at') and validation.get('final_cleanup',{}).get('verified') is True,'Prior validation is not terminal failed and clean')
    require(post.get('status') in ('completed','failed') and post.get('finished_at') and post.get('steps') and all(x.get('cleanup_verified') is True for x in post['steps']),'Prior postprocessor is not terminal and clean')
    require(post.get('validation_pipeline',{}).get('sha256')==PREVIOUS_PIPELINE_SHA,'Postprocessor belongs to a different validation')

def check_previous_controls(old,validation):
    pins=json.loads((old/'control/candidate07-pins.json').read_text())
    ep=old/'control/candidate07-execution.json'
    require(sha(ep)==pins.get('execution_sha256'),'Previous execution differs from sealed08 pins')
    require(validation.get('execution')==pin(ep),'Previous execution differs from actual08 validation')
    require(pins.get('driver_sha256')==PREVIOUS_DRIVER_SHA,'Previous driver identity differs from sealed08 pins')
    execution=json.loads(ep.read_text())
    wrapper=old/'control/with_correctness_namespace_04.py'
    require(execution.get('paths',{}).get('wrapper')==str(wrapper),'Previous wrapper path changed')
    require(sha(wrapper)==pins.get('wrapper_sha256'),'Previous wrapper differs from sealed08 pins')
    return ep

def next_execution(old,previous,new):
    value=copy.deepcopy(old)
    for name in ('root','source','control','wrapper',*MUTABLE):
        path=Path(value['paths'][name]);require(path==previous or previous in path.parents,'Unexpected owned path: '+name)
        value['paths'][name]=str(new/path.relative_to(previous))
    value['paths'].update(wrapper=str(new/'control/with_correctness_namespace_09.py'),run=str(new/'validation-09'),upstream_repository=str(new/'upstream.git'))
    value['reserved_cpu_note']='Attempt09: fresh source/build/binary/output directories; build CPUs24-27, serial scientific fits on CPU24 with verified current-host admission and owned-process cleanup. No administrative exclusive allocation is claimed. Original v3 campaign on workstation2 remains untouched. Scientific runtime and isolated glibc2.39 are unchanged from08.'
    return value

def stage(source_archive,source_archive_sha,source_freeze_sha,old=PREVIOUS,new=NEW):
    old,new=Path(old),Path(new);control=new/'control'
    require(control.is_dir() and not control.is_symlink(),'Stage reviewed controls first')
    require(not (control/'recovery09-staging.json').exists() and not (control/'recovery09-staging-failed.json').exists(),'No implicit staging retry')
    result={'schema':'orbit-poc-recovery09-staging-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'native_launched':False,'correctness_resolved':False}
    try:
        for path,expected in ((old/'control/candidate07-pins.json',PREVIOUS_PINS_SHA),(old/'validation-07/pipeline.json',PREVIOUS_PIPELINE_SHA),(old/'postprocess-07-01/pipeline.json',PREVIOUS_POST_SHA),(old/'control/validate_candidate_07.py',PREVIOUS_DRIVER_SHA)):
            require(sha(path)==expected,'Prior artifact changed: '+str(path))
        validation=json.loads((old/'validation-07/pipeline.json').read_text());post=json.loads((old/'postprocess-07-01/pipeline.json').read_text());check_terminal(validation,post)
        previous_execution=check_previous_controls(old,validation)
        spec=importlib.util.spec_from_file_location('staging09_prior_driver',old/'control/validate_candidate_07.py');driver=importlib.util.module_from_spec(spec);sys.modules[spec.name]=driver;spec.loader.exec_module(driver)
        prior=driver.load_execution(previous_execution);admission=driver.admission(prior)
        freeze=control/'candidate09-source-freeze.json';require(sha(freeze)==source_freeze_sha,'Source freeze changed')
        frozen=json.loads(freeze.read_text());require(frozen.get('schema')=='orbit-poc-candidate09-source-freeze-v1','Wrong source freeze schema')
        require(sha(source_archive)==source_archive_sha,'Source archive changed')
        execution=next_execution(prior,old,new)
        for key in (*MUTABLE,'source','upstream_repository'):
            path=Path(execution['paths'][key]);require(not path.exists() and not path.is_symlink(),'Fresh output path required: '+key)
        require(Path(execution['paths']['wrapper']).is_file(),'Reviewed09 wrapper is missing')
        unpack_source(source_archive,new/'source',frozen['source'])
        require(driver.source_receipt(new/'source')==frozen['source'],'Copied source snapshot differs')
        env={key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
        upstream=new/'upstream.git'
        subprocess.run(['git','clone','--bare','--no-hardlinks',str(old/'upstream.git'),str(upstream)],check=True,env=env)
        require(not (upstream/'objects/info/alternates').exists(),'Upstream cannot depend on alternate object stores')
        require(subprocess.check_output(['git','-C',str(upstream),'rev-parse',COMMIT+'^{tree}'],env=env,text=True).strip()==TREE,'Pinned upstream tree changed')
        raw=subprocess.check_output(['git','-C',str(upstream),'archive','--format=tar',COMMIT],env=env)
        require(hashlib.sha256(raw).hexdigest()==UPSTREAM_ARCHIVE_SHA,'Pinned upstream archive changed')
        upstream_receipt={'schema':'orbit-poc-recovery09-upstream-v1','commit':COMMIT,'tree':TREE,'archive_sha256':UPSTREAM_ARCHIVE_SHA,'archive_bytes':len(raw),'repository':str(upstream),'source_repository':str(old/'upstream.git'),'independent_object_store':True,'shallow_history_allowed_only_with_complete_pinned_tree':True}
        save(control/'recovery09-upstream.json',upstream_receipt)
        execution['runtime_artifacts'].update(recovery09_previous_validation=pin(old/'validation-07/pipeline.json'),recovery09_previous_postprocessor=pin(old/'postprocess-07-01/pipeline.json'),recovery09_upstream=pin(control/'recovery09-upstream.json'),recovery09_stager=pin(__file__))
        ep=control/'candidate09-execution.json';save(ep,execution);driver.load_execution(ep)
        for role,item in execution['runtime_artifacts'].items():require(sha(driver.resolved_host_path(item['path'],execution))==item['sha256'],'Runtime artifact changed: '+role)
        require(execution['read_only_bindings']==prior['read_only_bindings'],'Scientific input aliases changed')
        result.update(status='passed',execution=pin(ep),source_freeze=pin(freeze),source_archive=pin(source_archive),source_sha256=frozen['source']['sha256'],source_files=len(frozen['source']['files']),previous_validation=pin(old/'validation-07/pipeline.json'),previous_postprocessor=pin(old/'postprocess-07-01/pipeline.json'),upstream=pin(control/'recovery09-upstream.json'),admission=admission)
    except BaseException as error:
        result.update(status='failed',error=type(error).__name__+': '+str(error));save(control/'recovery09-staging-failed.json',result);raise
    save(control/'recovery09-staging.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-archive',type=Path,required=True);p.add_argument('--source-archive-sha256',required=True);p.add_argument('--source-freeze-sha256',required=True);args=p.parse_args()
    print(json.dumps(stage(args.source_archive,args.source_archive_sha256,args.source_freeze_sha256)))
