"""Run the five frozen pure binding methods without modifying their bodies."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = Path('/mnt/d/orbit-v41-recovery02/candidate07-density04-undamped-objective-probe01/preparation01')
SCRATCH = Path('/home/emper/orbit-density04-undamped-probe-fixtures02')

def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())

def source_identity(plan):
    rows=[]
    for key, root in (('probe_ledger',SOURCE),('control_ledger',HERE)):
        pin=plan[key]; ledger=root/'inputs.sha256'
        if pin['path']!=str(ledger) or hashlib.sha256(ledger.read_bytes()).hexdigest()!=pin['sha256']:
            raise ValueError('Wrong source/control ledger')
        paths=[]
        for line in ledger.read_text().splitlines():
            sha,relative=line.split('  ',1);path=root/relative
            if path.resolve()!=path or not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
                raise ValueError('Changed or aliased fixture source')
            paths.append(str(path));rows.append({'path':str(path),'sha256':sha})
        actual={str(p) for p in root.rglob('*') if p.is_file() or p.is_symlink()}
        if len(paths)!=len(set(paths)) or actual!={str(ledger),*paths}:raise ValueError('Source membership differs')
    return rows

class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.started_ids=[]; self.success_ids=[]
    def startTest(self, test): self.started_ids.append(test.id()); super().startTest(test)
    def addSuccess(self, test): self.success_ids.append(test.id()); super().addSuccess(test)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--plan-sha256',required=True); args=parser.parse_args()
    if hashlib.sha256(args.plan.read_bytes()).hexdigest()!=args.plan_sha256: raise ValueError('Changed plan')
    plan=json.loads(args.plan.read_text()); start=time.monotonic()
    report={'status':'failed','expected_ids':plan['expected_ids'],'native_gnss_runs':0,
            'covariance_authority':False,'release_authority':False}
    forbidden=[];before=None
    try:
        if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
            raise ValueError('Required -I -S -B absent')
        if sys.pycache_prefix != str(SCRATCH/'pycache'): raise ValueError('Fresh bytecode-cache prefix required')
        if os.getcwd()!=str(SCRATCH) or os.environ!=dict(plan['environment'],PWD=str(SCRATCH)):
            raise ValueError('Worker context differs')
        if os.sched_getaffinity(0)!={4}: raise ValueError('Worker CPU affinity differs')
        before=source_identity(plan)
        if plan['expected_ids']!=(SOURCE/'expected-test-ids.txt').read_text().splitlines():
            raise ValueError('Changed exact method inventory')
        save(SCRATCH/'worker-context.json', {'argv':sys.argv,'executable':sys.executable,
             'environment':dict(os.environ),'cwd':os.getcwd(),'affinity':sorted(os.sched_getaffinity(0)),
             'pid':os.getpid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
             'python_version':sys.version,'isolated':sys.flags.isolated,'no_site':sys.flags.no_site,
             'bytecode_disabled':sys.flags.dont_write_bytecode,'pycache_prefix':sys.pycache_prefix})
        def guard(event,args):
            blocked=(event.startswith(('subprocess.','os.exec','os.spawn','os.posix_spawn','ctypes.'))
                     or event in ('os.system','os.fork','os.forkpty','os.kill','os.killpg')
                     or (event=='import' and args and args[0].split('.')[0] in ('numpy','scipy','psutil','orbit_poc')))
            if blocked:
                forbidden.append({'event':event,'import_name':args[0] if event=='import' else None})
                raise RuntimeError('Pure fixture process/FFI/signal/scientific import blocked')
        sys.addaudithook(guard)
        spec=importlib.util.spec_from_file_location('test_probe',SOURCE/'tests/test_probe.py')
        module=importlib.util.module_from_spec(spec); sys.modules['test_probe']=module
        spec.loader.exec_module(module)
        suite=unittest.defaultTestLoader.loadTestsFromModule(module)
        def flatten(tests):
            for test in tests:
                if isinstance(test,unittest.TestSuite): yield from flatten(test)
                else: yield test.id()
        actual=list(flatten(suite))
        if len(actual)!=5 or sorted(actual)!=sorted(plan['expected_ids']): raise ValueError('Exact method inventory differs')
        save(SCRATCH/'discovery.json',{'ids':actual,'source':str(SOURCE),'module':module.__file__})
        with (SCRATCH/'unittest.log').open('x') as stream:
            result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
        report.update(tests_run=result.testsRun,started_ids=result.started_ids,success_ids=result.success_ids,
            failures=[{'id':x.id(),'traceback':text} for x,text in result.failures],
            errors=[{'id':x.id(),'traceback':text} for x,text in result.errors],
            skips=[{'id':x.id(),'reason':reason} for x,reason in result.skipped],
            expected_failures=[{'id':x.id(),'traceback':text} for x,text in result.expectedFailures],
            unexpected_successes=[x.id() for x in result.unexpectedSuccesses])
        if result.wasSuccessful() and result.testsRun==5 and not result.skipped and not result.expectedFailures and not forbidden:
            report['status']='passed'
    except BaseException as error: report['error']=repr(error)
    finally:
        report['forbidden_events']=forbidden
        if before is not None:
            try:
                if source_identity(plan)!=before:raise ValueError('Source/control bytes changed')
                report['source_control_bytes_unchanged']=True
            except BaseException as error:
                report.update(status='failed',posthash_error=repr(error),source_control_bytes_unchanged=False)
        report['elapsed_seconds']=time.monotonic()-start
        save(SCRATCH/'fixture-result.json',report)
    return 0 if report['status']=='passed' else 1

if __name__=='__main__': raise SystemExit(main())
