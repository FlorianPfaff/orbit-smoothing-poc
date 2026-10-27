"""Behavioral eleven-stage handoff checks using only mocked receipt fixtures."""
import ast
from pathlib import Path
from test_sequence import Fixture,seq,write


class ElevenStageContract(Fixture):
 def test_supplement_is_second_with_exact_count(self):
  self.assertEqual(seq.STAGES[1],'native-fail-fast-tests');self.assertEqual(seq.TEST_COUNTS,{'native-tests':106,'native-fail-fast-tests':37,'correction-tests':51})
 def test_supplement_count_below_rejected(self):self.row_mutate('strict_result','evidence',{'tests':36},1);self.reject_audit()
 def test_supplement_count_above_rejected(self):self.row_mutate('strict_result','evidence',{'tests':38},1);self.reject_audit()
 def test_old_ten_flag_cannot_authorize_cold(self):
  self.r['all_ten_strict_passed']=self.r.pop('all_eleven_strict_passed');write(self.go/'result.json',self.r)
  code,g,c,r=self.run_case();self.assertEqual(code,1);c.execute.assert_not_called()
 def test_truthy_eleven_flag_rejected(self):
  self.r['all_eleven_strict_passed']='yes';write(self.go/'result.json',self.r);self.reject_audit()
 def test_integer_eleven_flag_rejected(self):
  self.r['all_eleven_strict_passed']=1;write(self.go/'result.json',self.r);self.reject_audit()
 def test_missing_supplement_cannot_authorize_cold(self):
  self.r['stages'].pop(1);write(self.go/'result.json',self.r)
  code,g,c,r=self.run_case();self.assertEqual(code,1);c.execute.assert_not_called()
 def test_failed_supplement_cannot_authorize_cold(self):
  self.row_mutate('row','status','failed',1);code,g,c,r=self.run_case();self.assertEqual(code,1);c.execute.assert_not_called()
 def test_native106_environment_one_rejected(self):
  self.jobs[0]['environment']['ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY']='1';self.update_plan();self.reject_audit()
 def test_supplement_environment_zero_rejected(self):
  self.jobs[1]['environment']['ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY']='0';self.update_plan();self.reject_audit()
 def test_each_production_stage_must_use_one(self):
  for job in self.jobs[1:]:
   with self.subTest(stage=job['stage']):
    job['environment']['ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY']='0';self.update_plan();self.reject_audit();job['environment']['ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY']='1'
 def test_missing_environment_rejected(self):
  del self.jobs[1]['environment'];self.update_plan();self.reject_audit()
 def test_old_gate_schema_rejected(self):
  p=seq.read(self.plan_path);p['schema']='orbit-poc-candidate06-correctness-plan-v1'
  with self.assertRaises(ValueError):seq.gate_plan_contract(p)
 def test_every_gate_required(self):
  p=seq.read(self.plan_path)
  for i in range(11):
   q={**p,'jobs':p['jobs'][:i]+p['jobs'][i+1:]}
   with self.subTest(stage=seq.STAGES[i]),self.assertRaises(ValueError):seq.gate_plan_contract(q)
 def test_old_sequence_schema_rejected(self):
  self.p['schema']='candidate06-correctness-cold-sequence-v1';write(self.path,self.p)
  with self.assertRaises(ValueError):seq.checked(self.path,seq.sha(self.path))
 def test_checked_rejects_correctly_rehashed_old_gate_schema(self):
  p=seq.read(self.plan_path);p['schema']='orbit-poc-candidate06-correctness-plan-v1';write(self.plan_path,p);write(self.freeze_path,{'plan':seq.pin(self.plan_path)});self.p['gate_freeze']=seq.pin(self.freeze_path);write(self.path,self.p)
  with self.assertRaises(ValueError):seq.checked(self.path,seq.sha(self.path))
 def test_lifecycle_and_execution_remain_original(self):
  funcs=lambda p:{n.name:n for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef)}
  old=funcs(Path(__file__).parent.parent/'density-trial-sequence01/sequence.py');new=funcs(Path(seq.__file__))
  dump=lambda node:ast.dump(node,include_attributes=False)
  before="require(all(x['status']=='passed' for x in result['stages']),'Cold aggregate disagrees with a failed stage')"
  after="require(result['status']!='passed' or all(x['status']=='passed' for x in result['stages']),'Cold aggregate claims passed despite a failed stage')"
  before_dump=dump(ast.parse(before).body[0]);after_dump=dump(ast.parse(after).body[0])
  self.assertEqual(sum(dump(n)==before_dump for n in ast.walk(old['run'])),1)
  self.assertEqual(sum(dump(n)==after_dump for n in ast.walk(new['run'])),1)
  class AuthorizedReportingChange(ast.NodeTransformer):
   def visit_Expr(self,node):
    return ast.parse(before).body[0] if dump(node)==after_dump else self.generic_visit(node)
  new['run']=AuthorizedReportingChange().visit(new['run'])
  for name in old:
   if name not in ('checked','gate_audit'):self.assertEqual(dump(old[name]),dump(new[name]),name)
