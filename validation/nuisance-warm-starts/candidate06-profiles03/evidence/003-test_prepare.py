import argparse, ast, hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
SOURCE=Path('/home/emper/orbit-nuisance-warmstarts/control/make_profiles03_packet.py')
class PacketPreparer(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='fixtures-',dir=SOURCE.parent/'packet-preparer03-readiness01');self.addCleanup(self.temp.cleanup)
  self.B=Path(self.temp.name);spec=importlib.util.spec_from_file_location('packet_preparer_under_test',SOURCE);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
  self.m.B=self.B;self.m.C=self.B/'source-candidate06'
  for name in self.m.EVIDENCE:
   p=self.B/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
  def write(name,data):
   p=self.B/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data));return p
  self.report=write('source-candidate06/scripts/report_nuisance_warm_profiles.py',{'fixture':True})
  self.m.REPORT_SHA256=self.m.sha(self.report)
  self.m.READY_SHA256=self.m.sha(self.B/'control/candidate06-ready01/readiness.json')
  self.m.INVENTORY_SHA256=self.m.sha(self.B/'control/candidate06-ready01/source-inventory.json')
  self.freeze=write('profiles03/freeze.json',{'schema':'fixture','jobs':[]})
  write('profiles03/run-result.json',{'freeze':{'sha256':self.m.sha(self.freeze)},'outcomes':[{'status':'failed'}]})
  write('control/profiles03-check-execution-index.json',{'freeze_sha256':self.m.sha(self.freeze),'checks':[]})
  write('native-tests03/result.json',{'passed':False,'results':[]})
  self.audit=write('actual-audit.json',{'scientific_accepted':False,'release_authority':False})
  self.review=write('actual-review.json',{'status':'reviewed'})
  self.args=argparse.Namespace(output=self.B/'packet',audit=self.audit,review=[self.review])
 def test_failed_results_still_build_honest_report_command_without_execution(self):
  command,pins,log=self.m.prepare(self.args)
  self.assertEqual(command[:3],['/usr/bin/taskset','-c','4'])
  self.assertIn('--outcome-audit',command);self.assertIn(str(self.audit),pins)
  self.assertFalse(self.args.output.exists());self.assertFalse(log.exists())
 def test_existing_output_rejects(self):
  self.args.output.mkdir()
  with self.assertRaisesRegex(ValueError,'existing packet'):self.m.prepare(self.args)
 def test_protected_output_rejects(self):
  self.args.output=self.m.C/'report'
  with self.assertRaisesRegex(ValueError,'protected'):self.m.prepare(self.args)
 def test_reporter_change_rejects(self):
  self.report.write_text('changed')
  with self.assertRaisesRegex(ValueError,'reporter changed'):self.m.prepare(self.args)
 def test_readiness_change_rejects(self):
  (self.B/'control/candidate06-ready01/readiness.json').write_text('changed')
  with self.assertRaisesRegex(ValueError,'readiness/source'):self.m.prepare(self.args)
 def test_missing_terminal_run_rejects(self):
  (self.B/'profiles03/run-result.json').unlink()
  with self.assertRaisesRegex(ValueError,'Missing/nonregular'):self.m.prepare(self.args)
 def test_changed_freeze_rejects(self):
  self.freeze.write_text('{}')
  with self.assertRaisesRegex(ValueError,'freeze mismatch'):self.m.prepare(self.args)
 def test_missing_actual_audit_rejects(self):
  self.audit.unlink()
  with self.assertRaisesRegex(ValueError,'Missing/nonregular'):self.m.prepare(self.args)
 def test_explicit_actual_reviews_required(self):
  self.args.review=[]
  with self.assertRaisesRegex(ValueError,'actual candidate06'):self.m.prepare(self.args)
 def test_existing_execution_log_rejects(self):
  (self.B/'control/report-candidate06-profiles03.log').write_text('old')
  with self.assertRaisesRegex(ValueError,'execution log'):self.m.prepare(self.args)
 def test_symlink_evidence_rejects(self):
  p=self.B/self.m.EVIDENCE[0];p.unlink();p.symlink_to(self.audit)
  with self.assertRaisesRegex(ValueError,'symlink evidence'):self.m.prepare(self.args)
 def test_unexecuted_source_has_no_native_checker_or_git_call(self):
  tree=ast.parse(SOURCE.read_text())
  calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess']
  self.assertEqual(len(calls),1);self.assertEqual(calls[0].func.attr,'run')
  self.assertNotIn('run_owned',SOURCE.read_text())
if __name__=='__main__':unittest.main(verbosity=2)
