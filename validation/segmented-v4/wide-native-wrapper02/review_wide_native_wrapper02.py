from pathlib import Path
import ast,subprocess,time,json,tempfile,hashlib,datetime
from unittest.mock import patch
C=Path('/mnt/d/orbit-segmented-v4/control')
source=Path('/mnt/d/orbit-segmented-v4/source/tests/test_wide_tangent_native.py')
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
tree=ast.parse(source.read_text());func=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='run_logged')
ns={'subprocess':subprocess,'time':time,'json':json}
exec(compile(ast.Module(body=[func],type_ignores=[]),str(source),'exec'),ns)
checks=[]
for kind in ('TimeoutExpired','FileNotFoundError','nonzero_return'):
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);rawout=b'partial stdout\r\n';rawerr=b'partial stderr\r\n'
  def fake(argv,**kwargs):
   assert argv==['never-executed-fixture'];assert kwargs['timeout']==3
   if kind!='FileNotFoundError':
    kwargs['stdout'].write(rawout);kwargs['stderr'].write(rawerr)
   if kind=='TimeoutExpired':raise subprocess.TimeoutExpired(argv,3)
   if kind=='FileNotFoundError':raise FileNotFoundError('mocked missing executable')
   return subprocess.CompletedProcess(argv,9)
  expected={'TimeoutExpired':subprocess.TimeoutExpired,'FileNotFoundError':FileNotFoundError,'nonzero_return':AssertionError}[kind]
  with patch.object(subprocess,'run',side_effect=fake) as mocked:
   try:ns['run_logged'](['never-executed-fixture'],root,'attempt',3)
   except expected:pass
   else:raise AssertionError('Expected failure not propagated')
   assert mocked.call_count==1
  status=json.loads((root/'attempt.json').read_text())
  assert status['argv']==['never-executed-fixture'] and status['timeout_seconds']==3 and status['elapsed_seconds']>=0
  if kind=='nonzero_return':assert status['status']=='completed' and status['returncode']==9
  else:assert status['status']=='failed' and status['error_type']==kind
  assert (root/'attempt.stdout').read_bytes()==(b'' if kind=='FileNotFoundError' else rawout)
  assert (root/'attempt.stderr').read_bytes()==(b'' if kind=='FileNotFoundError' else rawerr)
  checks.append({'case':kind,'passed':True,'status':status,'raw_output_preserved':True})
receipt={'schema':'orbit-poc-independent-source-review-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'passed','passed':True,'scope':'Source review and exactly three pure mocked subprocess failure tests; no compiler/native execution.','source':pin(source),'review_helper':pin(Path(__file__)),'previous_finding':pin(C/'wide-native-wrapper-source-independent-review01.json'),'checks':checks,'resolved_finding':'stdout/stderr are streamed as bytes to files and terminal attempt JSON is written in finally on timeout/startup errors; normal nonzero exit retains output and returncode before assertion.','unchanged_scoped_checks':['C++ fixture require checks survive -DNDEBUG.','Exact-node and actual anchored high/low Fraction decoder expectations remain correct.','CXX is one executable path/name selected by shutil.which; no shell expansion.','Log artifacts remain under pytest tmp_path and need retention by the surrounding test runner.'],'execution':{'mock_cases':3,'compiler_invocations':0,'native_invocations':0,'remote_launches':0}}
out=C/'wide-native-wrapper-source-independent-review02.json'
with out.open('x') as f:json.dump(receipt,f,indent=2);f.write('\n')
print(json.dumps(pin(out)))
