"""Fabricated local control tests; never launch native code or access remote hosts."""
import copy,hashlib,importlib.util,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
import pytest
HERE=Path(__file__).parent
LAUNCHER=HERE/'launch_row_trace_d03.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
smoke=module('d03_smoke_test',HERE/'smoke_row_trace_d03.py')
launcher=module('d03_launcher_test',LAUNCHER)
def put(path,value):path.write_text(json.dumps(value));return path

def fixture(root):
    control=root/'control';control.mkdir();source=root/'source';source.mkdir()
    wrapper=control/'wrapper.py';wrapper.write_text('# inert wrapper fixture\n')
    runner=control/'runner.py';runner.write_text('import time\ntime.sleep(60)\n')
    driver=control/'driver.py';driver.write_text('import json\nfrom pathlib import Path\ndef load_execution(p):return json.loads(Path(p).read_text())\ndef admission(e):return {"hostname":e["host"]["hostname"],"boot_id":e["host"]["boot_id"]}\ndef resolved_host_path(p,e):return Path(p)\ndef source_receipt(p):return json.loads((Path(p).parent/"control/freeze.json").read_text())["source"]\n')
    freeze=put(control/'freeze.json',{'source':{'sha256':'774d6d777e1f5caf09b5599a8b469e421327f2e1f962eb75a5af17b0bc8bf8c2','files':{str(k):'0'*64 for k in range(771)}}})
    prior=put(control/'prior.json',{'status':'failed','finished_at':'fixture','final_cleanup':{'verified':True}})
    post=put(control/'post.json',{'status':'completed','finished_at':'fixture','steps':[{'cleanup_verified':True}],'validation_pipeline':pin(prior)})
    profile=control/'profile.xml';profile.write_text('<fixture/>')
    identity=put(control/'identity.json',{'fixture':True})
    prepare=control/'prepare.py';prepare.write_text('import json,hashlib\nfrom pathlib import Path\ndef collect_inputs(p,e,d):return ({"profile":{"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}},{},{"fixture":True})\n')
    e={'paths':{'root':str(root),'control':str(control),'source':str(source),'wrapper':str(wrapper),**{k:str(root/k) for k in smoke.MUTABLE}},'host':{'hostname':'fixture-host','boot_id':'fixture-boot'},'runtime_artifacts':{'control_python':pin(Path(sys.executable))}}
    ep=put(control/'execution.json',e)
    plan={'schema':'orbit-poc-diagnostic-row-trace-plan-v2','runner':pin(runner),'execution':pin(ep),'driver':pin(driver),'source_freeze':pin(freeze),'helpers':{'wrapper':pin(wrapper),'prepare':pin(prepare),'input_identity':pin(identity)},'inputs':{'profile':pin(profile)},'input_links':{},'prior_pipeline':pin(prior),'prior_postprocess':pin(post),'last_generation':4}
    pp=put(control/'plan.json',plan)
    hp=control/'proof-helper.py';hp.write_text('# inert evidence fixture\n')
    proof={'schema':'orbit-poc-d03-namespace-smoke-v1','passed':True,'execution':pin(ep),'plan':pin(pp),'cleanup':{'verified':True},'production_mutable_directories_absent':True,'scientific_validation_complete':False,'helper':pin(hp),'upstream_helper':pin(hp),'upstream_reference':pin(hp),'admission':e['host']}
    sp=put(control/'smoke.json',proof)
    return {'root':root,'control':control,'source':source,'runner':runner,'ep':ep,'pp':pp,'sp':sp,'e':e,'plan':plan,'proof':proof}

def args(f):return ['--execution',str(f['ep']),'--execution-sha256',sha(f['ep']),'--plan',str(f['pp']),'--plan-sha256',sha(f['pp']),'--smoke',str(f['sp']),'--smoke-sha256',sha(f['sp'])]
def namespace(f):
    from types import SimpleNamespace
    return SimpleNamespace(execution=f['ep'],execution_sha256=sha(f['ep']),plan=f['pp'],plan_sha256=sha(f['pp']),smoke=f['sp'],smoke_sha256=sha(f['sp']))
