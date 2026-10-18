"""Synthetic metadata fixtures exercise real reviewed builders; no native launch."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import pytest
D=Path(__file__).parent;C=D.parent

def load(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
s=load('sealer',D/'seal_direct_fit_inputs03.py')
f=load('existing_allowlist_fixtures',C/'observation-copy-allowlist-draft03/test_allowlist.py')

def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return s.pin(p)

def fixture(t):
 root=t/'actual';root.mkdir();f.test_support_collector_follows_gate_and_flight_read_dependencies_only(root)
 control=t/'control';control.mkdir();prior=t/'preparation-control';prior.mkdir()
 manifest=json.loads((root/'run/manifest.json').read_text())
 native=root/'native/bin/groops';native.parent.mkdir(parents=True);native.write_text('synthetic native identity; never executed')
 for rt in manifest['runtimes'].values():rt.update(python=s.pin(root/'python/bin/python'),native=s.pin(native))
 audit_record=json.loads((root/'audit.json').read_text());audit_record['identity']['native_sha256']=s.sha(native);put(root/'audit.json',audit_record)
 source=root/'source'
 for name in ('config.py','protocol.py','validation.py'):
  p=source/'src/orbit_poc/segmented'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# synthetic fixture public API identity only\n'+name)
 catalog=put(root/'run/prepared-input-catalog.json',{'schema':'orbit-poc-segmented-input-catalog-v1','entries':[{'case_id':c['case_id']} for c in manifest['cases']]})
 manifest['prepared_input_catalog']=catalog;manifest['manifest_hash']=s.canonical({k:v for k,v in manifest.items() if k!='manifest_hash'})
 mp=put(root/'run/manifest.json',manifest);put(root/'run/preparation-status.json',{'status':'prepared','manifest_hash':manifest['manifest_hash']})
 library=put(root/'library-manifest.json',{'directory':str(root/'native/lib'),'files':[]})
 cfg=json.loads((root/'config.json').read_text());cfg['corrected_reference']=s.pin(root/'audit.json');cfg['output_dir']=str(root/'run');cfg['resources'].update(reserved_cpu_ids=[24],threads=1,maximum_process_tree_rss_bytes=8589934592)
 for name in ('dense_runtime','segmented_runtime'):cfg[name].update(source_sha256='a'*64,source_root=str(source),python=s.pin(root/'python/bin/python'),native=s.pin(native),library_manifest=library)
 config=put(root/'config.json',cfg)
 temporal=root/'temp-parent';temporal.mkdir();(root/'temporary').rename(temporal/'fit-private')
 execution=put(prior/'execution.json',{'fit_cpu':24,'paths':{'root':str(root),'run':str(root/'run'),'source':str(source),'temporary':str(temporal)},'read_only_bindings':[]})
 pipeline=s.pin(root/'run/validation/attempt-0001/pipeline.json');audit=s.pin(root/'audit.json')
 pp=put(prior/'plan.json',{'schema':'orbit-poc-segmented-preparation-owned-plan-v1','execution':execution,'config':config,'validation_audit':audit,'pipeline':pipeline,'control_root':str(prior)})
 after=put(prior/'after.json',{'schema':'orbit-poc-segmented-preparation-state-check-v1','phase':'after','status':'passed','config':config,'source_sha256':'a'*64,'validation':{'status':'passed','pipeline':pipeline},'prepared':{'cases':28,'attempts':68,'benchmark_fit_count':0,'manifest':mp}})
 cp=put(prior/'pipeline.json',{'schema':'orbit-poc-segmented-preparation-owned-run-v1','status':'prepared','benchmark_attempts':0,'final_cleanup':{'verified':True,'errors':[]},'plan':pp,'checks':[{'phase':'before','status':'complete','returncode':0},{'phase':'after','status':'complete','returncode':0,'result':after}],'preparation':{'status':'complete','returncode':0}})
 names={'allowlist':'observation-copy-allowlist-draft03/prepare_segmented_fit_allowlist03.py','planner':'plan_segmented_fit_namespace01.py','probe':'probe_segmented_fit_namespace02.py','wrapper':'with_segmented_fit_namespace01.py','inner':'run_blinded_segmented_campaign02.py','state_checker':'check_segmented_fit_state02.py'}
 system=put(control/'system-support.json',{'schema':'orbit-poc-segmented-system-support-files-v1','files':[s.pin(root/'system-helper')]})
 request={'schema':'orbit-poc-direct-fit-sealing-request-v1','helper':s.pin(D/'seal_direct_fit_inputs03.py'),'preparation_plan':pp,'preparation_controller':cp,'execution':execution,'config':config,'validation_audit':audit,'system_support':system,'helpers':{k:s.pin(C/v) for k,v in names.items()},'taskset':s.pin('/usr/bin/taskset'),'bubblewrap':s.pin('/usr/bin/bwrap'),'control':s.identity(control),'temporary':s.identity(temporal/'fit-private'),'attempts':s.identity(root/'run/attempts'),'known_flight_references':[],'additional_denied_trees':[],'output_root':str(control/'sealed01')}
 return request,root,prior,control

def reference_fixture(t,present=False):
 p,root,prior,control=fixture(t);physical=t/'physical';physical.mkdir();back=physical/'GNV1B_fixture.txt';back.write_text('reference denial bytes only')
 alias=t/'canonical';canonical=alias/back.name
 if present:alias.mkdir();canonical.write_text('unrelated host bytes hidden by the declared readonly binding')
 e=s.read(p['execution']);e['read_only_bindings']=[{'source':str(physical),'target':str(alias)}];p['execution']=put(prior/'reference-execution.json',e)
 pp=s.read(p['preparation_plan']);pp.update(execution=p['execution'],driver=s.pin(C/'closure-owned-driver09.py'));p['preparation_plan']=put(prior/'reference-plan.json',pp)
 cp=s.read(p['preparation_controller']);cp['plan']=p['preparation_plan'];p['preparation_controller']=put(prior/'reference-controller.json',cp)
 p['known_flight_references']=[{'path':str(canonical),'sha256':s.sha(back),'role':'reference_orbit'},{**s.pin(back),'role':'reference_orbit'}]
 return p,canonical,back,prior

@pytest.mark.parametrize('present',[False,True])
def test_known_reference_alias_uses_exact_original_driver_mapping(tmp_path,present):
 p,alias,back,prior=reference_fixture(tmp_path,present);plan=s.make_plan(p);context=s.context(p)
 assert alias.exists()==present and not Path(p['output_root']).exists()
 assert context['known_reference_backings'][0]['backing']==str(back)
 assert {r['canonical'] for r in context['known_reference_backings']}=={str(alias),str(back)}
 assert len({(r['device'],r['inode'],r['sha256']) for r in context['known_reference_backings']})==1
 assert plan['request']['known_flight_references']==p['known_flight_references']

def test_unchanged_probe_expands_canonical_and_backing_denial(tmp_path):
 p,alias,back,prior=reference_fixture(tmp_path);c=s.context(p);probe=s.module('unchanged_probe',p['helpers']['probe'])
 run=c['execution']['paths']['run']
 allow={'files':[],'directories':[],'verified_safe_trees':[],'native_data_inventories':[],
        'denied_files':[{'path':str(q),'resolved':str(q)} for q in (alias,back)],
        'source_plan':{'run_root':run},'manifest_hash':c['manifest']['manifest_hash'],
        'writable':{'attempts':p['attempts']['path'],'temporary':p['temporary']['path'],'lock':{'path':run+'/.segmented.lock'}}}
 spec=s.probe_spec(p,c,allow,[],probe)
 assert spec['denied_paths']==sorted([str(alias),str(back)]) and not alias.exists()

@pytest.mark.parametrize('kind',['wrong_hash','unmapped','missing_backing','cycle','missing_physical_pin','missing_canonical_pin','duplicate_pin','wrong_driver','shadowed_alias'])
def test_known_reference_resolution_rejects_errors_without_outputs(tmp_path,kind):
 p,alias,back,prior=reference_fixture(tmp_path)
 if kind=='wrong_hash':p['known_flight_references'][0]['sha256']='0'*64
 elif kind=='missing_backing':back.unlink()
 elif kind=='missing_physical_pin':p['known_flight_references'].pop()
 elif kind=='missing_canonical_pin':p['known_flight_references'].pop(0)
 elif kind=='duplicate_pin':p['known_flight_references'].append(p['known_flight_references'][0].copy())
 elif kind=='cycle':back.unlink();other=back.with_name('loop');back.symlink_to(other);other.symlink_to(back)
 elif kind=='wrong_driver':
  pp=s.read(p['preparation_plan']);pp['driver']['sha256']='0'*64;p['preparation_plan']=put(prior/'bad-driver-plan.json',pp);cp=s.read(p['preparation_controller']);cp['plan']=p['preparation_plan'];p['preparation_controller']=put(prior/'bad-driver-controller.json',cp)
 else:
  e=s.read(p['execution'])
  if kind=='unmapped':e['read_only_bindings']=[]
  else:
   other=tmp_path/'wrong-reference';other.write_text('wrong');e['read_only_bindings'].append({'source':str(other),'target':str(alias)})
  p['execution']=put(prior/'bad-reference-execution.json',e);pp=s.read(p['preparation_plan']);pp['execution']=p['execution'];p['preparation_plan']=put(prior/'bad-reference-plan.json',pp);cp=s.read(p['preparation_controller']);cp['plan']=p['preparation_plan'];p['preparation_controller']=put(prior/'bad-reference-controller.json',cp)
 with pytest.raises((ValueError,RuntimeError,OSError)):s.make_plan(p)
 assert not Path(p['output_root']).exists()


def test_actual_metadata_flow_uses_real_builders_and_preserves_truth_denial(tmp_path):
 p,root,prior,control=fixture(tmp_path);before={str(q):s.sha(q) for q in root.rglob('*') if q.is_file()}
 plan=s.make_plan(p);assert not Path(p['output_root']).exists()
 result=s.seal(plan);assert result['status']=='sealed_metadata' and not result['fit_execution_authorized'] and result['fit_attempts']==result['native_executions']==0
 out=Path(p['output_root']);allow=json.loads((out/'allowlist.json').read_text());mount=json.loads((out/'mount-plan.json').read_text());inv=json.loads((out/'invocation.json').read_text())
 assert len(allow['denied_files'])>=2 and any(r['path'].endswith('truth.npz') for r in allow['denied_files'])
 assert not any(r['path'].endswith('truth.npz') for r in allow['files'])
 assert mount['policy']['host_root_mounted'] is False and mount['policy']['network_namespace']=='fresh'
 assert inv['wrapper']['sha256']==s.HELPERS['wrapper'] and inv['inner_helper']['sha256']==s.HELPERS['inner']
 assert all(s.sha(q)==h for q,h in before.items()) and not any((root/'run/attempts').iterdir())
 with pytest.raises(ValueError,match='fresh'):s.seal(plan)


@pytest.mark.parametrize('kind',['missing_manifest','wrong_manifest_hash','missing_case','missing_attempt','failed_preparation','dirty_cleanup','ran_fits','failed_check','incomplete_after','wrong_source','wrong_cpu','changed_helper','unknown_option','changed_config_pin','nonempty_attempts','nonempty_temporary','output_overlap','wrong_catalog','missing_system_support'])
def test_invalid_preparation_cannot_even_create_a_sealing_plan(tmp_path,kind):
 p,root,prior,control=fixture(tmp_path)
 if kind=='missing_manifest':(root/'run/manifest.json').unlink()
 elif kind=='changed_helper':p['helpers']['allowlist']['sha256']='0'*64
 elif kind=='unknown_option':p['allow_truth']=True
 elif kind=='changed_config_pin':p['config']['sha256']='0'*64
 elif kind=='nonempty_attempts':(root/'run/attempts/preserved').touch()
 elif kind=='nonempty_temporary':(Path(p['temporary']['path'])/'preserved').touch()
 elif kind=='output_overlap':p['output_root']=str(root/'run/outputs')
 elif kind=='missing_system_support':Path(p['system_support']['path']).unlink()
 elif kind in ('wrong_manifest_hash','missing_case','missing_attempt'):
  m=json.loads((root/'run/manifest.json').read_text())
  if kind=='wrong_manifest_hash':m['manifest_hash']='0'*64
  elif kind=='missing_case':m['cases'].pop()
  else:m['attempts'].pop()
  put(root/'run/manifest.json',m)
 elif kind=='wrong_catalog':put(root/'run/prepared-input-catalog.json',{'entries':[]})
 elif kind in ('failed_preparation','dirty_cleanup','ran_fits','failed_check'):
  v=s.read(p['preparation_controller'])
  if kind=='failed_preparation':v['status']='failed'
  elif kind=='dirty_cleanup':v['final_cleanup']['errors']=['still running']
  elif kind=='ran_fits':v['benchmark_attempts']=1
  else:v['checks'][1]['status']='failed'
  p['preparation_controller']=put(prior/'changed-controller.json',v)
 elif kind in ('incomplete_after','wrong_source'):
  cp=s.read(p['preparation_controller']);v=s.read(cp['checks'][1]['result'])
  if kind=='incomplete_after':v['prepared']['cases']=27
  else:v['source_sha256']='f'*64
  cp['checks'][1]['result']=put(prior/'changed-after.json',v);p['preparation_controller']=put(prior/'changed-controller.json',cp)
 elif kind=='wrong_cpu':v=s.read(p['execution']);v['fit_cpu']=32;p['execution']=put(prior/'changed-execution.json',v)
 with pytest.raises((ValueError,FileNotFoundError,KeyError)):s.make_plan(p)
 assert not Path(p['output_root']).exists()


def test_failure_preserves_partial_metadata_and_original_inputs(tmp_path):
 p,root,prior,control=fixture(tmp_path)
 # A copied truth payload in purported system support must fail the reviewed
 # allowlist builder; no synthetic benchmark fixture is promoted as a result.
 secret=root/'run/preparation/generation/family/evaluation/truth.npz';copy=control/'copied-truth';copy.write_bytes(secret.read_bytes())
 p['system_support']=put(control/'bad-system.json',{'schema':'orbit-poc-segmented-system-support-files-v1','files':[s.pin(copy)]})
 plan=s.make_plan(p)
 with pytest.raises(ValueError,match='denied'):s.seal(plan)
 failed=json.loads((Path(p['output_root'])/'failure.json').read_text())
 assert failed['status']=='failed' and failed['fit_attempts']==0 and secret.exists()
 assert not (Path(p['output_root'])/'result.json').exists()


def test_planned_output_path_tamper_rejected_before_write(tmp_path):
 p,*_=fixture(tmp_path);plan=s.make_plan(p);plan['planned_outputs']['allowlist.json']='/outside/allowlist.json'
 with pytest.raises(ValueError,match='specification'):s.seal(plan)
 assert not Path(p['output_root']).exists()
