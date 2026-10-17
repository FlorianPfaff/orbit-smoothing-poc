"""Fabricated outer-control checks; no scientific process is started."""
import importlib.util,json
from pathlib import Path
import pytest
S=importlib.util.spec_from_file_location('controller',Path(__file__).with_name('run_segmented_validation01.py'));M=importlib.util.module_from_spec(S);S.loader.exec_module(M)
@pytest.fixture
def plan(tmp_path):
 a=tmp_path/'artifact';a.write_text('sealed');pin={'path':str(a),'sha256':M.sha(a)}
 v={k:dict(pin) for k in M.PINS};v.update(schema='orbit-poc-v4-cli-validation-launch-plan-v1',global_lock='/tmp/serial.lock',wall_limit_seconds=108000)
 p=tmp_path/'plan.json';p.write_text(json.dumps(v));return p,v,a

def test_plan_exact(plan):
 p,v,_=plan;assert M.load_plan(p,M.sha(p))==v
@pytest.mark.parametrize('edit',[lambda v:v.update(extra=1),lambda v:v.update(schema='release'),lambda v:v.update(wall_limit_seconds=7200),lambda v:v.update(global_lock='relative'),lambda v:v['config'].update(sha256='0'*64),lambda v:v['source_freeze'].update(bytes=12),lambda v:v['runner'].update(path='relative')])
def test_changed_plan_rejected(plan,edit):
 p,v,_=plan;edit(v);p.write_text(json.dumps(v))
 with pytest.raises((RuntimeError,FileNotFoundError)):M.load_plan(p,M.sha(p))
def test_changed_artifact_rejected(plan):
 p,v,a=plan;a.write_text('changed')
 with pytest.raises(RuntimeError,match='Artifact changed'):M.load_plan(p,M.sha(p))
def test_changed_pin_file_rejected(plan):
 p,v,a=plan;h=M.sha(p);p.write_text('{}')
 with pytest.raises(RuntimeError,match='plan changed'):M.load_plan(p,h)
def test_public_cli_only():
 e={'paths':{'wrapper':'/wrapper','python':'/python'},'runtime_artifacts':{'control_python':{'path':'/control-python'}}};p={'execution':{'path':'/execution','sha256':'a'*64},'config':{'path':'/config'}}
 v=M.cli_command(e,p)
 assert v==['/control-python','/wrapper','--execution','/execution','--execution-sha256','a'*64,'--','/usr/bin/taskset','-c','24','/python','-m','orbit_poc.cli','segmented','validate','--config','/config']
@pytest.fixture
def output(tmp_path):
 r=tmp_path/'run';b=r/'validation';b.mkdir(parents=True)
 e=b/'execution.json';e.write_text(json.dumps({'status':'complete','returncode':0,'harness_execution':{'owned_process_group_cleaned':True}}))
 v={'schema':'orbit-poc-segmented-validation-run-v1','status':'passed','steps':[{'name':name,'status':'passed','execution':{'path':str(e),'sha256':M.sha(e)}} for name in M.STAGES]}
 p=b/'pipeline.json';p.write_text(json.dumps(v));(b/'latest.json').write_text(json.dumps({'pipeline':{'path':str(p),'sha256':M.sha(p)}}));return {'run':r},p,v,e

def update_output(paths,p,v):
 p.write_text(json.dumps(v));(paths['run']/'validation/latest.json').write_text(json.dumps({'pipeline':{'path':str(p),'sha256':M.sha(p)}}))
def test_passed_full_output(output):
 paths,p,v,e=output;assert M.inspect_cli_output(paths,{})['passed']==14

def test_failed_full_output_preserved(output):
 paths,p,v,e=output;v['status']='failed';v['steps'][0]['status']='failed';v['steps'][1:] = [{'name':name,'status':'not_run'} for name in M.STAGES[1:]];update_output(paths,p,v)
 x=M.inspect_cli_output(paths,{});assert x['status']=='failed' and x['passed']==0 and x['planned']==14
@pytest.mark.parametrize('mutation',[lambda v:v.update(status='running'),lambda v:v.update(schema='other'),lambda v:v['steps'].pop(),lambda v:v['steps'][1].update(status='running')])
def test_invalid_output_rejected(output,mutation):
 paths,p,v,e=output;mutation(v);update_output(paths,p,v)
 with pytest.raises(RuntimeError):M.inspect_cli_output(paths,{})
