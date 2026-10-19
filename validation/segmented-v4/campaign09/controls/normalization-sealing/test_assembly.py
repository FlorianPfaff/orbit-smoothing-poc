"""Synthetic metadata-only assembly tests; no namespace or fit is launched."""
import importlib.util
import json
from pathlib import Path
import pytest
D=Path(__file__).parent;C=D.parent
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
a=load('assembler',D/'plan_direct_campaign06.py')
f=load('reviewed_direct_fixtures',C/'direct-path-campaign-draft02/test_direct_views.py')
def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return a.pin(p)
def fixture(t):
 base,view,root,prior,seal,campaign=f.case.__wrapped__(t)
 # Only synthetic fixture controls are replaced here; no production artifacts.
 for n in ('host-plan.json','launch-pins.json'):(campaign/n).unlink()
 cfg=a.read(a.read(base['preparation_plan'])['config']);cfg['resources'].update(maximum_process_tree_rss_bytes=8589934592,minimum_free_output_bytes=34359738368)
 for k in ('dense_runtime','segmented_runtime'):cfg[k].update(native={'sha256':'n'*64},segmented_solver={'sha256':'s'*64})
 cp=a.read(base['preparation_controller']);pp=a.read(base['preparation_plan']);config=put(root/'control/config.json',cfg);pp['config']=config
 pipeline=pp['pipeline'];audit={'schema':'orbit-poc-segmented-validation-terminal-independent-review-v1','consistency_passed':True,'scientific_status':'passed_scoped_checks','cleanup_verified':True,'identity':{'comparison_source_sha256':'source','native_sha256':'n'*64,'solver_sha256':'s'*64},'artifacts':{'config':config,'cli_pipeline':pipeline}}
 va=put(prior/'validation-audit.json',audit);audit['schema']='orbit-poc-shifted-cut-terminal-independent-review-v1';sa=put(prior/'shifted-audit.json',audit)
 pp.update(validation_audit=va,driver=a.pin(seal/'never_execute.py'));base['preparation_plan']=put(prior/'plan.json',pp);cp['plan']=base['preparation_plan']
 manifest=put(root/'run/manifest.json',{'fixture_only':True,'manifest_hash':'m'*64});after=a.read(cp['checks'][1]['result']);after.update(config=config);after['prepared']['manifest']=manifest
 cp['checks'][1]['result']=put(root/'temporary/after.json',after);base['preparation_controller']=put(prior/'pipeline.json',cp)
 helper=seal/'sealer.py';helper.write_bytes((C/'normalization-sealing-draft01/seal_direct_fit_inputs05.py').read_bytes())
 output=seal/'sealed';output.mkdir();mount=a.read(view['mount_plan'])
 allow=put(output/'allowlist.json',{'manifest_hash':'m'*64,'source_plan':{'manifest':manifest}})
 mapping=put(output/'backing-map.json',{'fixture_only':True});mount['inputs']={'allowlist':allow,'mapping':mapping};mp=put(output/'mount-plan.json',mount)
 probe=put(output/'probe-spec.json',{'manifest_hash':'m'*64,'config':config,'source_sha256':'source','writable':{'temporary':str(root/'temporary/fit-private')}})
 inv=put(output/'invocation.json',{'schema':'orbit-poc-segmented-fit-namespace-invocation-v1','mount_plan':mp,'probe_spec':probe,'config':config,'resume_planner':None,'wrapper':a.pin(C/'with_segmented_fit_namespace01.py'),'taskset':a.pin('/usr/bin/taskset')})
 correspondence=put(output/'correspondence.json',{'fixture_only':True})
 artifacts={'mount-plan.json':mp,'invocation.json':inv,'allowlist.json':allow,'backing-map.json':mapping,'probe-spec.json':probe,'correspondence.json':correspondence}
 request={'helper':a.pin(helper),'preparation_plan':base['preparation_plan'],'preparation_controller':base['preparation_controller'],'execution':base['execution'],'control':base['control'],'validation_audit':va,'config':config,'bubblewrap':base['bubblewrap'],'output_root':str(output)}
 sp=put(seal/'seal-plan.json',{'schema':'orbit-poc-direct-fit-sealing-plan-v1','manifest':manifest,'manifest_hash':'m'*64,'native_executions':0,'fit_execution_authorized':False,'request':request,'planned_outputs':{n:r['path'] for n,r in artifacts.items()}})
 base['payload'].update(helper=a.pin(helper),plan=sp);bp=put(seal/'readonly-plan.json',base)
 result=put(output/'result.json',{'schema':'orbit-poc-direct-fit-sealing-result-v1','status':'sealed_metadata','native_executions':0,'fit_attempts':0,'fit_execution_authorized':False,'manifest':manifest,'manifest_hash':'m'*64,'artifacts':artifacts})
 names={'host':C/'run_blinded_segmented_host03.py','launcher':C/'launch_segmented_campaign01.py','host_view':C/'direct-path-campaign-draft02/with_segmented_campaign_host_direct01.py','readonly':C/'direct-path-campaign-draft02/with_completed_preparation_direct02.py','observer':C/'observe_segmented_timing02.py','observer_owner':C/'owned_timing_observer01.py'}
 return {'schema':'orbit-poc-direct-campaign-assembly-request-v1','helper':a.pin(D/'plan_direct_campaign06.py'),'sealed_result':result,'sealing_plan':sp,'readonly_plan':bp,'helpers':{k:a.pin(v) for k,v in names.items()},'host_control':a.identity(campaign),'validation_audit':va,'shifted_audit':sa,'prelaunch_evidence':[va,sa]},base,root,prior,seal,campaign