def proc(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split();return {'pid':pid,'start_ticks':int(fields[19]),'state':fields[0]}
    except FileNotFoundError:return None

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='d03-prelaunch-fabricated-',dir='@TEMP_ROOT@');self.f=fixture(Path(self.tmp.name));self.root=self.f['root'];self.control=self.f['control'];self.heartbeat=self.root/'heartbeat';self.started=self.root/'started.json';self.identities=[]
        self.f['runner'].write_text('import json,os,signal,time\nfrom pathlib import Path\nPath('+repr(str(self.started))+').write_text(json.dumps({"pid":os.getpid(),"sid":os.getsid(0),"sighup_ignored":signal.getsignal(signal.SIGHUP)==signal.SIG_IGN}))\nwhile True:\n Path('+repr(str(self.heartbeat))+').write_text(str(time.monotonic()))\n time.sleep(.02)\n')
        self.f['plan']['runner']=pin(self.f['runner']);put(self.f['pp'],self.f['plan']);self.f['proof']['plan']=pin(self.f['pp']);put(self.f['sp'],self.f['proof'])
    def tearDown(self):
        r=self.control/'diagnostic-launch.json'
        if r.exists():self.identities.append(json.loads(r.read_text())['driver_process'])
        if self.started.exists():
            p=proc(json.loads(self.started.read_text())['pid'])
            if p:self.identities.append(p)
        for ident in self.identities:
            p=proc(ident['pid'])
            if p and p['start_ticks']==ident['start_ticks'] and p['state']!='Z':os.kill(p['pid'],signal.SIGTERM)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if not any((p:=proc(i['pid'])) and p['start_ticks']==i['start_ticks'] and p['state']!='Z' for i in self.identities):break
            time.sleep(.01)
        self.tmp.cleanup()
    def call(self,runner=None,argv=None):
        if runner:
            script=self.root/'test_runner.py';script.write_text('import importlib.util,sys\nspec=importlib.util.spec_from_file_location("m",'+repr(str(LAUNCHER))+');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n'+runner)
        else:script=LAUNCHER
        return subprocess.run([sys.executable,str(script),*(argv or args(self.f))],capture_output=True,text=True,timeout=10,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    def alive(self):
        end=time.monotonic()+5
        while not self.started.exists() and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(self.started.exists());data=json.loads(self.started.read_text())
        while not self.heartbeat.exists() and time.monotonic()<end:time.sleep(.01)
        before=self.heartbeat.read_text();time.sleep(.06);self.assertNotEqual(before,self.heartbeat.read_text());self.assertNotEqual(proc(data['pid'])['state'],'Z');return data
    def test_detached_success_and_no_implicit_repeat(self):
        r=self.call();self.assertEqual(r.returncode,0,r.stderr);receipt=json.loads((self.control/'diagnostic-launch.json').read_text());data=self.alive()
        self.assertEqual(data['pid'],data['sid']);self.assertTrue(data['sighup_ignored']);self.assertEqual(receipt['argv'],receipt['observed_argv']);self.assertEqual(receipt['runner'],self.f['plan']['runner']);self.assertFalse(receipt['scientific_validation_complete'])
        before=(self.control/'diagnostic-launch.json').read_bytes();again=self.call();self.assertNotEqual(again.returncode,0);self.assertIn('no implicit retry',again.stderr);self.assertEqual(before,(self.control/'diagnostic-launch.json').read_bytes());self.alive()
    def test_broken_stdout_does_not_rollback_durable_handoff(self):
        r=self.call('class Broken:\n def write(self,v):raise BrokenPipeError("fixture")\n def flush(self):raise BrokenPipeError("fixture")\nsys.stdout=Broken()\nm.main()\n');self.assertEqual(r.returncode,0,r.stderr);self.alive();self.assertFalse((self.control/'diagnostic-launch-failure.json').exists())
    def test_sighup_does_not_kill_owned_detached_runner(self):
        r=self.call();self.assertEqual(r.returncode,0,r.stderr);data=self.alive();os.kill(data['pid'],signal.SIGHUP);self.alive()
    def test_receipt_failure_terminates_only_child_no_descendant_claim(self):
        r=self.call('real=m.write_new\ndef fail(p,v):\n if p.name=="diagnostic-launch.json":raise OSError("fixture receipt failure")\n return real(p,v)\nm.write_new=fail\nm.main()\n');self.assertNotEqual(r.returncode,0);f=json.loads((self.control/'diagnostic-launch-failure.json').read_text());self.assertFalse(f['descendant_cleanup_verified']);self.assertIsNotNone(f['returncode']);p=proc(f['driver_pid']);self.assertTrue(p is None or p['state']=='Z')
    def test_wrong_plan_hash_rejects_before_launch(self):
        argv=args(self.f);argv[argv.index('--plan-sha256')+1]='0'*64;r=self.call(argv=argv);self.assertNotEqual(r.returncode,0);self.assertIn('Sealed plan mismatch',r.stderr);self.assertFalse(self.started.exists())
    def test_changed_runner_hash_rejects_before_launch(self):
        self.f['runner'].write_text(self.f['runner'].read_text()+'#changed');r=self.call();self.assertNotEqual(r.returncode,0);self.assertFalse(self.started.exists())
    def test_failed_flush_preserves_durable_handoff(self):
        r=self.call('class Broken:\n def write(self,v):return len(v)\n def flush(self):raise OSError("fixture")\nsys.stdout=Broken()\nm.main()\n');self.assertEqual(r.returncode,0,r.stderr);self.alive()

@pytest.mark.parametrize('which',['execution_sha256','plan_sha256','smoke_sha256'])
def test_wrong_direct_hash(tmp_path,which):
    f=fixture(tmp_path);a=namespace(f);setattr(a,which,'0'*64)
    with pytest.raises(RuntimeError,match='mismatch'):launcher.validated(a)
@pytest.mark.parametrize('key',['passed','production_mutable_directories_absent'])
def test_failed_smoke_status(tmp_path,key):
    f=fixture(tmp_path);f['proof'][key]=False;put(f['sp'],f['proof'])
    with pytest.raises(RuntimeError,match='proof'):launcher.validated(namespace(f))
def test_wrong_smoke_host(tmp_path):
    f=fixture(tmp_path);f['proof']['admission']={'hostname':'other','boot_id':'fixture-boot'};put(f['sp'],f['proof'])
    with pytest.raises(RuntimeError,match='host/boot'):launcher.validated(namespace(f))
def test_smoke_execution_swap(tmp_path):
    f=fixture(tmp_path);f['proof']['execution']['sha256']='0'*64;put(f['sp'],f['proof'])
    with pytest.raises(RuntimeError,match='attribution'):launcher.validated(namespace(f))
def test_unclean_cleanup(tmp_path):
    f=fixture(tmp_path);f['proof']['cleanup']['verified']=False;put(f['sp'],f['proof'])
    with pytest.raises(RuntimeError,match='proof'):launcher.validated(namespace(f))
def test_changed_proof_helper(tmp_path):
    f=fixture(tmp_path);Path(f['proof']['helper']['path']).write_text('changed')
    with pytest.raises(RuntimeError,match='artifact'):launcher.validated(namespace(f))
def test_existing_output_refuses_launch(tmp_path):
    f=fixture(tmp_path);Path(f['e']['paths']['run']).mkdir()
    with pytest.raises(RuntimeError,match='Fresh production'):launcher.validated(namespace(f))
def test_smoke_plan_validation_reuses_driver_source_input_checks(tmp_path):
    f=fixture(tmp_path);e,p,d=smoke.validate(f['ep'],sha(f['ep']),f['pp'],sha(f['pp']));assert e==f['e'] and p==f['plan']
def test_smoke_source_identity_wrong(tmp_path):
    f=fixture(tmp_path);fp=Path(f['plan']['source_freeze']['path']);x=json.loads(fp.read_text());x['source']['sha256']='0'*64;put(fp,x);f['plan']['source_freeze']=pin(fp);put(f['pp'],f['plan'])
    with pytest.raises(RuntimeError,match='Wrong candidate'):smoke.validate(f['ep'],sha(f['ep']),f['pp'],sha(f['pp']))
def test_smoke_remaps_only_five_staging_paths(tmp_path):
    f=fixture(tmp_path);before=copy.deepcopy(f['e']);changed=smoke.derive(f['e'],tmp_path/'staging/smoke')
    assert f['e']==before and {k for k in before['paths'] if before['paths'][k]!=changed['paths'][k]}==set(smoke.MUTABLE)
    assert all(not Path(before['paths'][k]).exists() for k in smoke.MUTABLE)
@pytest.mark.parametrize('kind',['existing','symlink','outside'])
def test_smoke_output_is_new_owned_staging_child(tmp_path,kind):
    f=fixture(tmp_path);out=tmp_path/'staging/smoke';out.parent.mkdir()
    if kind=='existing':out.mkdir()
    if kind=='symlink':out.symlink_to(tmp_path/'absent')
    if kind=='outside':out=tmp_path/'outside'
    with pytest.raises(RuntimeError,match='staging'):smoke.derive(f['e'],out)
def test_native_commands_absent_from_smoke_inside_program():
    assert 'numpy,scipy,gtsam' in smoke.INSIDE and 'module.check' in smoke.INSIDE and 'ST_RDONLY' in smoke.INSIDE
    assert 'cmake' not in smoke.INSIDE and 'groops --help' not in smoke.INSIDE

@pytest.mark.parametrize('which',['smoke','launch'])
def test_unknown_plan_fields_fail_closed(tmp_path,which):
    f=fixture(tmp_path);f['plan']['unknown']=1;put(f['pp'],f['plan']);f['proof']['plan']=pin(f['pp']);put(f['sp'],f['proof'])
    with pytest.raises(RuntimeError,match='Unknown plan'):
        if which=='smoke':smoke.validate(f['ep'],sha(f['ep']),f['pp'],sha(f['pp']))
        else:launcher.validated(namespace(f))

@pytest.mark.parametrize('signal_number',[signal.SIGTERM,signal.SIGINT])
def test_smoke_interruption_uses_owned_cleanup_and_restores_handlers(tmp_path,signal_number):
    from contextlib import contextmanager
    from types import SimpleNamespace
    calls=[];fired=False
    original={n:signal.getsignal(n) for n in (signal.SIGTERM,signal.SIGINT)}
    class Child:
        returncode=None
        def poll(self):
            nonlocal fired
            if not fired:
                fired=True;os.kill(os.getpid(),signal_number)
            return self.returncode
    class Owned:
        def __init__(self,*args,**kwargs):self.child=Child()
        def observe(self):calls.append('observe')
        def cleanup(self,*,force):calls.append(('cleanup',force));self.child.returncode=-9;return {'verified':True}
    def interrupted(number,frame):raise RuntimeError('fixture signal '+str(number))
    @contextmanager
    def cleanup_signals():
        calls.append('cleanup_guard_enter')
        try:yield
        finally:calls.append('cleanup_guard_exit')
    d=SimpleNamespace(OwnedCommand=Owned,interrupted=interrupted,cleanup_signals=cleanup_signals)
    status,cleanup,error=smoke.run_owned(d,['inert'],tmp_path,{},tmp_path/'log',limit=1)
    assert status is None and cleanup['verified'] and 'fixture signal' in error
    assert calls==['cleanup_guard_enter',('cleanup',True),'cleanup_guard_exit']
    assert all(signal.getsignal(n)==v for n,v in original.items())

def test_smoke_cleanup_failure_cannot_pass(tmp_path):
    from contextlib import nullcontext
    from types import SimpleNamespace
    class Owned:
        def __init__(self,*a,**k):self.child=SimpleNamespace(poll=lambda:0,returncode=0)
        def cleanup(self,**kwargs):raise RuntimeError('fixture cleanup failure')
    d=SimpleNamespace(OwnedCommand=Owned,interrupted=lambda *a:None,cleanup_signals=nullcontext)
    status,cleanup,error=smoke.run_owned(d,['inert'],tmp_path,{},tmp_path/'log')
    assert status==0 and cleanup['verified'] is False and 'cleanup failure' in error
