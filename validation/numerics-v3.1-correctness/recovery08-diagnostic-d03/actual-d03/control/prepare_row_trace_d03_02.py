#!/usr/bin/env python3
"""Pin actual attempt08 point006 for a bounded diagnostic; never alter its XML."""
from pathlib import Path
import hashlib,json,ast,importlib.util,os,fnmatch,xml.etree.ElementTree as ET
D=Path('@REMOTE_DATA_ROOT@/orbit-v31-diagnostic-row-trace-03-PRIVATE_USER')
R=Path('@EXECUTION_08_ROOT@')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def artifact(p):return {'path':str(p),'sha256':sha(p)}
def require(ok,why):
    if not ok:raise RuntimeError(why)
def resolve_and_capture(path,e,d,links):
    logical=Path(path);seen=set()
    for _ in range(65):
        physical=d.host_path(logical,e)
        require(physical not in seen,'Input alias symlink cycle');seen.add(physical)
        parts=physical.parts
        for index in range(1,len(parts)+1):
            prefix=Path(*parts[:index])
            if prefix.is_symlink():
                target=prefix.readlink();links[str(prefix)]=str(target)
                logical=Path(os.path.normpath(str((target if target.is_absolute() else prefix.parent/target).joinpath(*parts[index:]))));break
        else:
            require(physical.exists(),'Missing alias-aware input: '+str(path));return physical
    raise RuntimeError('Input alias traversal limit')

def collect_inputs(profile,e,d):
    inputs={'profile':artifact(profile)};links={};identities=[]
    for node in ET.parse(profile).iter():
        if not node.tag.startswith('inputfile') or not (node.text or '').strip():continue
        logical=node.text.strip();require(Path(logical).is_absolute(),'Non-absolute diagnostic input')
        pattern=Path(logical.replace('{prn}','*'));require('{' not in str(pattern) and '}' not in str(pattern),'Unsupported dynamic input substitution')
        require(not any(c in str(pattern.parent) for c in '*?['),'Only a filename may contain a dynamic input substitution')
        parent=resolve_and_capture(pattern.parent,e,d,links);require(parent.is_dir(),'Input parent is not a directory')
        matches=sorted(path for path in parent.iterdir() if fnmatch.fnmatchcase(path.name,pattern.name));require(matches,'Missing input pattern: '+logical)
        mapping=[]
        for path in matches:
            physical=resolve_and_capture(path,e,d,links);require(physical.is_file(),'Missing resolved input: '+str(path))
            require(d.resolved_host_path(path,e)==physical,'Independent input traversal differs from driver')
            pin=artifact(physical);inputs['input_'+str(len(inputs))]=pin;mapping.append({'matched_path':str(path),'resolved':pin})
        identities.append({'tag':node.tag,'declared':logical,'files':mapping})
    identity={'schema':'orbit-poc-d03-exact-inputs-v1','profile':inputs['profile'],'inputs':identities,'symlink_targets':links,'source_xml_unchanged':True,'diagnostic_only':True}
    return inputs,links,identity

def main():
    require(not (D/'control/plan.json').exists(),'No implicit retry')
    e=json.loads((D/'control/diagnostic-execution.json').read_text())
    for name in ('native_source','build','binaries','run','temporary'):
        require(not Path(e['paths'][name]).exists(),'Fresh output required: '+name)
    for name in ('run_row_trace_d03.py','build_row_trace_d03.py','install_row_trace.py','verify_trace_equivalence.py'):
        ast.parse((D/'control'/name).read_text())
    original=(D/'source/scripts/build_groops.py').read_text();adapted=(D/'control/build_row_trace_d03.py').read_text()
    expected=original.replace('    extension = Path(__file__).resolve().parents[1] / "groops/extension/apply_extension.py"','    extension = Path('+repr(str(D/'source/groops/extension/apply_extension.py'))+')').replace('    env = dict(os.environ)','    run([sys.executable, '+repr(str(D/'control/install_row_trace.py'))+', "--tree", source, "--receipt", '+repr(str(D/'diagnostic/row-trace-install.json'))+'])\n    env = dict(os.environ)')
    require(adapted==expected,'Build adapter exceeds diagnostic installation scope')
    prior=json.loads((R/'validation-07/pipeline.json').read_text())
    require(prior.get('status')=='failed' and prior.get('final_cleanup',{}).get('verified') and prior.get('finished_at'),'Attempt08 must be terminal, failed and clean')
    post=json.loads((R/'postprocess-07-01/pipeline.json').read_text())
    require(post.get('status') in {'failed','completed'} and post.get('finished_at') and post.get('steps') and all(s.get('cleanup_verified') for s in post['steps']),'Postprocessing must be terminal and clean')
    require(post.get('validation_pipeline',{}).get('sha256')==sha(R/'validation-07/pipeline.json'),'Wrong postprocessor validation attribution')
    point=R/'validation-07/objective-log_drag_ou/point-006-direction-1.0-1-repeat'
    profile=point/'profile.xml';inputs={'profile':artifact(profile)};links={};identities=[]
    spec=importlib.util.spec_from_file_location('driver',R/'control/validate_candidate_07.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    d.load_execution(D/'control/diagnostic-execution.json')
    require(d.source_receipt(D/'source')==json.loads((R/'control/candidate07-source-freeze.json').read_text())['source'],'Source snapshot changed')
    inputs,links,identity=collect_inputs(profile,e,d)
    identitypath=D/'control/input-identity.json'
    with identitypath.open('x') as f:json.dump(identity,f,sort_keys=True,indent=2);f.write('\n')
    helpers={key:artifact(D/'control'/name) for key,name in {'build':'build_row_trace_d03.py','install':'install_row_trace.py','header':'nuisanceArithmeticTrace.h','compare':'verify_trace_equivalence.py','wrapper':'with_correctness_namespace_04.py','input_identity':'input-identity.json','prepare':Path(__file__).name}.items()}
    plan={'schema':'orbit-poc-diagnostic-row-trace-plan-v2','runner':artifact(D/'control/run_row_trace_d03.py'),'execution':artifact(D/'control/diagnostic-execution.json'),'driver':artifact(R/'control/validate_candidate_07.py'),'source_freeze':artifact(R/'control/candidate07-source-freeze.json'),'helpers':helpers,'inputs':inputs,'input_links':links,'prior_pipeline':artifact(R/'validation-07/pipeline.json'),'prior_postprocess':artifact(R/'postprocess-07-01/pipeline.json'),'last_generation':4}
    with (D/'control/plan.json').open('x') as f:json.dump(plan,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'plan':artifact(D/'control/plan.json'),'inputs':len(inputs),'input_identity':artifact(identitypath),'helpers':helpers}))
if __name__=='__main__':main()
