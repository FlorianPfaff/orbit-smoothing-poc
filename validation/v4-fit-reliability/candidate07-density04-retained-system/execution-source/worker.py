"""Two bounded saved-factor actions using the previously qualified runtime."""
import sys
if not (sys.flags.isolated and sys.flags.no_site and sys.flags.no_user_site and sys.flags.dont_write_bytecode) or 'site' in sys.modules:
    raise RuntimeError('Require isolated Python -I -S -B')
from pathlib import Path
import hashlib
import importlib.util
import importlib.machinery
import json
import os
import traceback
import unittest

ROOT=Path('/home/florianpfaff/codex-runs/orbit-density-retained-qr11-20261027-01')
SOURCE=ROOT/'source'
PYTHON=Path('/home/florianpfaff/codex-runs/orbit-poc-20261013/env/bin/python')
BOOT='95156dd4-0d4c-499d-a214-8883a2d650fa'
FIXED={'provenance/qualified-isolated-suite.py':'dd530f1344a88bff3eb9e55dbbe97d82f20cb58fff8f8641a6dbcb775a81b041',
       'provenance/runtime.sha256':'dd15f70ca65b3c6409aef1c461e877a0892d2b7771cb6ba0deed73ef0582010c',
       'provenance/runtime-links.txt':'bd05218976dac6800a60289c31b01ec35078f194074e239b328fa83f6fa41f1e',
       'startup_probe_guard.py':'8e6f6e020b7fe2ff775b057af7c9ebf3588054fae8ab712701a5c8310a37e789'}

def need(ok,message):
    if not ok:raise RuntimeError(message)

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    need(spec is not None and spec.loader is not None,'module unavailable')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

def ledger(path,sha):
    need(digest(path)==sha,'ledger changed');result={}
    for line in path.read_text().splitlines():
        value,name=line.split('  ',1);relative=Path(name);file=path.parent/relative
        need(len(value)==64 and all(c in '0123456789abcdef' for c in value) and not relative.is_absolute() and '..' not in relative.parts and name==relative.as_posix(),'invalid ledger')
        need(str(file) not in result and file.is_file() and not file.is_symlink() and file.resolve(strict=True)==file and digest(file)==value,'source changed: '+name)
        result[str(file)]=value
    result[str(path)]=sha;return result

