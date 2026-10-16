#!/usr/bin/env python3
"""Recover only preparation startup and handoff with the actual account home."""
import argparse, contextlib, fcntl, hashlib, importlib.util, json, os, pwd, socket, sys
from pathlib import Path
KEYS={'schema','helper','control_python','control_root','host','account','environment','execution','preparation_plan','preparation_pins','helpers','old_smoke','old_probe','smoke','probe','failure_records','resource','global_lock'}
HELPERS={'driver','runner','smoke','launcher'}
ENV_KEYS={'PATH','HOME','PYTHONDONTWRITEBYTECODE'}
def need(ok,msg):
    if not ok: raise RuntimeError(msg)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def checked(item):
    need(isinstance(item,dict) and set(item)=={'path','sha256'},'Exact artifact pin required')
    p=Path(item['path']); need(p.is_absolute() and p.is_file() and not p.is_symlink() and sha(p)==item['sha256'],'Changed artifact: '+str(p)); return p
def read(item): return json.loads(checked(item).read_text())
def load(name,item):
    spec=importlib.util.spec_from_file_location(name,checked(item)); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def canonical(path):
    p=Path(path);need(p.is_absolute() and '..' not in p.parts and p.resolve()==p,'Canonical path required');return p
def exact_live(identity):
    try: f=(Path('/proc')/str(identity['pid'])/'stat').read_text().rsplit(')',1)[1].split()
    except (FileNotFoundError,ProcessLookupError):return False
    return int(f[19])==identity['start_ticks'] and f[0]!='Z'
def environment_for(account,environment,actual=None):
    actual=actual or pwd.getpwuid(os.getuid())
    need(account=={'uid':os.getuid(),'username':actual.pw_name,'home':actual.pw_dir},'Pinned account differs from current passwd account')
    need(set(environment)==ENV_KEYS and environment=={'PATH':'/usr/bin:/bin','HOME':account['home'],'PYTHONDONTWRITEBYTECODE':'1'},'Only exact proper-home environment is allowed')
    canonical(account['home']);return dict(environment)
@contextlib.contextmanager
def controlled_environment(environment):
    old=dict(os.environ)
    try:
        os.environ.clear();os.environ.update(environment);yield
    finally:
        os.environ.clear();os.environ.update(old)
def validate_delta(old_smoke,old_probe,new_smoke,new_probe,root):
    target=str(Path(root)/'staging/preparation-04/startup-02')
    need(new_smoke['output']==target and new_probe['output']==str(Path(target)/'temporary/probe-result'),'Fresh startup02 paths required')
    a=dict(new_smoke);b=dict(old_smoke);a.pop('output');b.pop('output');a.pop('probe_plan');b.pop('probe_plan');need(a==b,'Startup controls differ beyond output/probe pin')
    a=dict(new_probe);b=dict(old_probe);a.pop('output');b.pop('output');need(a==b,'Probe inputs changed')
def check_startup(receipt,plan,live=exact_live):
    need(receipt.get('status')=='passed' and receipt.get('physical_propagations')==0 and receipt.get('benchmark_fits')==0,'Startup must pass without propagation or fits')
    need({k:receipt['plan'][k] for k in ('path','sha256')}==plan['smoke'] and receipt['probe_plan']==plan['probe'] and receipt['execution']==plan['execution'],'Startup attribution differs')
    cleanup=receipt.get('final_cleanup',{});need(cleanup.get('verified') is True and cleanup.get('errors')==[],'Startup cleanup failed')
    for command in cleanup['commands']:
        need(command.get('verified') is True and not command.get('live_owned_processes'),'Startup command cleanup failed')
        for identity in command['identities']:need(not live(identity),'Startup owned process is still live')
    result=read({k:receipt['result'][k] for k in ('path','sha256')})
    need(result.get('status')=='passed' and result.get('physical_propagations')==0 and result.get('benchmark_fits')==0,'Actual startup result failed')
def preserve_handoff(journal,receipt_path):
    path=Path(receipt_path)
    if not path.exists():return False
    journal['preparation_launch']={'path':str(path),'sha256':sha(path)}
    journal['handoff_committed']='unresolved'
    try:
        launched=json.loads(path.read_text())
        need(launched.get('launch_committed') is True,'Launch receipt is not committed')
        journal['handoff_committed']=True
        journal['owned_driver_process']=launched['driver_process']
        return True
    except BaseException as ex:
        journal['handoff_readback_error']=repr(ex)
        return False

