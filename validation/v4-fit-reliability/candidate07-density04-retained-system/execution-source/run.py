"""Admit and supervise one saved-factor action; no native fit or build."""
import sys
if not (sys.flags.isolated and sys.flags.no_site and sys.flags.no_user_site and sys.flags.dont_write_bytecode) or 'site' in sys.modules:
    raise RuntimeError('Require isolated system Python -I -S -B')
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import signal
import traceback

ROOT=Path('/home/florianpfaff/codex-runs/orbit-density-retained-qr11-20261027-01')
SOURCE=ROOT/'source'
ENV={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
PYTHON='/home/florianpfaff/codex-runs/orbit-poc-20261013/env/bin/python'
FIXED={'supervisor.py':'060bc208a5d36631689905563c9e969ae4615299e39e87637f71393b62eed267',
       'qualified_host.py':'15f40502c44c948cdd454a40f52df83f686dad51d386e12f04d3e060e8db543f',
       'provenance/system-runtime-pins.json':'06f38245918e6ed6d31a626d1ca2affbe608ee01355b9ecb47db2653fb3136f7',
       'provenance/qualified-controller-runtime-before.json':'d49dc20ef6c0b1c7af354e02bc3e65b850da83bcdcbd2a63813a9a8670802cd1'}

def need(ok,message):
    if not ok:raise RuntimeError(message)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def save(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);need(spec is not None and spec.loader is not None,'module unavailable')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

def ledger(path,sha):
    need(digest(path)==sha,'ledger changed');result={}
    for line in path.read_text().splitlines():
        value,name=line.split('  ',1);relative=Path(name);file=path.parent/relative
        need(len(value)==64 and all(c in '0123456789abcdef' for c in value) and not relative.is_absolute() and '..' not in relative.parts and name==relative.as_posix(),'invalid ledger')
        need(str(file) not in result and file.is_file() and not file.is_symlink() and file.resolve(strict=True)==file and digest(file)==value,'source changed: '+name)
        result[str(file)]=value
    result[str(path)]=sha;return result

def package_inventory(expected):
    root=Path('/usr/lib/python3/dist-packages/psutil')
    need(root.resolve(strict=True)==root and root.is_dir(),'psutil root changed')
    actual={}
    for path in root.rglob('*'):
        need(not path.is_symlink(),'psutil alias forbidden')
        if path.is_file():actual[str(path)]=digest(path)
    need(actual==expected,'qualified psutil58 tree changed')

def dependencies():
    import ctypes
    host=load('qualified_host',ROOT/'qualified_host.py');host.R=ROOT
    host.verify_known_runtime();need(host.ENV==ENV,'host environment policy changed')
    baseline=json.loads((ROOT/'provenance/qualified-controller-runtime-before.json').read_text())
    expected={name:sha for name,sha in baseline['files'].items() if name.startswith('/usr/lib/python3/dist-packages/psutil/')}
    need(len(expected)==58,'psutil inventory incomplete');package_inventory(expected)
    need('psutil' not in sys.modules,'psutil imported before attribution')
    before=list(sys.path);root=Path('/usr/lib/python3/dist-packages/psutil')
    spec=importlib.util.spec_from_file_location('psutil',root/'__init__.py',submodule_search_locations=[str(root)])
    module=importlib.util.module_from_spec(spec);sys.modules['psutil']=module;spec.loader.exec_module(module)
    need(sys.path==before and 'site' not in sys.modules,'bootstrap changed isolated paths')
    for name,module in list(sys.modules.items()):
        if name=='psutil' or name.startswith('psutil.'):
            path=Path(module.__file__);need(path.resolve(strict=True)==path and expected.get(str(path))==digest(path),'psutil origin differs')
    return host,load('owned_supervisor',ROOT/'supervisor.py'),expected

def main():
    need(len(sys.argv)==5 and sys.argv[1] in ('qualify','analyze'),'action and exact digests required')
    mode,source_sha,controls_sha,review_sha=sys.argv[1:]
    need(ROOT.resolve(strict=True)==ROOT and dict(os.environ)==ENV,'canonical root and exact environment required')
    phase=ROOT/('qualification01' if mode=='qualify' else 'analysis01');phase.mkdir();(phase/'tmp').mkdir()
    result={'schema':'density-retained-supervised-action-v1','action':mode,'status':'failed','source_sha256':source_sha,'controls_sha256':controls_sha,'review_sha256':review_sha,'native_runs':0,'release_authority':False,'covariance_authority':False,'signals_received':[]}
    host=None;before=None;package=None;source_before=None;control_before=None
    review_path=ROOT/('source-review.json' if mode=='qualify' else 'qualification-review.json')
    def interrupted(number,_):result['signals_received'].append(number);raise KeyboardInterrupt('owned action interrupted')
    for number in (signal.SIGINT,signal.SIGTERM):signal.signal(number,interrupted)
    save(phase/'started.json',result)
    try:
        source_before=ledger(SOURCE/'inputs.sha256',source_sha);control_before=ledger(ROOT/'controls.sha256',controls_sha)
        need({str(p) for p in SOURCE.rglob('*') if p.is_file() or p.is_symlink()}==set(source_before),'source membership differs')
        for name,sha in FIXED.items():need(control_before.get(str(ROOT/name))==sha,'qualified helper identity differs')
        need(digest(review_path)==review_sha,'review changed')
        review=json.loads(review_path.read_text());need(review.get('source_sha256')==source_sha and review.get('controls_sha256')==controls_sha and review.get('approved_action')==mode,'review scope differs')
        host,supervisor,package=dependencies();host.admission(supervisor,phase)
        before=host.runtime_snapshot();save(phase/'runtime-before.json',before)
        save(phase/'source-before.json',source_before);save(phase/'controls-before.json',control_before)
        child={**ENV,'PYTHONNOUSERSITE':'1','PYTHONHASHSEED':'0','NUMEXPR_NUM_THREADS':'1','BLIS_NUM_THREADS':'1','GOTO_NUM_THREADS':'1','TMPDIR':str(phase/'tmp'),'PWD':str(ROOT)}
        command=['/usr/bin/bwrap','--die-with-parent','--unshare-net','--ro-bind','/','/','--tmpfs','/mnt','--dev','/dev','--tmpfs','/tmp',
                 '--bind',str(phase),str(phase),'--chdir',str(ROOT),'--',PYTHON,'-I','-S','-B',str(ROOT/'worker.py'),mode,source_sha,controls_sha,review_sha]
        receipt=supervisor.run_owned(command,python_executable='/usr/bin/python3',cwd=ROOT,env=child,log_path=phase/'worker.log',receipt_path=phase/'supervisor.json',
            timeout_seconds=300,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=32*1024**3,working_directory=ROOT)
        result['supervisor']=receipt;cleanup=receipt.get('cleanup',{})
        need(receipt['status']=='complete' and receipt['returncode']==0 and receipt['signals_received']==[] and cleanup.get('verified') is True
             and cleanup.get('empty_tree_certificate')=='kernel_ECHILD' and cleanup.get('remaining')==[] and cleanup.get('hard_kill') is False and cleanup.get('signals')==[],'worker failed or cleanup not clean')
        report=json.loads((phase/'worker-result.json').read_text());result['worker_result_sha256']=digest(phase/'worker-result.json')
        need(report['status']=='passed' and report['source_sha256']==source_sha and report['controls_sha256']==controls_sha and report['review_sha256']==review_sha
             and report['source_runtime_posthashed'] is True and report['process_policy_events']==[],'actual worker did not pass')
        if mode=='qualify':
            need(report['tests_run']==9 and report['test_ids']==(SOURCE/'expected-test-ids.txt').read_text().splitlines() and len(set(report['test_ids']))==9,'exact nine tests required')
            for key in ('failures','errors','skips','expected_failures','unexpected_successes'):need(report[key]==0,'actual test failure: '+key)
        else:
            actual=json.loads((phase/'result.json').read_text());need(actual['status']=='retained_system_checks_passed' and actual['all_31_inputs_unchanged_after'] is True,'actual retained check failed')
        result['status']='passed'
    except BaseException as error:result.update(status='failed',error=repr(error),traceback=traceback.format_exc())
    finally:
        try:
            need(host is not None and before is not None and source_before is not None and control_before is not None and package is not None,'baseline incomplete')
            source_after=ledger(SOURCE/'inputs.sha256',source_sha);controls_after=ledger(ROOT/'controls.sha256',controls_sha)
            need(source_after==source_before and controls_after==control_before and digest(review_path)==review_sha,'source/review changed')
            need({str(p) for p in SOURCE.rglob('*') if p.is_file() or p.is_symlink()}==set(source_before),'source membership changed')
            host.verify_known_runtime();package_inventory(package);after=host.runtime_snapshot();save(phase/'runtime-after.json',after)
            need(after==before,'controller runtime changed');result['source_runtime_posthashed']=True
        except BaseException as error:result.update(status='failed',source_runtime_posthashed=False,posthash_error=repr(error))
        save(phase/'controller-result.json',result)
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
