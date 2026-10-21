"""Synthetic unit fixtures only. No production manifest, bwrap or native launch."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest
D=Path(__file__).parent

def load(name):
 p=D/name;s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
b=load('with_completed_preparation_direct02.py')
h=load('with_segmented_campaign_host_direct01.py')
def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return b.pin(p)

@pytest.fixture
def case(tmp_path):
 root=tmp_path/'actual';root.mkdir();prior=tmp_path/'preparation-control';prior.mkdir();seal=tmp_path/'sealing-control';seal.mkdir();campaign=tmp_path/'campaign-control';campaign.mkdir()
 paths={'root':str(root)}
 for k in (*b.SLOTS,'source','control','prefix'):
  p=root/k;p.mkdir();paths[k]=str(p)
 hist=root/'run/validation';hist.mkdir();lock=tmp_path/'shared.lock';lock.touch();st=lock.stat()
 shared={'path':str(lock),'device':st.st_dev,'inode':st.st_ino}
 execution=put(prior/'execution.json',{'paths':paths,'fit_cpu':24,'read_only_bindings':[]})
 cfg=put(root/'control/config.json',{'output_dir':paths['run'],'resources':{'reserved_cpu_ids':[24],'threads':1},'segmented_runtime':{'source_sha256':'source'},'dense_runtime':{'source_sha256':'source'}})
 validation=put(hist/'pipeline.json',{'fixture_only':True})
 pp=put(prior/'plan.json',{'schema':'orbit-poc-segmented-preparation-owned-plan-v1','execution':execution,'control_root':str(prior),'config':cfg,'pipeline':validation,'global_lock':str(lock)})
 # Synthetic fixture marker; no real campaign manifest is fabricated.
 manifest=put(root/'run/manifest.json',{'fixture_only':True})
 after=put(root/'temporary/after.json',{'schema':'orbit-poc-segmented-preparation-state-check-v1','status':'passed','phase':'after','config':cfg,'source_sha256':'source','validation':{'status':'passed','pipeline':validation},'prepared':{'cases':28,'attempts':68,'benchmark_fit_count':0,'manifest':manifest}})
 cp=put(prior/'pipeline.json',{'schema':'orbit-poc-segmented-preparation-owned-run-v1','status':'prepared','benchmark_attempts':0,'plan':pp,'final_cleanup':{'verified':True,'errors':[]},'checks':[{'phase':'before','status':'complete','returncode':0},{'phase':'after','status':'complete','returncode':0,'result':after}],'preparation':{'status':'complete','returncode':0}})
 helper=seal/'never_execute.py';helper.write_text('raise RuntimeError("pure test fixture")')
 base={'schema':'orbit-poc-completed-preparation-direct-readonly-view-v1','helper':b.pin(D/'with_completed_preparation_direct02.py'),'execution':execution,'preparation_plan':pp,'preparation_controller':cp,'directories':{k:b.identity(paths[k]) for k in b.SLOTS},'historical_validation':b.identity(hist),'shared_lock':shared,'control':b.identity(seal),'payload':{'mode':'seal_inputs','helper':b.pin(helper),'plan':put(seal/'seal-plan.json',{'fixture_only':True})},'control_python':b.pin('/usr/bin/python3'),'bubblewrap':b.pin('/usr/bin/bwrap')}
 base['parent_topology']=put(seal/'parents.json',b.capture_topology([]))
 basepin=put(seal/'readonly-plan.json',base);writes=[]
 for kind,k,name in [('attempts','run','attempts'),('temporary','temporary','fit-private'),('lock','run','.segmented.lock')]:
  p=root/k/name
  if kind=='lock':p.touch()
  else:p.mkdir()
  st=p.stat();writes.append({'kind':kind,'source':str(p),'target':str(p),'identity':{'path':str(p),'device':st.st_dev,'inode':st.st_ino}})
 mount=put(seal/'mount.json',{'schema':'orbit-poc-segmented-fit-mount-plan-v1','writable_mounts':writes});inv=put(seal/'invocation.json',{'mount_plan':mount})
 host=put(campaign/'host-plan.json',{'helper':b.pin(helper),'config':cfg,'fit_cpu':24,'observer_cpu':32,'control_python':base['control_python'],'preparation_controller':cp,'global_lock':str(lock),'control_root':str(campaign),'invocation':inv})
 launch=put(campaign/'launch-pins.json',{'schema':'orbit-poc-segmented-campaign-launch-pins-v1','launcher':b.pin(helper),'controller':b.pin(helper),'control_python':base['control_python'],'plan':host,'control_root':str(campaign)})
 view={'schema':'orbit-poc-segmented-campaign-host-direct-view-v1','helper':h.pin(D/'with_segmented_campaign_host_direct01.py'),'readonly_helper':base['helper'],'readonly_plan':basepin,'launch_pins':launch,'mount_plan':mount,'control_python':base['control_python'],'bubblewrap':base['bubblewrap']}
 return base,view,root,prior,seal,campaign


def update_preparation(case,change):
 base,view,root,prior,seal,campaign=case
 pp=b.read(base['preparation_plan']);cp=b.read(base['preparation_controller']);e=b.read(base['execution']);after=b.read(cp['checks'][1]['result'])
 change(base,pp,cp,e,after)
 base['execution']=put(prior/'execution-updated.json',e);pp['execution']=base['execution']
 base['preparation_plan']=put(prior/'plan-updated.json',pp);cp['plan']=base['preparation_plan'];cp['checks'][1]['result']=put(root/'temporary/after-updated.json',after)
 base['preparation_controller']=put(prior/'pipeline-updated.json',cp)
 base['parent_topology']=put(seal/'parents-updated.json',b.capture_topology([(row['source'],row['target']) for row in e['read_only_bindings']]))
 view['readonly_plan']=put(seal/'readonly-updated.json',base)
 pins=h.read(view['launch_pins']);host=h.read(pins['plan']);host['preparation_controller']=base['preparation_controller'];pins['plan']=put(campaign/'host-updated.json',host);view['launch_pins']=put(campaign/'launch-updated.json',pins)


def update_host(case,change):
 base,view,root,prior,seal,campaign=case;pins=h.read(view['launch_pins']);host=h.read(pins['plan']);mount=h.read(view['mount_plan'])
 change(pins,host,mount)
 view['mount_plan']=put(seal/'mount-updated.json',mount);host['invocation']=put(seal/'invocation-updated.json',{'mount_plan':view['mount_plan']});pins['plan']=put(campaign/'host-updated.json',host);view['launch_pins']=put(campaign/'launch-updated.json',pins)


def test_completed_direct_view_has_one_writable_sealing_directory(case):
 base,_,root,prior,seal,_=case;v=b.build(base)
 assert v.count('--bind')==1 and v.count('--ro-bind')==7
 assert v[v.index('--bind')+1:v.index('--bind')+3]==[str(seal)]*2
 assert not {'--unshare-pid','--unshare-net','--die-with-parent'}&set(v)
 assert 'original_view' not in base
 for k in b.SLOTS:
  i=v.index(str(root/k));assert v[i-1:i+2]==['--ro-bind',str(root/k),str(root/k)]


def test_campaign_direct_view_keeps_only_exact_five_writable_paths(case):
 base,view,root,_,seal,campaign=case;v=h.build(view)
 triples=[v[i+1:i+3] for i,x in enumerate(v) if x=='--bind']
 assert triples==[[str(root/'run/attempts')]*2,[str(root/'temporary/fit-private')]*2,[str(root/'run/.segmented.lock')]*2,[base['shared_lock']['path']]*2,[str(campaign)]*2]
 assert v[v.index(str(seal))-1]=='--ro-bind'
 assert not {'--unshare-pid','--unshare-net','--die-with-parent'}&set(v)
 assert v[-4:]==['--pins',view['launch_pins']['path'],'--pins-sha256',view['launch_pins']['sha256']]


@pytest.mark.parametrize('kind',['extra','old_schema','old_view','changed_helper','failed','dirty','fits','wrong_after','incomplete','wrong_source','wrong_config','wrong_pipeline','wrong_cpu','wrong_output','changed_directory','changed_history','changed_lock','missing_manifest','payload_fit','external_payload','changed_payload','overlap_control'])
def test_completed_direct_invalid_state_rejected(case,kind):
 base,view,root,prior,seal,campaign=case
 def change(p,pp,cp,e,after):
  if kind=='failed':cp['status']='failed'
  if kind=='dirty':cp['final_cleanup']['errors']=['live child']
  if kind=='fits':cp['benchmark_attempts']=1
  if kind=='wrong_after':after['phase']='before'
  if kind=='incomplete':after['prepared']['cases']=27
  if kind=='wrong_source':after['source_sha256']='wrong'
  if kind=='wrong_config':after['config']['sha256']='0'*64
  if kind=='wrong_pipeline':after['validation']['pipeline']['sha256']='0'*64
  if kind=='wrong_cpu':e['fit_cpu']=32
  if kind=='wrong_output':e['paths']['run']=str(root/'temporary')
 if kind in {'failed','dirty','fits','wrong_after','incomplete','wrong_source','wrong_config','wrong_pipeline','wrong_cpu','wrong_output'}:update_preparation(case,change)
 if kind=='extra':base['extra']=True
 if kind=='old_schema':base['schema']='orbit-poc-completed-preparation-readonly-view-v1'
 if kind=='old_view':base['original_view']={'fabricated':True}
 if kind=='changed_helper':base['helper']['sha256']='0'*64
 if kind=='changed_directory':base['directories']['run']['inode']+=1
 if kind=='changed_history':base['historical_validation']['inode']+=1
 if kind=='changed_lock':base['shared_lock']['inode']+=1
 if kind=='missing_manifest':(root/'run/manifest.json').unlink()
 if kind=='payload_fit':base['payload']['mode']='run_fits'
 if kind=='external_payload':base['payload']['helper']=b.pin(D/'with_completed_preparation_direct02.py')
 if kind=='changed_payload':Path(base['payload']['helper']['path']).write_text('changed')
 if kind=='overlap_control':base['control']=b.identity(root/'run')
 with pytest.raises((RuntimeError,FileNotFoundError)):b.build(base)


@pytest.mark.parametrize('kind',['extra','old_schema','wrong_config','fit_cpu32','observer_cpu24','wrong_preparation','wrong_lock','reused_control','overlap_control','resume','missing_write','changed_inode','wrong_attempts','wrong_temporary','remapped_source','nonempty_attempts','nonempty_temporary','nonempty_lock','symlink_write','dotdot'])
def test_campaign_direct_invalid_handoff_rejected(case,kind):
 base,view,root,prior,seal,campaign=case
 def change(pins,host,mount):
  if kind=='wrong_config':host['config']['sha256']='0'*64
  if kind=='fit_cpu32':host['fit_cpu']=32
  if kind=='observer_cpu24':host['observer_cpu']=24
  if kind=='wrong_preparation':host['preparation_controller']['sha256']='0'*64
  if kind=='wrong_lock':host['global_lock']=str(campaign/'wrong.lock')
  if kind=='overlap_control':host['control_root']=pins['control_root']=str(seal)
  if kind=='resume':mount['schema']='orbit-poc-segmented-fit-resume-mount-plan-v1'
  if kind=='missing_write':mount['writable_mounts'].pop()
  if kind=='changed_inode':mount['writable_mounts'][0]['identity']['inode']+=1
  if kind=='wrong_attempts':mount['writable_mounts'][0]['target']=str(root/'run/unsafe')
  if kind=='wrong_temporary':mount['writable_mounts'][1]['target']=str(root/'run/validation')
  if kind=='remapped_source':mount['writable_mounts'][0]['target']=str(prior/'attempts')
  if kind=='dotdot':mount['writable_mounts'][1]['target']=str(root/'temporary')+'/../temporary/fit-private'
 if kind in {'wrong_config','fit_cpu32','observer_cpu24','wrong_preparation','wrong_lock','overlap_control','resume','missing_write','changed_inode','wrong_attempts','wrong_temporary','remapped_source','dotdot'}:update_host(case,change)
 if kind=='extra':view['extra']=True
 if kind=='old_schema':view['schema']='orbit-poc-segmented-campaign-host-view-v1'
 if kind=='reused_control':(campaign/'pipeline.json').write_text('preserved')
 if kind=='nonempty_attempts':(root/'run/attempts/preserved').touch()
 if kind=='nonempty_temporary':(root/'temporary/fit-private/preserved').touch()
 if kind=='nonempty_lock':(root/'run/.segmented.lock').write_text('data')
 if kind=='symlink_write':p=root/'run/attempts';p.rmdir();p.symlink_to(seal,target_is_directory=True)
 with pytest.raises(RuntimeError):h.build(view)


@pytest.mark.parametrize('kind',['attempts','temporary','lock','global_lock','control'])
@pytest.mark.parametrize('side',['source','target'])
def test_writes_never_override_readonly_bindings(case,kind,side):
 base,view,root,prior,seal,campaign=case
 paths={'attempts':root/'run/attempts','temporary':root/'temporary/fit-private','lock':root/'run/.segmented.lock','global_lock':Path(base['shared_lock']['path']),'control':campaign}
 other=prior/'readonly';other.mkdir()
 def change(p,pp,cp,e,after):
  row={'source':str(other),'target':str(other)};row[side]=str(paths[kind]);e['read_only_bindings']=[row]
 update_preparation(case,change)
 with pytest.raises(RuntimeError):h.build(view)


def test_inner_empty_root_controls_remain_unchanged():
 c=D.parent
 expected={'with_segmented_fit_namespace01.py':'85c961e0ac62f0e8b8a85e34930505776aa1027a1bbc51b2428d5be939cc692a','run_blinded_segmented_host03.py':'30fe0add2c5489052f6f353aa66f74dc5425a82e459eb3b06d5bda3037ce680d','run_blinded_segmented_campaign02.py':'24b12ce5c08ef5f8d821470736728202b993034bbc337b1191d320e32ea16af0','with_completed_preparation_view04.py':'634cedb9ccb9bda29abd2f71d1af31616f42e7e0f0b258a08175a7a639433ac2','with_segmented_campaign_host_view04.py':'a5dbcaf4f7a93e03c5fb8b4b132dba7164fcc1b8ed259edf0a88125766cf1f52'}
 for name,sha in expected.items():assert b.sha(c/name)==sha
 inner=(c/'with_segmented_fit_namespace01.py').read_text()
 assert "'-c','24'" in inner or "'-c', '24'" in inner


def test_actual_direct_execution_alias_ancestor_allows_only_shared_empty_lock(case):
 base,view,root,prior,seal,campaign=case
 # Place shared lock inside a distinct former-correctness root, as in actual07.
 old=prior.parent/'old-correctness';old.mkdir();lock=old/'control/shared.lock';lock.parent.mkdir();lock.touch();st=lock.stat()
 base['shared_lock']={'path':str(lock),'device':st.st_dev,'inode':st.st_ino}
 def change(p,pp,cp,e,after):
  pp['global_lock']=str(lock);e['read_only_bindings']=[{'source':str(old),'target':str(old)}]
 update_preparation(case,change)
 update_host(case,lambda pins,host,mount:host.update(global_lock=str(lock)))
 v=h.build(view);i=v.index(str(old));assert v[i-1:i+2]==['--ro-bind',str(old),str(old)]
 writes=[v[i+1:i+3] for i,x in enumerate(v) if x=='--bind']
 assert [str(lock),str(lock)] in writes and all(row!=[str(old),str(old)] for row in writes)
 (old/'control/preserved.json').write_text('immutable evidence')
 assert all(str(old/'control')!=row[1] for row in writes)
 lock.write_text('not empty')
 with pytest.raises(RuntimeError,match='lock'):h.build(view)


def test_sealing_control_cannot_alias_frozen_readonly_source(case):
 base,view,root,prior,seal,campaign=case;link=prior/'readonly-alias';link.symlink_to(seal,target_is_directory=True)
 def change(p,pp,cp,e,after):e['read_only_bindings']=[{'source':str(link),'target':str(prior/'other-alias')}]
 update_preparation(case,change)
 with pytest.raises(RuntimeError,match='overlaps'):b.build(base)
