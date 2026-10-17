"""Metadata-only launcher tests; never execute a launcher or create a child."""
import ast
import hashlib
import json
from pathlib import Path
import pytest

HERE=Path(__file__).parent
NAMES=['verify_correctness_results_07.py','render_correctness_report_07.py','collect_correctness_publication_07.py','recovery_evidence_07.py']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prepared(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new';(old/'control').mkdir(parents=True);(new/'control').mkdir(parents=True)
    plan={'schema':'orbit-poc-correctness-postprocess07-plan-v1','source_commit':'old','source_sha256':'a'*64,'helpers':{name:'b'*64 for name in NAMES},'postprocessor_sha256':'c'*64,'execution':{'path':'old-execution','sha256':'d'*64},'candidate_pins':{'path':'old-pins','sha256':'e'*64},'driver_process':{'pid':1,'start_ticks':2,'boot_id':'old'},'output_root':'old-output','reporting_python':{'path':'/pinned/python','sha256':'f'*64,'versions':{'python':'3.10.12'}},'previous':'/canonical/original-objective','wait_seconds':86400}
    prior=old/'control/candidate07-postprocess-plan.json';prior.write_text(json.dumps(plan))
    launch={'driver_process':{'pid':3000,'start_ticks':12345,'boot_id':'current'}}
    freeze={'commit':'7e232423566a9d608ada0bcc88af8a86dd914db3','source':{'sha256':'029864cfbb2140007d0767505e0f4a655912a9ff053e135fd2bc0f434415b498'}}
    control=new/'control';(control/'candidate09-launch.json').write_text(json.dumps(launch));(control/'candidate09-source-freeze.json').write_text(json.dumps(freeze))
    for name in [*(n.replace('_07.py','_09.py') for n in NAMES),'postprocess_candidate09.py','candidate09-execution.json','candidate09-pins.json']:(control/name).write_text('exact fixture bytes '+name)
    return old,new,plan,launch,freeze

def metadata(old,new):
    tree=ast.parse((HERE/'launch_postprocess09.py').read_text())
    # Stop immediately before SIGHUP/process launch. Only two root literals are mapped.
    boundary=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='signal.signal')
    tree.body=tree.body[:boundary]
    class Roots(ast.NodeTransformer):
        def visit_Constant(self,node):
            mapping={'@EXECUTION_08_ROOT@':str(old),'@EXECUTION_09_ROOT@':str(new)}
            if isinstance(node.value,str) and node.value in mapping:return ast.copy_location(ast.Constant(mapping[node.value]),node)
            return node
    tree=Roots().visit(tree);ast.fix_missing_locations(tree)
    assert 'Popen' not in ast.unparse(tree)
    ns={};exec(compile(tree,'exact_launcher_metadata','exec'),ns);return ns

def test_exact09_metadata_and_pinned_helpers(tmp_path):
    old,new,prior,launch,freeze=prepared(tmp_path);ns=metadata(old,new);p=ns['plan'];c=new/'control'
    assert p['schema']=='orbit-poc-correctness-postprocess09-plan-v1'
    assert p['source_commit']==freeze['commit'] and p['source_sha256']==freeze['source']['sha256']
    assert p['driver_process']==launch['driver_process']
    assert p['helpers']=={n.replace('_07.py','_09.py'):sha(c/n.replace('_07.py','_09.py')) for n in NAMES}
    assert p['execution']=={'path':str(c/'candidate09-execution.json'),'sha256':sha(c/'candidate09-execution.json')}
    assert p['candidate_pins']=={'path':str(c/'candidate09-pins.json'),'sha256':sha(c/'candidate09-pins.json')}
    assert p['postprocessor_sha256']==sha(c/'postprocess_candidate09.py')
    assert p['output_root']==str(new/'postprocess-09-01')
    assert ns['argv']==['/pinned/python',str(c/'postprocess_candidate09.py'),'--plan',str(c/'candidate09-postprocess-plan.json'),'--plan-sha256',sha(c/'candidate09-postprocess-plan.json')]

def test_preserves_runtime_previous_and_wait_without_mutating08(tmp_path):
    old,new,prior,_,_=prepared(tmp_path);before=(old/'control/candidate07-postprocess-plan.json').read_bytes();ns=metadata(old,new)
    for key in ('reporting_python','previous','wait_seconds'):assert ns['plan'][key]==prior[key]
    assert (old/'control/candidate07-postprocess-plan.json').read_bytes()==before
    assert not (new/'postprocess-09-01').exists()

def test_plan_cannot_overwrite_prior_launch_preparation(tmp_path):
    old,new,*_=prepared(tmp_path);metadata(old,new);before=(new/'control/candidate09-postprocess-plan.json').read_bytes()
    with pytest.raises(FileExistsError):metadata(old,new)
    assert (new/'control/candidate09-postprocess-plan.json').read_bytes()==before

@pytest.mark.parametrize('missing',['recovery_evidence_09.py','candidate09-source-freeze.json','candidate09-launch.json'])
def test_missing_identity_fails_before_process_launch(tmp_path,missing):
    old,new,*_=prepared(tmp_path);(new/'control'/missing).unlink()
    with pytest.raises(FileNotFoundError):metadata(old,new)
    assert not (new/'control/candidate09-postprocess-plan.json').exists()

def test_complete_launcher_diff_is_metadata_only():
    before=(HERE/'launch_postprocess07.py').read_text();after=(HERE/'launch_postprocess09.py').read_text()
    replacements={'orbit-v31-correctness-04-':'orbit-v31-correctness-08-','orbit-v31-correctness-07-':'orbit-v31-correctness-09-','candidate04-postprocess-plan.json':'candidate07-postprocess-plan.json','candidate07-launch.json':'candidate09-launch.json','candidate07-source-freeze.json':'candidate09-source-freeze.json','postprocess07-plan-v1':'postprocess09-plan-v1',"'_04.py','_07.py'":"'_07.py','_09.py'",'postprocess_candidate07.py':'postprocess_candidate09.py','candidate07-execution.json':'candidate09-execution.json','candidate07-pins.json':'candidate09-pins.json','postprocess-07-01':'postprocess-09-01','candidate07-postprocess-plan.json\';save':'candidate09-postprocess-plan.json\';save','candidate07-postprocess.log':'candidate09-postprocess.log','recovery07-postprocess-launch-v1':'recovery09-postprocess-launch-v1','candidate07-postprocess-launch.json':'candidate09-postprocess-launch.json'}
    for old,new in replacements.items():before=before.replace(old,new)
    assert ast.dump(ast.parse(before),include_attributes=False)==ast.dump(ast.parse(after),include_attributes=False)
