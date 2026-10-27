"""Pure tamper checks using temporary packet copies; no candidate/controller import."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('proposal_verifier',ROOT/'packet/verify_packet.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class VerifierTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='candidate06-proposal-checker-')
  self.root=Path(self.temp.name)/'packet';shutil.copytree(ROOT/'packet',self.root)
 def tearDown(self):self.temp.cleanup()
 def result(self):return module.Verification(self.root).run()
 def rehash(self,name):
  p=self.root/name;m=json.loads((self.root/'manifest.json').read_text())
  for r in m['files']:
   if r['path']==name:r['sha256']=module.Verification.sha(p);r['bytes']=p.stat().st_size
  (self.root/'manifest.json').write_text(json.dumps(m))
 def modify_json(self,name,fn):
  p=self.root/name;d=json.loads(p.read_text());fn(d);p.write_text(json.dumps(d));self.rehash(name)
 def test_portable_without_original_paths(self):self.assertTrue(self.result()['passed'])
 def test_changed_source_rejected(self):
  p=self.root/'candidate/source/src/orbit_poc/numerics/backend.py';p.write_text(p.read_text()+'\n# tampered\n')
  self.assertFalse(self.result()['passed'])
 def test_missing_failure_rejected(self):
  (self.root/'controls/sequence/tests01/result.json').unlink()
  with self.assertRaises(FileNotFoundError):self.result()
 def test_rehashed_false_failure_pass_rejected(self):
  self.modify_json('candidate/tests/unit01/result.json',lambda d:d.update(passed=True))
  self.assertFalse(self.result()['passed'])
 def test_rehashed_false_numerical_pass_rejected(self):
  self.modify_json('summary.json',lambda d:d.update(candidate06_native_correctness='passed'))
  self.assertFalse(self.result()['passed'])
 def test_rehashed_false_release_authority_rejected(self):
  self.modify_json('summary.json',lambda d:d.update(release_authority=True))
  self.assertFalse(self.result()['passed'])
 def test_rehashed_patch_tamper_rejected(self):
  p=self.root/'candidate/candidate06-python-domain.patch';p.write_text(p.read_text()+'\n');self.rehash(str(p.relative_to(self.root)))
  self.assertFalse(self.result()['passed'])
 def test_extra_uninventoried_file_rejected(self):
  (self.root/'unlisted.json').write_text('{}')
  self.assertFalse(self.result()['passed'])
if __name__=='__main__':unittest.main(verbosity=2)