def failure_status(journal,error,receipt_path=None):
    if receipt_path is not None:preserve_handoff(journal,receipt_path)
    journal['error']=repr(error)
    if journal.get('handoff_committed'):
        journal['status']='handoff_committed_verification_failed' if journal['handoff_committed'] is True else 'handoff_identity_unresolved'
        journal['recovery_policy']='Preserve the durable launch receipt. Do not relaunch. Inspect the recorded exact PID/start/boot and owned preparation pipeline before any recovery; this adapter does not terminate a committed preparation.'
    else:journal['status']='failed'

def load_plan(path,digest):
    need(sha(path)==digest,'Recovery plan changed');p=json.loads(Path(path).read_text());need(set(p)==KEYS and p['schema']=='orbit-poc-preparation04-proper-home-recovery-v1','Unknown recovery plan')
    for k in ('helper','control_python','execution','preparation_plan','preparation_pins','old_smoke','old_probe','smoke','probe'):checked(p[k])
    need(p['helper']['sha256']==sha(__file__) and p['control_python']['sha256']==sha(Path(sys.executable).resolve()),'Recovery helper or interpreter differs')
    need(set(p['helpers'])==HELPERS,'Exact unchanged helpers required')
    for v in p['helpers'].values():checked(v)
    for v in p['failure_records']:checked(v)
    control=canonical(p['control_root']);need(control.is_dir() and control.name=='recovery-startup02','Separate recovery controls required')
    e=read(p['execution']);old=read(p['old_smoke']);smoke=read(p['smoke']);q=read(p['probe']);prep=read(p['preparation_plan'])
    need(p['host']==e['host']=={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'Host boot differs')
    environment_for(p['account'],p['environment'])
    need(smoke['execution']==p['execution'] and smoke['probe_plan']==p['probe'] and smoke['helper']==p['helpers']['smoke'] and q['helper']==read(p['old_probe'])['helper'],'Unchanged startup helper linkage required')
    validate_delta(old,read(p['old_probe']),smoke,q,e['paths']['root'])
    need(prep['execution']==p['execution'] and prep['driver']==p['helpers']['driver'] and prep['runner']==p['helpers']['runner'],'Preparation linkage differs')
    resource=p['resource'];home_resource=str(Path(p['account']['home'])/'.tudat/resource')
    need(resource['path']==home_resource and {'source':home_resource,'target':home_resource} in e['read_only_bindings'],'Actual home Tudat resource binding missing')
    st=canonical(home_resource).stat();need({k:getattr(st,'st_'+k) for k in ('dev','ino','uid')}==resource['identity'],'Tudat resource identity changed')
    checked(resource['sentinel']);need(resource['sentinel'] in e['runtime_artifacts'].values(),'Tudat sentinel must retain frozen runtime pin')
    lock=canonical(p['global_lock']['path']);st=lock.stat();need({'dev':st.st_dev,'ino':st.st_ino}==p['global_lock']['identity'],'Global lock identity changed')
    need(str(lock)==old['global_lock']==prep['global_lock'],'Original shared lock required')
    return p

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('phase',choices=('startup','launch'));ap.add_argument('--plan',required=True,type=Path);ap.add_argument('--sha256',required=True);ap.add_argument('--startup-sha256');a=ap.parse_args(argv)
    p=load_plan(a.plan,a.sha256);control=Path(p['control_root']);environment=environment_for(p['account'],p['environment']);d=load('proper_home_owned_driver',p['helpers']['driver']);e=d.load_execution(p['execution']['path']);runner=load('proper_home_preparation_runner',p['helpers']['runner']);prep=runner.load_plan(p['preparation_plan']['path'],p['preparation_plan']['sha256']);smokeplan=read(p['smoke']);startup=Path(smokeplan['output'])/'process.json';journal={'schema':'orbit-poc-preparation04-proper-home-recovery-result-v1','phase':a.phase,'status':'checking','plan':{'path':str(a.plan),'sha256':a.sha256},'started_at':d.stamp(),'effective_environment':environment,'physical_propagations_by_recovery':0,'benchmark_fits':0,'release_authorized':False,'handoff_committed':False}
    record=control/(a.phase+'-result.json');need(not record.exists() and not record.is_symlink(),'Preserve prior recovery result')
    def save():d.save(record,journal)
    def guard():
        need(load_plan(a.plan,a.sha256)==p,'Recovery inputs changed')
        freeze=read(prep['source_freeze']);need(d.source_receipt(e['paths']['source'])==freeze['source'],'Frozen source changed')
        config=read(prep['config'])
        for profile in ('segmented_runtime','dense_runtime'):
            for key in ('native','segmented_solver'):
                if key in config[profile]:
                    v=config[profile][key];need(sha(d.resolved_host_path(v['path'],e))==v['sha256'],'Frozen native/solver changed')
        for item in p['failure_records']:
            if Path(item['path']).name=='process.json':
                old=read(item);need(old['status']=='failed' and old['physical_propagations']==0 and old['benchmark_fits']==0,'Failed startup preservation differs')
                for command in old['final_cleanup']['commands']:
                    for identity in command['identities']:need(not exact_live(identity),'Earlier startup process remains live')
        return d.admission(e,[])
    with (control/'recovery.lock').open('a') as local:
        fcntl.flock(local,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with Path(p['global_lock']['path']).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);journal['admission']=guard()
        try:
            if a.phase=='startup':
                need(a.startup_sha256 is None,'Startup cannot inherit a receipt');smoke=load('proper_home_smoke',p['helpers']['smoke']);smoke.inspect(p['smoke']['path'],p['smoke']['sha256']);save()
                with controlled_environment(environment):code=smoke.main(['--plan',p['smoke']['path'],'--sha256',p['smoke']['sha256']])
                need(code==0,'Actual startup failed');value=json.loads(startup.read_text());check_startup(value,p);journal['startup']={'path':str(startup),'sha256':sha(startup)};journal['status']='passed'
            else:
                need(a.startup_sha256 is not None and sha(startup)==a.startup_sha256,'Exact actual startup receipt required');value=json.loads(startup.read_text());check_startup(value,p)
                prior=json.loads((control/'startup-result.json').read_text());need(prior['status']=='passed' and prior['startup']=={'path':str(startup),'sha256':a.startup_sha256} and prior['effective_environment']==environment,'Own startup/environment receipt differs')
                prepcontrol=Path(prep['control_root'])
                for name in ('preparation-launch.json','pipeline.json','preparation-driver.log'):need(not(prepcontrol/name).exists(),'Preserve earlier preparation launch')
                journal['startup']={'path':str(startup),'sha256':a.startup_sha256};save();launcher=load('proper_home_preparation_launcher',p['helpers']['launcher']);oldargv=sys.argv
                try:
                    sys.argv=[p['helpers']['launcher']['path'],'--execution',p['execution']['path'],'--pins',p['preparation_pins']['path'],'--pins-sha256',p['preparation_pins']['sha256']]
                    with controlled_environment(environment):launcher.main()
                finally:sys.argv=oldargv
                need(preserve_handoff(journal,prepcontrol/'preparation-launch.json'),'Durable launch receipt missing');journal['status']='handoff_committed_verification_pending';save();launched=read(journal['preparation_launch']);need(launched['launch_committed'] and exact_live(launched['driver_process']),'Durable preparation handoff missing')
                selected={}
                for item in (Path('/proc')/str(launched['driver_process']['pid'])/'environ').read_bytes().split(b'\0'):
                    key,sep,val=item.partition(b'=')
                    if sep and key.decode() in ENV_KEYS:selected[key.decode()]=val.decode()
                need(selected==environment,'Durable preparation environment differs');journal['preparation_launch']={'path':str(prepcontrol/'preparation-launch.json'),'sha256':sha(prepcontrol/'preparation-launch.json')};journal['observed_driver_environment']=selected;journal['status']='preparation_launched'
        except BaseException as ex:
            failure_status(journal,ex,Path(prep['control_root'])/'preparation-launch.json' if a.phase=='launch' else None);raise
        finally:journal['finished_at']=d.stamp();save()
    print(json.dumps({'status':journal['status'],'result':{'path':str(record),'sha256':sha(record)}}));return 0
if __name__=='__main__':raise SystemExit(main())
