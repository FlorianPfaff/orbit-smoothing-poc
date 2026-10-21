"""Pure full-tree installation receipt guards, with no installer/native launch."""
from pathlib import Path
import copy,hashlib,importlib.util,json
import pytest
C=Path(__file__).parent
spec=importlib.util.spec_from_file_location('provenance02',C/'validation07_provenance04.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def fixture(tmp,monkeypatch):
 def file(name,data):
  p=tmp/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return {'path':str(p),'sha256':sha(p),'bytes':len(data)}
 def doc(name,value):return file(name,json.dumps(value).encode())
 def checked(pin):
  assert set(pin)=={'path','sha256'}
  if sha(Path(pin['path']))!=pin['sha256']:raise RuntimeError('Changed pin')
 root=tmp/'repository';out=tmp/'installation';gitdir=tmp/'upstream/.git'
 source={f'file{i}.cpp':hashlib.sha256(str(i).encode()).hexdigest()for i in range(1134)}
 repo={'groops/extension/'+x:'a'*64 for x in ('apply_extension.py','native_segmented.py','native_tangent_wide.py')};repo['scripts/build_groops.py']='b'*64
 baseline=doc('base.json',{'source_after':{}});delta=doc('delta.json',{'changes':[]})
 receipt={'build_base_result':baseline,'native_source_delta':delta};build={'source_after':source}
 archive=file('upstream.tar',b'fixture archive');git=file('git',b'git fixture');python=file('python',b'python fixture');head=file('HEAD',m.UPSTREAM_COMMIT.encode());helper=file('helper.py',b'installer fixture');monkeypatch.setattr(m,'INSTALLER_HELPER',helper['sha256'])
 provenance={'schema':'orbit-poc-pristine-native-source-archive-v1','commit':m.UPSTREAM_COMMIT,'uses_git_object_content_not_worktree':True,'archive':archive,'git_sha256':git['sha256'],'repository':str(tmp/'upstream')}
 inventory={'schema':'orbit-poc-native-installer-repository-inventory-v1','root':str(root),'files':repo}
 request={'schema':'orbit-poc-native-installer-equivalence-request-v1','archive':archive,'archive_provenance':doc('archive-provenance.json',provenance),'python':python,'git':git,'git_head':head,'git_dir':str(gitdir),'repository_inventory':doc('repository.json',inventory),'baseline_result':baseline,'source_delta':delta,'output':str(out)}
 argv=[[git['path'],'-C',provenance['repository'],'rev-parse','--absolute-git-dir'],[git['path'],'-C',provenance['repository'],'rev-parse','HEAD'],[python['path'],str(root/'groops/extension/apply_extension.py'),str(out/'checkout'),'--numerics'],[python['path'],str(root/'groops/extension/native_segmented.py'),str(out/'checkout')],[python['path'],str(root/'groops/extension/native_tangent_wide.py'),str(out/'checkout')],[git['path'],'-C',str(gitdir.parent),'rev-parse','HEAD']]
 commands=[]
 for i,command in enumerate(argv):
  stdout=(str(gitdir)if i==0 else m.UPSTREAM_COMMIT if i in (1,5)else'')+'\n'
  commands.append({'argv':command,'returncode':0,'stdout':file(f'command{i}.stdout',stdout.encode()),'stderr':file(f'command{i}.stderr',b'')})
 members={'schema':'orbit-poc-upstream-archive-members-v1','archive':archive,'members':[{'path':'source','kind':'directory'},{'path':'source/first.cpp','kind':'file','sha256':'c'*64,'bytes':1}]}
 install={'schema':'orbit-poc-native-installer-equivalence-result-v1','status':'passed','passed':True,'compiled':False,'native_launches':0,'git_mutations':0,'repository_preserved':True,'git_head_preserved':True,'pinned_inputs_preserved':True,'helper':helper,'request':doc('request.json',request),'inputs':{k:request[k]for k in request.keys()-{'schema','output'}},'baseline_result':baseline,'source_delta':delta,'repository_inventory':request['repository_inventory'],'source_after':source,'comparison':{'expected_files':1134,'actual_files':1134,'missing':[],'extra':[],'different':[]},'source_after_sha256':m.digest(source),'expected_source_sha256':m.digest(source),'installed_checkout':str(out/'checkout'),'archive':archive,'archive_provenance':request['archive_provenance'],'commands':commands,'archive_member_inventory':doc('members.json',members),'pristine_source':{'first.cpp':'c'*64}}
 return {'install':install,'receipt':receipt,'build':build,'repo':repo,'checked':checked,'file':file,'doc':doc,'request':request,'inventory':inventory,'provenance':provenance,'members':members,'run':lambda:m.verify_installation(install,receipt,build,repo,checked)}

@pytest.fixture
def f(tmp_path,monkeypatch):return fixture(tmp_path,monkeypatch)

def test_entire_tree_and_source_only_commands_pass(f):assert f['run']()

@pytest.mark.parametrize('case',['tree_byte','tree_member','tree_size','comparison','digest','expected_digest','baseline','delta','repository','request','helper','compiled','native','git_mutation','preserved','failed','command_order','command_extra','command_failed','command_stdout','head','archive','archive_member','archive_duplicate','pristine','nested_size'])
def test_mutation_rejected(f,case):
 v=f['install'];wrong={'path':'/wrong','sha256':'0'*64}
 if case=='tree_byte':f['build']['source_after']=dict(f['build']['source_after'],file0='0'*64)
 elif case=='tree_member':v['source_after']=dict(v['source_after'],extra='0'*64)
 elif case=='tree_size':v['source_after']=dict(v['source_after']);v['source_after'].pop('file0.cpp');f['build']['source_after']=v['source_after']
 elif case=='comparison':v['comparison']['different']=['file0.cpp']
 elif case=='digest':v['source_after_sha256']='0'*64
 elif case=='expected_digest':v['expected_source_sha256']='0'*64
 elif case=='baseline':v['baseline_result']=wrong
 elif case=='delta':v['source_delta']=wrong
 elif case=='repository':f['repo']=dict(f['repo'],extra='0'*64);v['repository_inventory']=wrong
 elif case=='request':v['inputs']['output']='unexpected'
 elif case=='helper':v['helper']=f['file']('differenthelper.py',b'different')
 elif case=='compiled':v['compiled']=True
 elif case=='native':v['native_launches']=1
 elif case=='git_mutation':v['git_mutations']=1
 elif case=='preserved':v['repository_preserved']=False
 elif case=='failed':v['status']='failed'
 elif case=='command_order':v['commands'][2],v['commands'][3]=v['commands'][3],v['commands'][2]
 elif case=='command_extra':v['commands'].append(copy.deepcopy(v['commands'][0]))
 elif case=='command_failed':v['commands'][2]['returncode']=1
 elif case=='command_stdout':v['commands'][0]['stdout']=f['file']('wrong-directory.stdout',b'/not-the-original-git\n')
 elif case=='head':v['commands'][5]['stdout']=f['file']('wrong-head.stdout',b'wrong\n')
 elif case=='archive':v['archive']=wrong
 elif case=='archive_member':f['members']['members'][1]['path']='elsewhere/first.cpp';v['archive_member_inventory']=f['doc']('members.json',f['members'])
 elif case=='archive_duplicate':f['members']['members'].append(copy.deepcopy(f['members']['members'][1]));v['archive_member_inventory']=f['doc']('members.json',f['members'])
 elif case=='pristine':v['pristine_source']={}
 elif case=='nested_size':v['commands'][1]['stdout']['bytes']+=1
 with pytest.raises((RuntimeError,KeyError,AssertionError)):f['run']()
