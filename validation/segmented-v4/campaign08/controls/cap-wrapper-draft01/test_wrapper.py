from pathlib import Path
import copy,importlib.util,json,subprocess,types,pytest
s=importlib.util.spec_from_file_location('blind_wrapper',Path(__file__).with_name('with_segmented_fit_namespace02.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def pin(p):return {'path':str(p),'sha256':m.sha(p)}
def write(p,v):p.write_text(json.dumps(v));return pin(p)
@pytest.fixture
def fixture(tmp_path,monkeypatch):
 files={};p={'schema':'orbit-poc-segmented-fit-namespace-invocation-v1','wrapper':pin(Path(m.__file__)),'resume_planner':None,'bubblewrap':pin(Path('/usr/bin/bwrap'))}
 monkeypatch.setattr(m,'EXPECTED_BUBBLEWRAP',dict(p['bubblewrap']))
 planner=tmp_path/'planner.py';planner.write_text('fixture');p['fresh_planner']=pin(planner)
 def canonical(key,value,path=None):
  real=tmp_path/(key+'.json');real.write_text(json.dumps(value));logical=path or '/canonical/'+key;v={'path':logical,'sha256':m.sha(real)};files[logical]={**pin(real),'bytes':real.stat().st_size};return v
 p['python']=canonical('python',{},'/runtime/python');p['taskset']=canonical('taskset',{},'/usr/bin/taskset');p['inner_helper']=canonical('inner_helper',{});p['probe_helper']=canonical('probe_helper',{});p['probe_spec']=canonical('probe_spec',{})
 library=canonical('library',{'directory':'/runtime/lib'});cfg={'resources':{'reserved_cpu_ids':[24],'maximum_process_tree_rss_bytes':8589934592},'segmented_runtime':{'python':p['python'],'source_root':'/source','source_sha256':'source','library_manifest':library},'dense_runtime':{'source_root':'/source','source_sha256':'source'}};p['config']=canonical('config',cfg)
 inner={'config':p['config'],'probe_helper':p['probe_helper'],'probe_spec':p['probe_spec']};p['inner_plan']=canonical('inner_plan',inner)
 allow=write(tmp_path/'allow.json',{'marker':'unchanged'});mapping=write(tmp_path/'mapping.json',{'marker':'backing'})
 mount={'schema':'orbit-poc-segmented-fit-mount-plan-v1','inputs':{'allowlist':allow,'mapping':mapping},'canonical_symlinks':[],'verified_file_backings':files,'mount_args':['--tmpfs','/','--remount-ro','/']};p['mount_plan']=write(tmp_path/'mount.json',mount)
 fresh=types.SimpleNamespace(build=lambda i:mount,read=lambda i:json.loads(Path(i['path']).read_text()),links_resolve=lambda n,l:n);probe=types.SimpleNamespace(verify_spec_correspondence=lambda *a:True)
 return p,mount,files,cfg,inner,fresh,probe
def run(f,resume=None):p,_,_,_,_,fresh,probe=f;return m.prepare(p,fresh,resume,probe)
def change(f,key,value):
 p,mount,files,*_=f;logical=p[key]['path'];target=Path(files[logical]['path']);target.write_text(json.dumps(value));p[key]['sha256']=m.sha(target);files[logical]['sha256']=m.sha(target);files[logical]['bytes']=target.stat().st_size;p['mount_plan']=write(Path(p['mount_plan']['path']),mount)
def test_fixed_command_environment_without_host_root(fixture):
 v=run(fixture);assert v['prefix']==0 and v['command'][:5]==['/usr/bin/taskset','-c','24','/runtime/python','-B'];assert v['environment']['LD_LIBRARY_PATH']=='/runtime/lib';assert 'PATH' not in v['environment'];assert '--ro-bind' not in v['mount_args'];assert fixture[1]['mount_args']==v['mount_args'][:4]
@pytest.mark.parametrize('kind',['unknown','host_pin','self','bubblewrap','rebuilt','unexpected_resume','unknown_schema','canonical_pin','missing_backing','wrong_python','wrong_source','wrong_cpu','wrong_memory','inner_config','probe_spec','probe_reject','library_backing'])
def test_wrapper_fails_closed(fixture,kind):
 p,mount,files,cfg,inner,fresh,probe=fixture
 if kind=='unknown':p['extra']=1
 if kind=='host_pin':p['fresh_planner']['sha256']='0'*64
 if kind=='self':p['wrapper']=p['fresh_planner']
 if kind=='bubblewrap':p['bubblewrap']=p['fresh_planner']
 if kind=='rebuilt':fresh.build=lambda i:{'changed':True}
 if kind=='unexpected_resume':p['resume_planner']=p['fresh_planner']
 if kind=='unknown_schema':mount['schema']='unknown';p['mount_plan']=write(Path(p['mount_plan']['path']),mount)
 if kind=='canonical_pin':p['inner_helper']['sha256']='0'*64
 if kind=='missing_backing':del files[p['inner_helper']['path']];p['mount_plan']=write(Path(p['mount_plan']['path']),mount)
 if kind=='wrong_python':cfg['segmented_runtime']['python']={'path':'/other','sha256':'different'};change(fixture,'config',cfg)
 if kind=='wrong_source':cfg['dense_runtime']['source_sha256']='different';change(fixture,'config',cfg)
 if kind=='wrong_cpu':cfg['resources']['reserved_cpu_ids']=[32];change(fixture,'config',cfg)
 if kind=='wrong_memory':cfg['resources']['maximum_process_tree_rss_bytes']=999;change(fixture,'config',cfg)
 if kind=='inner_config':inner['config']={'path':'/different','sha256':'changed'};change(fixture,'inner_plan',inner)
 if kind=='probe_spec':inner['probe_spec']={'path':'/other','sha256':'changed'};change(fixture,'inner_plan',inner)
 if kind=='probe_reject':probe.verify_spec_correspondence=lambda *a:(_ for _ in ()).throw(RuntimeError('Denied alias list incomplete'))
 if kind=='library_backing':del files[cfg['segmented_runtime']['library_manifest']['path']];p['mount_plan']=write(Path(p['mount_plan']['path']),mount)
 with pytest.raises(RuntimeError):run(fixture)
@pytest.mark.parametrize('prefix',[1,67,68])
def test_resume_prefix_and_complete_noop(fixture,tmp_path,prefix):
 p,initial,files,cfg,inner,fresh,probe=fixture;initial_pin=write(tmp_path/'initial.json',initial)
 resumed={'schema':'orbit-poc-segmented-fit-resume-mount-plan-v1','inputs':{'inputs':{'initial_mount_plan':initial_pin}},'terminal_prefix':[{}]*prefix,'input_mounts_unchanged':True,'prior_attempts_readonly':True,'mount_args':['--tmpfs','/','--remount-ro','/']};p['mount_plan']=write(tmp_path/'resume.json',resumed);p['resume_planner']=p['fresh_planner'];resume=types.SimpleNamespace(build=lambda i:resumed)
 if prefix==68:
  with pytest.raises(RuntimeError,match='no-op'):run(fixture,resume)
 else:assert run(fixture,resume)['prefix']==prefix
def test_descriptor_boundary_actual_system_python(tmp_path):
 script=tmp_path/'fd.py';script.write_text('''import sys,os,json,importlib.util,fcntl
from pathlib import Path
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
w=load('wrapper',sys.argv[1]);p=load('planner',sys.argv[2]);extra=os.open(sys.argv[3],os.O_RDONLY);fd=p.sealed_args_fd(['--tmpfs','/']);w.descriptor_boundary(fd)
try:os.fstat(extra);raise AssertionError('Extra host descriptor survived')
except OSError:pass
assert os.read(0,1)==b'' and os.get_inheritable(fd) and fcntl.fcntl(fd,1034)==15
assert os.read(fd,1024)==b'--tmpfs\\0/\\0';os.close(fd);print(json.dumps({'passed':True}))
''');data=tmp_path/'secret';data.write_text('not inherited')
 done=subprocess.run(['/usr/bin/python3','-B',str(script),m.__file__,str(Path(__file__).with_name('plan_segmented_fit_namespace01.py')),str(data)],capture_output=True,text=True,timeout=10);assert done.returncode==0,done.stdout+done.stderr;assert json.loads(done.stdout)['passed']

PRODUCTION_BUBBLEWRAP=dict(m.EXPECTED_BUBBLEWRAP)
def test_production_binary_pin():
 assert PRODUCTION_BUBBLEWRAP=={'path': '/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/bwrap-cap-01/binaries/bwrap-0.6.1-ubuntu0.3-maxargs16384', 'sha256': '7983e8f9ac3c68f072b4ea7884f4d3ce87c2086a1198412649663614113fc3f4'}
def test_old_system_binary_rejected_by_production_pin(fixture,monkeypatch):
 monkeypatch.setattr(m,'EXPECTED_BUBBLEWRAP',PRODUCTION_BUBBLEWRAP)
 with pytest.raises(RuntimeError,match='Explicit pinned control'):run(fixture)
def test_exact_hash_in_expected_pin_cannot_change(fixture,monkeypatch):
 wrong=dict(fixture[0]['bubblewrap']);wrong['sha256']='0'*64;monkeypatch.setattr(m,'EXPECTED_BUBBLEWRAP',wrong)
 with pytest.raises(RuntimeError,match='Explicit pinned control'):run(fixture)
