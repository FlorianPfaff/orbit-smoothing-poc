"""One separately admitted, supervised run of 25 inert capture control tests."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import traceback

R=Path('/home/florianpfaff/codex-runs/orbit-fixed-capture-controls-20261026-01')
SOURCE=R/'capture-source'
BOOT='95156dd4-0d4c-499d-a214-8883a2d650fa'
ENV={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
     'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
PINS={
 'supervisor.py':'060bc208a5d36631689905563c9e969ae4615299e39e87637f71393b62eed267',
 'capture-source/source.sha256':'0324308fed6bdf34bbf6f54e3eeafb7039f6543b80bfc14009f4fc9d4aed526b',
 'tests/expected-test-ids.json':'f06934c2b671e68ab6c753158178fae73436086e9ae591985fc3cad499b3d73c',
 'tests/run_tests.py':'69fb36a2a0d8257e20f8cc3e41d2c4684841024e9316fd036921f9c53fcd386f',
 'provenance/capture-source-review.json':'f88c9e59b18944588e68ff19057a99827f79be43677194541480eb56b8e35846',
 'provenance/actual05-controller-runtime-before.json':'7078f7847e3c21c7bcca235ca57f6eace5d524e7e7f3aa4bd48d95a2b48c3f0b',
 'provenance/system-runtime-pins.json':'06f38245918e6ed6d31a626d1ca2affbe608ee01355b9ecb47db2653fb3136f7',
}
PYTHON_SHA='a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae'
TOOLS=('/usr/bin/python3','/usr/bin/bwrap','/usr/bin/findmnt','/usr/bin/taskset','/usr/bin/nice','/usr/bin/ldd')
RUNTIME_TREES=('/usr/lib/python3.10','/usr/lib/python3/dist-packages/psutil')


def need(ok,message):
 if not ok:raise ValueError(message)


def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()


def verify_sources(expected_sha):
 ledger=R/'inputs.sha256';need(digest(ledger)==expected_sha,'frozen input ledger changed')
 rows={}
 for line in ledger.read_text().splitlines():
  sha,name=line.split('  ',1);relative=Path(name)
  need(re.fullmatch('[0-9a-f]{64}',sha) is not None and name==relative.as_posix()
       and not relative.is_absolute() and '..' not in relative.parts and name not in rows,'unsafe/duplicate ledger member')
  path=R/relative
  need(path.is_file() and not path.is_symlink() and path.resolve(strict=True)==path,'missing/aliased source: '+name)
  need(digest(path)==sha,'uploaded source changed: '+name);rows[name]=sha
 for name,sha in PINS.items():need(rows.get(name)==sha,'required source identity differs: '+name)
 expected={'source.sha256'}
 for line in (SOURCE/'source.sha256').read_text().splitlines():
  sha,name=line.split('  ',1);relative=Path(name)
  need(not relative.is_absolute() and '..' not in relative.parts and relative.as_posix() not in expected,'unsafe/duplicate capture source member')
  expected.add(relative.as_posix());need(rows.get('capture-source/'+relative.as_posix())==sha,'capture03 source ledger differs')
 need(len(expected)==30 and {p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*') if p.is_file()}==expected,'capture03 file inventory differs')
 return rows


def runtime_snapshot():
 """Pin tree membership as well as bytes; include actual loaded native libraries."""
 files={};aliases={};tools={};dependencies={}
 def add(path):
  path=Path(path)
  if path.is_symlink():aliases[str(path)]=os.readlink(path)
  target=path.resolve(strict=True)
  if target.is_file():files[str(target)]=digest(target)
 for root in RUNTIME_TREES:
  tree=Path(root);need(tree.is_dir() and not tree.is_symlink(),'runtime tree missing/aliased: '+root)
  for path in sorted(tree.rglob('*')):
   if path.is_file() or path.is_symlink():add(path)
 for tool in TOOLS:
  add(tool);tools[tool]=str(Path(tool).resolve(strict=True))
  if tool!='/usr/bin/ldd':
   text=subprocess.check_output(['/usr/bin/ldd',tool],text=True,env=ENV,stderr=subprocess.STDOUT)
   need('not found' not in text,'runtime library missing: '+tool);dependencies[tool]=text
   for raw in re.findall(r'(/[A-Za-z0-9_./+:-]+)',text):add(raw)
 for module in list(sys.modules.values()):
  path=getattr(module,'__file__',None)
  if path and Path(path).is_file():add(path)
 for line in Path('/proc/self/maps').read_text().splitlines():
  fields=line.split(maxsplit=5)
  if len(fields)==6 and fields[5].startswith('/') and Path(fields[5]).is_file():add(fields[5])
 return {'files':files,'aliases':aliases,'tool_targets':tools,
         'dependency_paths':{tool:sorted(set(re.findall(r'(/[A-Za-z0-9_./+:-]+)',text))) for tool,text in dependencies.items()},
         'tree_roots':list(RUNTIME_TREES)}


def verify_known_runtime():
 need(Path('/usr/bin/python3').resolve(strict=True)==Path('/usr/bin/python3.10') and digest('/usr/bin/python3.10')==PYTHON_SHA,'qualified system Python identity differs')
 pins=json.loads((R/'provenance/system-runtime-pins.json').read_text())
 need(len(pins)==136 and all(path.startswith(('/usr/','/etc/')) for path in pins),'known runtime pin inventory differs')
 for path,sha in pins.items():need(digest(path)==sha,'previously qualified system runtime changed: '+path)


def admission(supervisor,folder):
 rows=[];blockers=[]
 for path in Path('/proc').glob('[0-9]*'):
  try:row=supervisor.process(int(path.name));row.update(name=(path/'comm').read_text().strip(),uid=path.stat().st_uid)
  except (FileNotFoundError,ProcessLookupError):continue
  rows.append(row)
  if row['pid']==os.getpid() or row['state']=='Z':continue
  if row['name'].startswith('groops') or (row['uid']==1002 and row['name'].startswith(('python','pytest','cc1','f951','cmake','ninja','make','g++','gcc','gfortran','source_record','native_','transaction_fai'))):blockers.append(row)
 storage=subprocess.check_output(['/usr/bin/findmnt','-n','-o','SOURCE,FSTYPE','--target',str(R)],text=True).split()
 receipt={'hostname':platform.node(),'uid':os.getuid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
          'self':supervisor.process(os.getpid()),'cpu':sorted(os.sched_getaffinity(0)),'nice':os.getpriority(os.PRIO_PROCESS,0),
          'storage':storage,'available_memory_bytes':supervisor.psutil.virtual_memory().available,
          'free_disk_bytes':supervisor.psutil.disk_usage(R).free,'blockers':blockers,'processes':rows,
          'timing_scope':'inert control qualification, not performance evidence'}
 supervisor.save(folder/'admission.json',receipt,new=True)
 need(receipt['hostname']=='workstation1' and receipt['uid']==1002 and receipt['boot_id']==BOOT,'current host identity differs')
 need(receipt['cpu']==[127] and receipt['nice']==19 and not blockers,'current-host admission failed')
 need(storage==['/dev/nvme0n1p2','ext4'] and receipt['available_memory_bytes']>=16*1024**3 and receipt['free_disk_bytes']>=32*1024**3,'storage/resource admission failed')


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--inputs-sha256',required=True)
 options=parser.parse_args();frozen_inputs_sha=options.inputs_sha256
 need(re.fullmatch('[0-9a-f]{64}',frozen_inputs_sha) is not None,'exact frozen ledger SHA required')
 need(R.resolve(strict=True)==R and not (R/'sequence01').exists() and not (R/'tests01').exists(),'fresh canonical remote root required')
 need(dict(os.environ)==ENV,'fixed clean one-thread environment required')
 source_before=verify_sources(frozen_inputs_sha);verify_known_runtime()
 spec=importlib.util.spec_from_file_location('capture_control_supervisor',R/'supervisor.py')
 supervisor=importlib.util.module_from_spec(spec);spec.loader.exec_module(supervisor)
 out=R/'sequence01';out.mkdir();phase=R/'tests01';phase.mkdir()
 result={'schema':'capture03-supervised-pure-control-qualification-v1','status':'running','inputs_sha256':frozen_inputs_sha,
         'planned_tests':25,'stage':{'status':'not_started'},'boot_id':BOOT,'supervisor_sha256':PINS['supervisor.py'],
         'capture_source_sha256':PINS['capture-source/source.sha256'],'runner_sha256':PINS['tests/run_tests.py'],
         'tests_source_review_sha256':PINS['provenance/capture-source-review.json'],'actual_posthash_verification_complete':False,
         'native_runs':0,'actual_namespace_verified':False,'capture_launch_authorized':False,
         'accepted_state_binding_issued':False,'scientific_backend_enabled':False,'score_authority':False,
         'covariance_authority':False,'release_authority':False}
 supervisor.save(out/'status.json',result,new=True);runtime_before=None
 try:
  review=json.loads((R/'provenance/capture-source-review.json').read_text())
  need(review['schema']=='new-fixed-physical-capture03-narrow-independent-source-review-v1'
       and review['approved_for_separately_admitted_control_test_qualification'] is True
       and review['source_manifest']['sha256']==PINS['capture-source/source.sha256']
       and review['test_source_review']['total_prepared_methods']==25
       and review['test_source_review']['tests_executed'] is False
       and review['approved_for_native_capture_launch'] is False,'source review scope differs')
  runtime_before=runtime_snapshot();supervisor.save(out/'runtime-before.json',runtime_before,new=True)
  supervisor.save(out/'sources-before.json',source_before,new=True)
  admission(supervisor,phase)
  command=['/usr/bin/bwrap','--die-with-parent','--unshare-net','--ro-bind','/','/',
           '--tmpfs','/mnt','--dev','/dev','--tmpfs','/tmp',
           '--bind',str(phase),str(phase),'--','/usr/bin/python3','-I','-S','-B',str(R/'tests/run_tests.py'),
           '--ids-sha256',PINS['tests/expected-test-ids.json'],'--output',str(phase/'results')]
  result['stage']={'status':'running','argv':command};supervisor.save(out/'status.json',result)
  receipt=supervisor.run_owned(command,python_executable='/usr/bin/python3',cwd=R,env=ENV,
    log_path=phase/'worker.log',receipt_path=phase/'supervisor.json',timeout_seconds=300,
    max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=32*1024**3,working_directory=R)
  result['stage']=receipt;supervisor.save(out/'status.json',result)
  cleanup=receipt.get('cleanup',{})
  need(cleanup.get('verified') is True and cleanup.get('empty_tree_certificate')=='kernel_ECHILD'
       and cleanup.get('remaining')==[] and cleanup.get('hard_kill') is False and cleanup.get('signals')==[]
       and receipt.get('signals_received')==[],'clean owned-process completion required')
  need(receipt['status']=='complete' and receipt['returncode']==0,'pure test worker did not complete successfully')
  path=phase/'results/result.json';need(path.is_file() and not path.is_symlink(),'actual test result missing')
  report=json.loads(path.read_text());result['actual_test_result_sha256']=digest(path)
  result['actual_tests']=report.get('actual_tests');result['test_passed']=report.get('passed')
  need(report['schema']=='capture03-inert-control-tests-v1' and report['passed'] is True
       and type(report['actual_tests']) is int and report['actual_tests']==25 and report['planned_tests']==25,'actual 25-test success required')
  for field in ('failures','errors','skipped','expected_failures','unexpected_successes'):need(report.get(field)==[],'test failures/skips retained: '+field)
  expected_child_sources={str(R/name):sha for name,sha in source_before.items() if name.startswith('capture-source/')}
  expected_child_sources.update({str(R/name):PINS[name] for name in ('tests/run_tests.py','tests/expected-test-ids.json')})
  need(report['sources_unchanged'] is True and report['source_before']==expected_child_sources
       and report['source_after']==expected_child_sources,'child source identity differs')
  ids=json.loads((R/'tests/expected-test-ids.json').read_text())
  need(len(report['actual_test_ids'])==25 and len(set(report['actual_test_ids']))==25
       and sorted(report['actual_test_ids'])==ids,'actual test identities differ')
  need(report['native_runs']==0 and report['forbidden_process_attempts']==[] and report['real_staging_executed'] is False
       and report['accepted_state_binding_issued'] is False
       and report['inert_fixture_success_is_not_capture_qualification'] is True,'inert test scope differs')
  result['status']='pure_control_tests_passed'
 except BaseException as error:
  result.update(status='failed',error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
 finally:
  try:
   source_after=verify_sources(frozen_inputs_sha);verify_known_runtime()
   supervisor.save(out/'sources-after.json',source_after,new=True)
   runtime_after=runtime_snapshot();supervisor.save(out/'runtime-after.json',runtime_after,new=True)
   need(source_after==source_before and runtime_before is not None and runtime_after==runtime_before,'source/runtime contents or membership changed')
   need(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BOOT,'boot changed')
   result['actual_posthash_verification_complete']=True
  except BaseException as error:result.update(status='failed',final_identity_error=repr(error),actual_posthash_verification_complete=False)
  supervisor.save(out/'status.json',result);supervisor.save(out/'result.json',result,new=True)
 return 0 if result['status']=='pure_control_tests_passed' else 1


if __name__=='__main__':sys.exit(main())
