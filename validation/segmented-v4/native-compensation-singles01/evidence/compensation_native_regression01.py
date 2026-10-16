"""Run the supplemental analytical fixture against the actual candidate header."""
from pathlib import Path
import hashlib,json,subprocess

EXPECTED_HEADER='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def recipe(built,fixture,output):
 root=Path(built['native']['path']).parent.parent
 include=root/'native_source/source/misc/orbitPoc'
 header=include/'sixStateTangent.h'
 if sha(header)!=EXPECTED_HEADER or built['source_after']['misc/orbitPoc/sixStateTangent.h']!=EXPECTED_HEADER:raise ValueError('Candidate header differs')
 commands=list(built['compile_commands'].values())
 if len(commands)!=27 or len({x[0]for x in commands})!=1 or any(not all(flag in x for flag in ('-O3','-DNDEBUG','-std=gnu++17'))for x in commands):raise ValueError('Native compiler recipe differs')
 return [commands[0][0],'-O3','-DNDEBUG','-std=gnu++17','-I',str(include),str(fixture),'-o',str(output)],header
def run(folder,built,fixture):
 folder.mkdir();binary=folder/'compensated-quadrature';argv,header=recipe(built,fixture,binary)
 record={'schema':'orbit-poc-compensation-supplemental-native-regression-v1','status':'running','argv':argv,'compiler_sha256':sha(argv[0]),'header':{'path':str(header),'sha256':sha(header)},'fixture':{'path':str(fixture),'sha256':sha(fixture)},'native':built['native'],'frozen_suite_counts_changed':False,'fit_attempts':0}
 def save():(folder/'result.json').write_text(json.dumps(record,indent=2)+'\n')
 save()
 try:
  with(folder/'compile.log').open('xb')as f:subprocess.run(argv,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=90)
  with(folder/'run.log').open('xb')as f:subprocess.run([str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=30)
  if(folder/'run.log').read_bytes()!=b'compensated quadrature regression passed\n':raise ValueError('Unexpected supplemental fixture output')
  record.update(status='passed',binary={'path':str(binary),'sha256':sha(binary)})
 except BaseException as error:record.update(status='failed',error=repr(error));raise
 finally:save()
 return record
