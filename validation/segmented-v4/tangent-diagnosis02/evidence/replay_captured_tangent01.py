#!/usr/bin/env python3
"""Compile and run one pinned diagnostic reader against a preserved capture."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess
INPUTS={'capture','capture_result','reader_source','reader_manifest','reader_tangent','reader_force','reader_quadrature','build_result'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(value):
 p=Path(value['path'])
 if set(value)!={'path','sha256'}or not p.is_absolute()or'..'in p.parts or sha(p)!=value['sha256']:raise ValueError('Changed standalone input')
 return p
def compile_command(built,source,binary):
 old=built['reader_compile_command'];old_source=Path(old[-3]);expected=[old[0],'-O3','-DNDEBUG','-std=gnu++17','-I'+str(old_source.parent/'include'),str(old_source),'-o',built['reader']['path']]
 if old!=expected or built['status']!='built_diagnostic_only':raise ValueError('Unexpected original reader compiler recipe')
 return [old[0],'-O3','-DNDEBUG','-std=gnu++17','-I'+str(source.parent/'include'),str(source),'-o',str(binary)]
def trace_records(path):
 rows=[json.loads(line)for line in path.read_text().splitlines()]
 if not rows or rows[0].get('kind')!='input'or rows[-1].get('kind')!='terminal':raise ValueError('Incomplete standalone trace')
 if {k:rows[0].get(k)for k in ('tolerance','maximum_iterations','restart')}!={'tolerance':2e-12,'maximum_iterations':120,'restart':20}:raise ValueError('Diagnostic numerical limits changed')
 return rows
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args();assert sha(a.plan)==a.sha256;p=json.loads(a.plan.read_text());assert set(p['inputs'])==INPUTS
 for value in p['inputs'].values():check(value)
 e=json.loads(check(p['execution']).read_text());paths={k:Path(v)for k,v in e['paths'].items()};out=Path(p['output']);assert not out.exists();out.mkdir();source=check(p['inputs']['reader_source']);binary=paths['binaries']/'tangent-reader';assert not binary.exists();built=json.loads(check(p['inputs']['build_result']).read_text());captured=json.loads(check(p['inputs']['capture_result']).read_text());capture=check(p['inputs']['capture'])
 assert captured['capture']==dict(p['inputs']['capture'],bytes=capture.stat().st_size) and captured['exact_failure_reproduced']is True and captured['native']==built['native']==p['native']
 manifest=json.loads(check(p['inputs']['reader_manifest']).read_text());assert set(manifest['files'])=={'sixStateTangent.h','syntheticForceDerivatives.h','eventQuadrature.h'}
 for name,value in manifest['files'].items():assert sha(source.parent/'include'/name)==value['telemetry_sha256']
 command=compile_command(built,source,binary);assert sha(Path(command[0]))==e['runtime_artifacts']['cxx_compiler']['sha256'];env=dict(os.environ,PATH=str(paths['prefix']/'bin')+':/usr/bin:/bin',LD_LIBRARY_PATH=str(paths['prefix']/'lib'))
 result={'schema':'orbit-poc-captured-tangent-experiment-v1','status':'running','plan_sha256':a.sha256,'inputs':p['inputs'],'compiler_command':command,'groops_propagations':0,'fit_attempts':0,'release_evidence':False}
 def save():(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 save()
 try:
  with(out/'compile.log').open('xb')as log:subprocess.run(command,cwd=paths['build'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
  result['reader']={'path':str(binary),'sha256':sha(binary)};result['compiler_version']=subprocess.check_output([command[0],'--version'],env=env,text=True);loader=subprocess.check_output(['/usr/bin/ldd',str(binary)],env=env,text=True);result['reader_loader_output']=loader;library_paths={word for line in loader.splitlines()for word in line.split()if word.startswith('/')and Path(word).is_file()};result['reader_libraries']=[{'path':x,'resolved':str(Path(x).resolve()),'sha256':sha(x)}for x in sorted(library_paths)];save()
  trace=out/'trace.jsonl';stderr=out/'stderr.log'
  with trace.open('xb')as stdout,stderr.open('xb')as err:run=subprocess.run([str(binary),str(capture)],cwd=paths['build'],env=env,stdout=stdout,stderr=err,check=False,timeout=600)
  rows=trace_records(trace);result.update(status='reader_passed'if run.returncode==0 else'reader_failed',returncode=run.returncode,trace={'path':str(trace),'sha256':sha(trace)},stderr={'path':str(stderr),'sha256':sha(stderr)},record_count=len(rows),input=rows[0],terminal=rows[-1]);save()
  for value in p['inputs'].values():check(value)
  return run.returncode
 except BaseException as error:result.update(status='control_failed',error=repr(error));save();raise
if __name__=='__main__':raise SystemExit(main())