def test_no_cleanup_cannot_be_accepted(output):
 paths,p,v,e=output;e.write_text(json.dumps({'harness_execution':{'owned_process_group_cleaned':False}}));v['steps'][0]['execution']['sha256']=M.sha(e);update_output(paths,p,v)
 with pytest.raises(RuntimeError,match='cleanup'):M.inspect_cli_output(paths,{})
def test_execution_tamper_rejected(output):
 paths,p,v,e=output;e.write_text('{}')
 with pytest.raises(RuntimeError,match='Artifact changed'):M.inspect_cli_output(paths,{})
def test_plan_and_source_reverified_in_guard():
 import inspect
 s=inspect.getsource(M.main)
 assert "load_plan(a.plan,a.sha256)==p" in s and "d.source_receipt(paths['source'])==freeze['source']" in s
 assert 'with d.cleanup_signals()' in s and 'signal.signal(sig,d.interrupted)' in s
 assert "child.cleanup(force=child.child.poll() is None)" in s
 assert "d.prepare_writable_directories(e['paths'])" in s
 assert "d.supervise(" in s and "d.admission(e,registry)" in s

def test_launcher_only_metadata_and_directory_fsync():
 p=Path(__file__).parent;old=(p/'launch_segmented_engineering.py').read_text();new=(p/'launch_segmented_validation01.py').read_text()
 expected=old.replace('segmented_engineering.py','run_segmented_validation01.py').replace('engineering-launch','validation-launch').replace('engineering-driver','validation-driver').replace('orbit-poc-segmented-engineering-detached-launch-v1','orbit-poc-v4-cli-validation-detached-launch-v1')
 expected=expected.replace("json.dump(value,f,indent=2);f.write('\\n');f.flush();os.fsync(f.fileno())", "json.dump(value,f,indent=2);f.write('\\n');f.flush();os.fsync(f.fileno())\n    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)\n    try:os.fsync(fd)\n    finally:os.close(fd)")
 assert new==expected

@pytest.mark.parametrize('mutation',[lambda v:v['steps'].reverse(),lambda v:v['steps'][1].update(name=M.STAGES[0]),lambda v:v['steps'][0].pop('execution')])
def test_incomplete_gate_attribution_rejected(output,mutation):
 paths,p,v,e=output;mutation(v);update_output(paths,p,v)
 with pytest.raises(RuntimeError):M.inspect_cli_output(paths,{})
def test_external_pipeline_rejected(output):
 paths,p,v,e=output;q=paths['run'].parent/'external.json';q.write_text(p.read_text());(paths['run']/'validation/latest.json').write_text(json.dumps({'pipeline':{'path':str(q),'sha256':M.sha(q)}}))
 with pytest.raises(RuntimeError,match='escapes'):M.inspect_cli_output(paths,{})
@pytest.mark.parametrize('status,code',[('failed',0),('complete',1)])
def test_passed_process_cannot_claim_failure(output,status,code):
 paths,p,v,e=output;e.write_text(json.dumps({'status':status,'returncode':code,'harness_execution':{'owned_process_group_cleaned':True}}))
 for row in v['steps']:row['execution']['sha256']=M.sha(e)
 update_output(paths,p,v)
 with pytest.raises(RuntimeError,match='process failed'):M.inspect_cli_output(paths,{})

@pytest.mark.parametrize('status',['not_run','failed'])
def test_passed_summary_requires_all_gates_passed(output,status):
 paths,p,v,e=output;v['steps'][0]={'name':M.STAGES[0],'status':status};update_output(paths,p,v)
 with pytest.raises(RuntimeError,match='Passed CLI summary'):M.inspect_cli_output(paths,{})

def test_actual_emitted_module_entrypoint_help(tmp_path):
 import os,subprocess,sys
 e={'paths':{'wrapper':'/wrapper','python':sys.executable},'runtime_artifacts':{'control_python':{'path':'/control-python'}}};p={'execution':{'path':'/execution','sha256':'a'*64},'config':{'path':'/config'}}
 command=M.cli_command(e,p);module=command[command.index('-m')+1]
 source=Path(__file__).parent.parent/'source/src'
 result=subprocess.run([sys.executable,'-m',module,'segmented','validate','--help'],cwd=tmp_path,env=dict(os.environ,PYTHONPATH=str(source),PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=60)
 assert result.returncode==0,result.stderr
 assert 'usage: orbit-poc segmented validate' in result.stdout