def ids(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from ids(item)
        else:yield item.id()

def main():
    need(len(sys.argv)==5 and sys.argv[1] in ('qualify','analyze'),'action and exact source/control/review digests required')
    mode,source_sha,control_sha,review_sha=sys.argv[1:]
    job=ROOT/('qualification01' if mode=='qualify' else 'analysis01')
    need(job.is_dir() and job.resolve(strict=True)==job and not (job/'worker-result.json').exists(),'fresh canonical output required')
    result={'schema':'density-retained-isolated-action-v1','action':mode,'status':'failed','source_sha256':source_sha,'controls_sha256':control_sha,
            'review_sha256':review_sha,'native_runs':0,'covariance_authority':False,'release_authority':False}
    runtime=None;pins=None;expected=None;guard=None
    try:
        source_pins=ledger(SOURCE/'inputs.sha256',source_sha)
        need({str(p) for p in SOURCE.rglob('*') if p.is_file() or p.is_symlink()}==set(source_pins),'source membership differs')
        controls=ledger(ROOT/'controls.sha256',control_sha)
        for name,sha in FIXED.items():need(controls.get(str(ROOT/name))==sha,'qualified helper differs')
        review_path=ROOT/('source-review.json' if mode=='qualify' else 'qualification-review.json')
        need(digest(review_path)==review_sha,'actual review identity differs')
        review=json.loads(review_path.read_text())
        need(review.get('source_sha256')==source_sha and review.get('controls_sha256')==control_sha and review.get('approved_action')==mode,'review scope differs')
        if mode=='analyze':
            q=ROOT/'qualification01/worker-result.json';s=ROOT/'qualification01/supervisor.json'
            need(review.get('qualification_result_sha256')==digest(q) and review.get('qualification_supervisor_sha256')==digest(s),'actual qualification attribution differs')
            prior=json.loads(q.read_text());sup=json.loads(s.read_text())
            need(prior['status']=='passed' and prior['tests_run']==9 and prior['source_runtime_posthashed'] is True and sup['status']=='complete' and sup['returncode']==0 and sup['cleanup']['verified'] is True,'actual qualification missing')
        runtime=load('qualified_runtime_snapshot',ROOT/'provenance/qualified-isolated-suite.py')
        need(sys.executable==str(PYTHON) and sys.version_info[:3]==(3,11,15) and os.getuid()==1002 and os.uname().nodename=='workstation1' and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BOOT,'runtime host differs')
        need(os.sched_getaffinity(0)=={127} and os.getpriority(os.PRIO_PROCESS,0)==19,'CPU admission differs')
        expected_env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTHONHASHSEED':'0',
                      **{key:'1' for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','GOTO_NUM_THREADS')},'TMPDIR':str(job/'tmp'),'PWD':str(ROOT)}
        need(dict(os.environ)==expected_env,'worker environment differs')
        pins=runtime.read_pins(ROOT/'provenance/runtime.sha256');pins.update(source_pins);pins.update(controls)
        for name,sha in pins.items():need(digest(name)==sha,'runtime/source prehash differs: '+name)
        for line in (ROOT/'provenance/runtime-links.txt').read_text().splitlines():
            name,target=line.split(' -> ',1);need(Path(name).is_symlink() and os.readlink(name)==target,'runtime alias differs')
        base=PYTHON.resolve(strict=True).parent.parent;stdlib=base/'lib/python3.11';zip_path=base/'lib/python311.zip'
        need(len(sys.path)==3 and sys.path[0]==str(zip_path) and not zip_path.exists() and [Path(p).resolve(strict=True) for p in sys.path[1:]]==[stdlib,stdlib/'lib-dynload'],'isolated paths differ')
        expected=[str(stdlib),str(stdlib/'lib-dynload'),str(SOURCE),str(SOURCE/'tests'),str(SOURCE/'vendor'),str(SOURCE/'vendor/production'),str(PYTHON.parent.parent/'lib/python3.11/site-packages')]
        sys.path[:]=expected
        class SelectedImports:
            def find_spec(self,fullname,path=None,target=None):
                if fullname=='_sysconfigdata__linux_x86_64-linux-gnu':
                    file=stdlib/'_sysconfigdata__linux_x86_64-linux-gnu.py';sha='370767023c70ac6b2115ba239a593cf87b3b47bc624edaf3a2b386ad01e7aeff'
                    spec=importlib.machinery.PathFinder.find_spec(fullname,[str(stdlib)],target)
                    need(spec is not None and spec.origin and Path(spec.origin).resolve(strict=True)==file and pins.get(str(file))==sha and digest(file)==sha,'generated stdlib origin differs');return spec
                top=fullname.partition('.')[0]
                if top not in sys.stdlib_module_names and top not in {'numpy','scipy','retained_analysis','selected_terminal_audit','orbit_poc','test_retained_analysis','startup_probe_guard'}:raise ImportError('unselected import: '+fullname)
                return None
        sys.meta_path.insert(0,SelectedImports())
        guard_module=load('startup_probe_guard',ROOT/'startup_probe_guard.py')
        guard=guard_module.StartupProbeGuard(expected_env,lambda:dict(os.environ),lambda:False,lambda:None)
        sys.addaudithook(guard.audit)  # Never opened: no hardware probe or child processes.
        import numpy,scipy,scipy.linalg
        need(numpy.__version__=='1.26.4' and scipy.__version__=='1.15.3','scientific versions differ')
        runtime.write_new(job/'loaded-before.json',runtime.snapshot(pins,expected,'before-operation'))
        if mode=='qualify':
            module=load('test_retained_analysis',SOURCE/'tests/test_retained_analysis.py');suite=unittest.defaultTestLoader.loadTestsFromModule(module)
            actual_ids=sorted(ids(suite));need(actual_ids==(SOURCE/'expected-test-ids.txt').read_text().splitlines() and len(set(actual_ids))==9,'nine exact IDs required')
            result['test_ids']=actual_ids
            runtime.write_new(job/'loaded-discovery.json',runtime.snapshot(pins,expected,'discovery'))
            run=unittest.TextTestRunner(verbosity=2).run(suite)
            result.update(tests_run=run.testsRun,failures=len(run.failures),errors=len(run.errors),skips=len(run.skipped),expected_failures=len(run.expectedFailures),unexpected_successes=len(run.unexpectedSuccesses),failed_test_ids=[t.id() for t,_ in run.failures+run.errors])
            need(run.wasSuccessful() and run.testsRun==9 and not run.skipped and not run.expectedFailures and not run.unexpectedSuccesses,'focused qualification failed')
        else:
            import retained_analysis
            sys.argv=[str(SOURCE/'retained_analysis.py'),'--input-root',str(ROOT/'inputs'),'--output',str(job/'result.json')]
            code=retained_analysis.main();result['analysis_exitcode']=code;result['analysis_result_sha256']=digest(job/'result.json')
            need(code==0,'saved retained-factor check failed')
        need(not guard.events and not guard.active and guard.allowed==0,'process-policy event occurred')
        runtime.write_new(job/'loaded-after.json',runtime.snapshot(pins,expected,'after-operation'))
        result['status']='passed'
    except BaseException as error:
        result.update(status='failed',error=repr(error),traceback=traceback.format_exc());traceback.print_exc()
    finally:
        if guard is not None:result['process_policy_events']=guard.events
        try:
            need(runtime is not None and pins is not None and expected is not None,'incomplete runtime verification')
            ledger(SOURCE/'inputs.sha256',source_sha);ledger(ROOT/'controls.sha256',control_sha)
            need(digest(review_path)==review_sha,'review changed')
            for name,sha in pins.items():need(digest(name)==sha,'runtime/source posthash differs: '+name)
            for line in (ROOT/'provenance/runtime-links.txt').read_text().splitlines():
                name,target=line.split(' -> ',1);need(Path(name).is_symlink() and os.readlink(name)==target,'runtime alias changed')
            runtime.write_new(job/'loaded-final.json',runtime.snapshot(pins,expected,'final-posthash'))
            result['source_runtime_posthashed']=True
        except BaseException as error:result.update(status='failed',source_runtime_posthashed=False,posthash_error=repr(error))
        with (job/'worker-result.json').open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
