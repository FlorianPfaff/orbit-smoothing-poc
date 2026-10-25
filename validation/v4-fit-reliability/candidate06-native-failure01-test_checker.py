"""Pure archive-verifier tamper tests; no controller/native execution."""
import importlib.util,json,hashlib,shutil,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('archive_verifier',ROOT/'packet/verify_packet.py');MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)
def save(p,d):p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
def change_json(packet,rel,fn):
 p=packet/rel;d=json.loads(p.read_text());fn(d);save(p,d)
def refresh_manifest(packet):
 p=packet/'artifact-manifest.json';d=json.loads(p.read_text())
 for row in d['files']:
  f=packet/row['path']
  if f.exists():row['bytes']=f.stat().st_size;row['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()
 d['total_bytes']=sum(r['bytes'] for r in d['files']);save(p,d)
class CheckerTests(unittest.TestCase):
 def case(self,mutation=None,refresh=False):
  with tempfile.TemporaryDirectory(prefix='checker-',dir=ROOT) as name:
   packet=Path(name)/'packet';shutil.copytree(ROOT/'packet',packet)
   if mutation:mutation(packet)
   if refresh:refresh_manifest(packet)
   return MOD.verify(packet,False)
 def test_portable_valid(self):self.assertTrue(self.case()['passed'])
 def test_missing_failed_fixture(self):self.assertFalse(self.case(lambda p:(p/'evidence/current/fixtures/reject/search.json').unlink())['passed'])
 def test_modified_original_bytes(self):self.assertFalse(self.case(lambda p:(p/'evidence/current/stage.log').write_text('hidden'))['passed'])
 def test_reclassified_report_with_updated_manifest(self):
  self.assertFalse(self.case(lambda p:change_json(p,'report.json',lambda d:d.update(status='passed',failures=0,passed=106)),True)['passed'])
 def test_covariance_authority_with_updated_manifest(self):
  self.assertFalse(self.case(lambda p:change_json(p,'report.json',lambda d:d.update(covariance_authority=True)),True)['passed'])
 def test_cold_gate_claim_with_updated_manifest(self):
  self.assertFalse(self.case(lambda p:change_json(p,'report.json',lambda d:d.update(cold_fit_gate='open')),True)['passed'])
 def test_unknown_extra_file(self):self.assertFalse(self.case(lambda p:(p/'new-passing-result.json').write_text('{}'))['passed'])
 def test_broken_report_link_with_updated_manifest(self):
  self.assertFalse(self.case(lambda p:(p/'index.html').write_text((p/'index.html').read_text()+'<a href="missing-results.json">results</a>'),True)['passed'])
 def test_plan_change_with_updated_manifest(self):
  def mutate(p):
   change_json(p,'evidence/current/correctness-plan.json',lambda d:d['jobs'][0]['environment'].update(ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY='0'))
   # Even matching provenance cannot defeat the exact frozen-plan trust anchor.
   changed=p/'evidence/current/correctness-plan.json';pin={'bytes':changed.stat().st_size,'sha256':hashlib.sha256(changed.read_bytes()).hexdigest()}
   change_json(p,'provenance.json',lambda d:[r.update(pin) for r in d['files'] if r['path']=='evidence/current/correctness-plan.json'])
  self.assertFalse(self.case(mutate,True)['passed'])
 def test_fixture_rewrite_with_updated_manifest(self):
  def mutate(p):
   rel='evidence/current/fixtures/reject/search.json';change_json(p,rel,lambda d:d.update(trials=[{}]*17))
   changed=p/rel;pin={'bytes':changed.stat().st_size,'sha256':hashlib.sha256(changed.read_bytes()).hexdigest()}
   change_json(p,'provenance.json',lambda d:[r.update(pin) for r in d['files'] if r['path']==rel])
  self.assertFalse(self.case(mutate,True)['passed'])
 def test_missing_historical_auditor_failure(self):self.assertFalse(self.case(lambda p:(p/'evidence/history-audit/audit-attempt01.json').unlink())['passed'])
if __name__=='__main__':unittest.main(verbosity=2)
