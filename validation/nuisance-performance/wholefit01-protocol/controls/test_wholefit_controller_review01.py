"""Independent injected control tests; never run a native or scientific backend."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

import pytest

BASE = Path('/home/emper/orbit-nuisance-performance/control')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True))
    return {'path': str(path), 'sha256': digest(path)}


@pytest.fixture
def context(tmp_path, monkeypatch):
    controller = module('review_wholefit_controller', BASE/'run_wholefit01.py')
    worker = module('review_wholefit_worker', BASE/'wholefit_worker01.py')
    source = tmp_path/'source'; source.mkdir(); (source/'src').mkdir()
    marker = source/'identity'; marker.write_text('source')
    jobs = []
    for cache in (1, 0):
        request = save(tmp_path/f'template-{cache}.json', {'id':f'cache{cache}', 'cache':cache, 'nuisance_performance_cache':cache})
        jobs.append({'cache':cache,'name':f'cache{cache}','request':request})
    env = {'ORBIT_POC_NUISANCE_PERFORMANCE':'1','OPENBLAS_NUM_THREADS':'1',
           'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1',
           'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
    frozen = {'schema':'orbit-poc-nuisance-wholefit-freeze-v1','root':str(tmp_path),
              'source_root':str(source),'host':os.uname().nodename,
              'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'cpu':0,'runner':{'path':str(BASE/'run_wholefit01.py'), 'sha256':digest(BASE/'run_wholefit01.py')},
              'worker':{'path':str(BASE/'wholefit_worker01.py'), 'sha256':digest(BASE/'wholefit_worker01.py')},
              'python':{'path':sys.executable},'jobs':jobs,'environment':env,
              'wall_time_seconds':7200.,'maximum_process_tree_rss_bytes':8*1024**3,
              'minimum_free_output_bytes':16*1024**3,'reserve_bytes':8*1024**3,
              'pinned_files':[{'path':str(marker),'sha256':digest(marker)},*[j['request'] for j in jobs]]}
    freeze = tmp_path/'freeze.json'; save(freeze,frozen)
    calls=[]
    complete={'status':'complete','converged':True,'covariance_valid':True,
              'strict_nuisance_converged':True,
              'strict_final_correction':{'fresh_undamped':True}}
    behavior={'measured':{'status':'complete','returncode':0,'owned_process_group_cleaned':True},
              'result':complete}
    def fake_run_owned(argv, **kwargs):
        calls.append((argv,kwargs))
        if behavior.get('raise'):raise behavior['raise']
        output=Path(argv[6]);result=behavior.get('result')
        if result is not None:save(output,result)
        measured=dict(behavior['measured']);save(kwargs['receipt_path'],measured)
        if behavior.get('mutate'):behavior['mutate']()
        return measured
    supervisor=types.ModuleType('orbit_poc.segmented.supervisor');supervisor.run_owned=fake_run_owned
    monkeypatch.setitem(sys.modules,'orbit_poc.segmented.supervisor',supervisor)
    gate_calls=[]
    def strict_gate(result, request):
        gate_calls.append((result,request))
        if not all(result.get(k) is True for k in ('converged','covariance_valid','strict_nuisance_converged')):
            raise ValueError('injected strict gate rejects incomplete outcome')
        return True
    report=types.ModuleType('orbit_poc.segmented.report');report.strict_result=strict_gate
    monkeypatch.setitem(sys.modules,'orbit_poc.segmented.report',report)
    monkeypatch.setattr(controller,'admission',lambda f:{'admitted':True})
    def run():
        monkeypatch.setattr(sys,'argv',['run_wholefit01.py','--freeze',str(freeze),'--freeze-sha256',digest(freeze)])
        return controller.main()
    return types.SimpleNamespace(root=tmp_path,controller=controller,worker=worker,source=source,
        marker=marker,freeze=freeze,frozen=frozen,calls=calls,behavior=behavior,run=run,complete=complete,gate_calls=gate_calls)


def test_wholefit_environment_cache_order_and_limits(context,monkeypatch):
    x=context
    monkeypatch.setenv('ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS','1')
    monkeypatch.setenv('ORBIT_POC_NUISANCE_INTERPOLATION_CACHE','wrong')
    monkeypatch.setenv('LD_PRELOAD','unfrozen')
    monkeypatch.setenv('PYTHONPATH','unfrozen')
    x.run()
    assert len(x.calls)==2
    for cache,(argv,kw) in zip((1,0),x.calls):
        assert argv[7]==str(cache)
        assert kw['env']['ORBIT_POC_NUISANCE_INTERPOLATION_CACHE']==str(cache)
        assert kw['env']['ORBIT_POC_NUISANCE_PERFORMANCE']=='1'
        assert set(k for k in kw['env'] if k.startswith('ORBIT_POC_'))=={
            'ORBIT_POC_NUISANCE_PERFORMANCE','ORBIT_POC_NUISANCE_INTERPOLATION_CACHE'}
        assert 'LD_PRELOAD' not in kw['env'] and 'PYTHONPATH' not in kw['env']
        assert kw['timeout_seconds']==7200 and kw['max_process_tree_rss_bytes']==8*1024**3
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
            assert kw['env'][key]=='1'
    assert json.loads((x.root/'execution-complete.json').read_text())['all_attempts_executed']
    assert len(x.gate_calls)==2


@pytest.mark.parametrize('missing',['converged','covariance_valid','strict_nuisance_converged'])
def test_inconsistent_complete_fails_closed_preserving_raw_result(context,missing):
    x=context;x.behavior['result']=dict(x.complete);x.behavior['result'].pop(missing);x.run()
    assert len(x.gate_calls)==2
    for cache in (1,0):
        assert json.loads((x.root/f'cache{cache}'/'worker-result.json').read_text())['status']=='complete'
        result=json.loads((x.root/f'cache{cache}'/'result.json').read_text())
        assert result['status']=='failed' and result['reported_worker_status']=='complete'


@pytest.mark.parametrize('status',['failed','timeout','unresolved_rank','invalid_covariance'])
def test_numerical_failure_not_promoted_by_process_exit_zero(context,status):
    x=context;x.behavior['result']={'status':status,'converged':False,'covariance_valid':False}
    x.run()
    for cache in (1,0):assert json.loads((x.root/f'cache{cache}'/'result.json').read_text())['status']==status


@pytest.mark.parametrize('status',['timeout','memory_limit','disk_limit','interrupted'])
def test_harness_limit_wins_and_interrupt_stops_next_job(context,status):
    x=context;x.behavior['measured'].update(status=status,returncode=1)
    x.run()
    result=json.loads((x.root/'cache1'/'result.json').read_text())
    assert result['status']==status and result['converged'] is False and result['covariance_valid'] is False
    assert len(x.calls)==(1 if status=='interrupted' else 2)
    assert (x.root/'execution-stopped.json').exists()==(status=='interrupted')


def test_unclean_ownership_stops_second_job(context):
    x=context;x.behavior['measured']['owned_process_group_cleaned']=False;x.run()
    assert len(x.calls)==1
    assert json.loads((x.root/'cache1'/'result.json').read_text())['status']=='failed'
    assert (x.root/'execution-stopped.json').exists()


@pytest.mark.parametrize('change',['input','request','runner','freeze_digest'])
def test_identity_changes_block_before_run(context,monkeypatch,change):
    x=context
    if change=='input':x.marker.write_text('changed')
    elif change=='request':Path(x.frozen['jobs'][0]['request']['path']).write_text('{}')
    elif change=='runner':x.frozen['runner']['sha256']='0'*64;save(x.freeze,x.frozen)
    if change=='freeze_digest':
        monkeypatch.setattr(sys,'argv',['run','--freeze',str(x.freeze),'--freeze-sha256','0'*64])
        with pytest.raises(RuntimeError):x.controller.main()
    else:
        with pytest.raises(RuntimeError):x.run()
    assert not x.calls and not (x.root/'launch.json').exists()


def test_existing_output_is_preserved_and_rejected(context):
    x=context;directory=x.root/'cache1';directory.mkdir();old=directory/'partial';old.write_text('preserve')
    with pytest.raises(RuntimeError,match='already exists'):x.run()
    assert old.read_text()=='preserve' and not x.calls


def test_existing_launch_never_restarts(context):
    x=context;(x.root/'launch.json').write_text('original')
    with pytest.raises(RuntimeError,match='no automatic resume'):x.run()
    assert (x.root/'launch.json').read_text()=='original' and not x.calls


def test_input_mutation_after_attempt_preserved_and_stops(context):
    x=context;x.behavior['mutate']=lambda:x.marker.write_text('changed');x.run()
    assert len(x.calls)==1 and (x.root/'cache1'/'result.json').exists()
    assert not json.loads((x.root/'cache1'/'post-input-check.json').read_text())['verified']
    assert (x.root/'execution-stopped.json').exists()


def test_supervisor_interruption_leaves_no_replaceable_output(context):
    x=context;x.behavior['raise']=KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):x.run()
    assert len(x.calls)==1 and (x.root/'launch.json').exists() and (x.root/'cache1'/'request.json').exists()
    with pytest.raises((RuntimeError,BlockingIOError)):x.run()
    assert len(x.calls)==1


@pytest.mark.parametrize('cache',[0,1])
def test_worker_effective_environment_and_full_backend(context,monkeypatch,cache):
    x=context;job=next(j for j in x.frozen['jobs'] if j['cache']==cache)
    directory=x.root/job['name'];directory.mkdir();request=directory/'request.json';request.write_bytes(Path(job['request']['path']).read_bytes())
    output=directory/'worker-result.json';observed=[]
    backend=types.ModuleType('orbit_poc.segmented.backend')
    backend.fit_job=lambda request,root:observed.append((request,root)) or x.complete
    monkeypatch.setitem(sys.modules,'orbit_poc.segmented.backend',backend)
    for key in list(os.environ):
        if key.startswith('ORBIT_POC_'):monkeypatch.delenv(key)
    for k,v in x.frozen['environment'].items():monkeypatch.setenv(k,v)
    monkeypatch.setenv('ORBIT_POC_NUISANCE_INTERPOLATION_CACHE',str(cache))
    affinity=set()
    monkeypatch.setattr(os,'sched_setaffinity',lambda pid,cpus:affinity.update(cpus))
    monkeypatch.setattr(os,'sched_getaffinity',lambda pid:affinity)
    monkeypatch.setattr(sys,'argv',['worker',str(x.source),str(request),str(output),str(cache),str(x.freeze),digest(x.freeze)])
    x.worker.main()
    assert len(observed)==1 and observed[0][1]==directory
    receipt=json.loads((directory/'effective-environment.json').read_text())
    assert receipt['cache']==cache and receipt['cpu_affinity']==[0]
    assert receipt['environment']['ORBIT_POC_NUISANCE_INTERPOLATION_CACHE']==str(cache)
    assert json.loads(output.read_text())==x.complete


@pytest.mark.parametrize('wrong',['extra_override','cache','thread','request','freeze','output'])
def test_worker_rejects_mismatched_identity_or_env(context,monkeypatch,wrong):
    x=context;job=x.frozen['jobs'][0];directory=x.root/job['name'];directory.mkdir()
    request=directory/'request.json';request.write_bytes(Path(job['request']['path']).read_bytes());output=directory/'worker-result.json'
    for key in list(os.environ):
        if key.startswith('ORBIT_POC_'):monkeypatch.delenv(key)
    for k,v in x.frozen['environment'].items():monkeypatch.setenv(k,v)
    monkeypatch.setenv('ORBIT_POC_NUISANCE_INTERPOLATION_CACHE','1')
    if wrong=='extra_override':monkeypatch.setenv('ORBIT_POC_NUMERICS_SOLVER','other')
    if wrong=='cache':monkeypatch.setenv('ORBIT_POC_NUISANCE_INTERPOLATION_CACHE','0')
    if wrong=='thread':monkeypatch.setenv('OMP_NUM_THREADS','2')
    if wrong=='request':request.write_text('{}')
    if wrong=='output':output=x.root/'elsewhere'/'worker-result.json'
    monkeypatch.setattr(os,'sched_setaffinity',lambda pid,cpus:None)
    monkeypatch.setattr(os,'sched_getaffinity',lambda pid:{0})
    monkeypatch.setattr(sys,'argv',['worker',str(x.source),str(request),str(output),'1',str(x.freeze),'0'*64 if wrong=='freeze' else digest(x.freeze)])
    with pytest.raises(RuntimeError):x.worker.main()
    assert not output.exists()