def test_assemble_reviewed_host_and_direct_view_without_launch(tmp_path):
 p,base,root,prior,seal,campaign=fixture(tmp_path)
 before={str(q):a.sha(q) for q in root.rglob('*') if q.is_file()};result=a.assemble(p)
 assert result['status']=='assembled_metadata' and result['native_executions']==result['fit_attempts']==0 and result['fit_execution_authorized'] is False
 assert result['launch_command'][:3]==['/usr/bin/taskset','-c','32']
 hp=a.read(result['artifacts']['host-plan.json']);assert hp['fit_cpu']==24 and hp['observer_cpu']==32 and hp['sibling_cpus']==[88]
 assert hp['maximum_seconds']==604800 and hp['minimum_free_bytes']==34359738368
 assert all(a.sha(q)==h for q,h in before.items())
 assert not (campaign/'pipeline.json').exists() and not any((root/'run/attempts').iterdir())
 with pytest.raises(ValueError,match='Preserve'):a.assemble(p)

@pytest.mark.parametrize('kind',['unknown','helper','sealed_failed','sealed_had_fit','sealed_authorizes','wrong_manifest','wrong_sealer','wrong_readonly','bad_artifact_path','changed_artifact','missing_artifact','failure_present','stale_inode','prior_output','no_evidence','duplicate_evidence','changed_evidence','resumed_invocation','wrong_mount','overlap_source','overlap_sealing'])
def test_reject_invalid_metadata_before_assembly(tmp_path,kind):
 p,base,root,prior,seal,campaign=fixture(tmp_path)
 if kind=='unknown':p['run_now']=True
 elif kind=='helper':p['helpers']['host']['sha256']='0'*64
 elif kind=='stale_inode':p['host_control']['inode']+=1
 elif kind=='overlap_source':p['host_control']=a.identity(root/'source')
 elif kind=='overlap_sealing':p['host_control']=a.identity(seal)
 elif kind=='prior_output':(campaign/'pipeline.json').write_text('preserved')
 elif kind=='no_evidence':p['prelaunch_evidence']=[]
 elif kind=='duplicate_evidence':p['prelaunch_evidence']*=2
 elif kind=='changed_evidence':p['prelaunch_evidence'][0]['sha256']='0'*64
 elif kind=='wrong_sealer':
  sp=a.read(p['sealing_plan']);sp['request']['helper']['sha256']='0'*64;p['sealing_plan']=put(seal/'changed-plan.json',sp)
 elif kind=='wrong_readonly':
  bp=a.read(p['readonly_plan']);bp['preparation_controller']['sha256']='0'*64;p['readonly_plan']=put(seal/'changed-base.json',bp)
 else:
  r=a.read(p['sealed_result'])
  if kind=='sealed_failed':r['status']='failed'
  elif kind=='sealed_had_fit':r['fit_attempts']=1
  elif kind=='sealed_authorizes':r['fit_execution_authorized']=True
  elif kind=='wrong_manifest':r['manifest_hash']='wrong'
  elif kind=='bad_artifact_path':r['artifacts']['mount-plan.json']['path']=str(seal/'mount.json')
  elif kind=='changed_artifact':Path(r['artifacts']['mount-plan.json']['path']).write_text('changed')
  elif kind=='missing_artifact':r['artifacts'].pop('probe-spec.json')
  elif kind=='failure_present':(seal/'sealed/failure.json').touch()
  elif kind in ('resumed_invocation','wrong_mount'):
   name='invocation.json' if kind=='resumed_invocation' else 'mount-plan.json';v=a.read(r['artifacts'][name])
   if kind=='resumed_invocation':v['resume_planner']={'path':'/wrong','sha256':'0'*64}
   else:v['inputs']['allowlist']['sha256']='0'*64
   r['artifacts'][name]=put(seal/'sealed'/name,v)
  p['sealed_result']=put(seal/'sealed/result.json',r)
 with pytest.raises((ValueError,RuntimeError,FileNotFoundError)):a.assemble(p)
 assert not (campaign/'assembly.json').exists() and not (campaign/'host-plan.json').exists()
 assert not (root/'source/host-plan.json').exists() and not (seal/'host-plan.json').exists()

def test_failed_reviewed_host_validation_keeps_failed_output(tmp_path):
 p,base,root,prior,seal,campaign=fixture(tmp_path);v=a.read(p['shifted_audit']);v['scientific_status']='failed';p['shifted_audit']=put(prior/'bad-shifted.json',v)
 with pytest.raises(RuntimeError,match='audit'):a.assemble(p)
 assert (campaign/'host-plan.json').is_file() and (campaign/'failure.json').is_file() and not (campaign/'assembly.json').exists()
 assert not any((root/'run/attempts').iterdir())
