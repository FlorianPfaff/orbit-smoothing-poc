"""Campaign freeze, input-integrity and resource tests; no numerical jobs launched."""
import importlib.util,json,tempfile,unittest
from threading import Barrier, Lock
from pathlib import Path
from unittest.mock import patch
from orbit_poc.comparison import protocol as p
from orbit_poc.comparison.config import load_config
PROJECT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('campaign_driver',PROJECT/'scripts/run_comparison_campaign.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
CONFIG=load_config(PROJECT/'configs/comparison-v3.json')

class Checks(unittest.TestCase):
 def test_parallel_preparation_primes_dates_and_preserves_case_order(self):
  cases=[{'date':date,'seed':seed} for date,seeds in [('2024-04-23',range(3)),('2024-04-24',range(3,6))] for seed in seeds]
  first={case['date']:case['seed'] for case in reversed(cases)}
  primed=set();active=0;peak=0;lock=Lock();barrier=Barrier(4,timeout=10)
  def prepare(runner,frozen,stage,split,case,allowed):
   nonlocal active,peak
   self.assertEqual(split,'evaluation');self.assertTrue(allowed)
   if case['seed']==first[case['date']]:
    with lock:
     self.assertEqual(active,0);primed.add(case['date'])
   else:
    with lock:
     self.assertEqual(primed,set(first));active+=1;peak=max(peak,active)
    barrier.wait()
    with lock:active-=1
   return {'status':'prepared','seed':case['seed']}
  with tempfile.TemporaryDirectory() as folder,patch.object(p,'_prepared',side_effect=prepare):
   rows=list(d.prepared_cases(p.Runner(folder,workers=4),{},'flight','evaluation',[('primary',case) for case in cases]))
  self.assertEqual([row[1] for row in rows],cases)
  self.assertEqual([row[2]['seed'] for row in rows],list(range(6)))
  self.assertEqual(peak,4)
 def test_memory_cap_uses_available_not_installed(self):
  with tempfile.TemporaryDirectory(prefix='driver-memory-test-') as folder:
   path=Path(folder)/'meminfo'
   path.write_text('MemTotal: 131072000 kB\nMemAvailable: 52428800 kB\n')
   result=d.launch_resources(24,path)
   self.assertEqual(result['chosen_workers'],12)
   self.assertGreaterEqual(result['available_after_estimated_worker_budget_bytes'],result['reserve_bytes'])
   self.assertEqual(d.launch_resources(4,path)['chosen_workers'],4)
   path.write_text('MemTotal: 131072000 kB\nMemAvailable: 1000000 kB\n')
   with self.assertRaisesRegex(RuntimeError,'Insufficient available memory'):d.launch_resources(24,path)
 def test_case_counts_and_secondary_seeds(self):
  syn=d.evaluation_cases(CONFIG,'synthetic');flight=d.evaluation_cases(CONFIG,'flight')
  self.assertEqual({k:len(v) for k,v in syn.items()},{'primary':800,'stress':10})
  self.assertEqual({k:len(v) for k,v in flight.items()},{'primary':12,'flight_ar_reference':6})
  self.assertEqual({x['seed'] for x in syn['stress']},set(range(500000,500005)))
  self.assertTrue(all(x['ambiguity_policy']=='integer' for x in flight['flight_ar_reference']))
 def exercise_freeze(self):
  temp=tempfile.TemporaryDirectory(prefix='driver-freeze-test-');self.addCleanup(temp.cleanup);root=Path(temp.name)
  frozen={'protocol_hash':'p','source':{'sha256':'s'},'native_binary':{'path':'native','sha256':'n'}}
  selection={'selection_hash':'selection'};cases={'primary':[{'seed':1}],'stress':[{'seed':2}]}
  calls=[]
  def prepared(runner,actual_frozen,stage,split,case,allowed):
   self.assertEqual(split,'evaluation');self.assertTrue(allowed);calls.append(case)
   sub=root/str(case['seed']);sub.mkdir();raw=sub/'raw';raw.write_text('observations')
   native=sub/'receiver';native.write_text('converted observations')
   nf=sub/'native.json';p.write_json(nf,{'native_artifacts':[p.artifact_record('converted_estimation_input',native)]})
   result={'status':'prepared','request_hash':str(case['seed']),'record_path':str(sub/'result.json'),
    'estimation_inputs':[p.artifact_record('gnss_observations',raw),p.artifact_record('force_auxiliary',nf,metadata={'kind':'native_preparation'})]}
   p.write_json(sub/'result.json',result)
   index={'status':'prepared','request_hash':result['request_hash'],'result_path':result['record_path'],'result_sha256':p.file_hash(sub/'result.json')}
   p.write_json(sub/'result-record.json',index);return result
  with patch.object(p,'_selection',return_value=selection),patch.object(p,'_prepared',side_effect=prepared),patch.object(d,'evaluation_cases',return_value=cases):
   record=d.freeze_evaluation_inputs(CONFIG,root,frozen,'synthetic')
   self.assertEqual(len(calls),2);self.assertEqual(len(record['inputs']),6)
   self.assertEqual(d.freeze_evaluation_inputs(CONFIG,root,frozen,'synthetic'),record)
   self.assertEqual(len(calls),2)
   return root,frozen,selection,cases,record
 def test_resume_and_transitive_mutation(self):
  root,frozen,selection,cases,record=self.exercise_freeze()
  (root/'1/receiver').write_text('mutated converted observations')
  with patch.object(d,'evaluation_cases',return_value=cases),self.assertRaisesRegex(ValueError,'Converted input changed'):
   d.verify_input_freeze(record,CONFIG,frozen,selection,'synthetic')
 def test_selection_identity_cannot_change(self):
  root,frozen,selection,cases,record=self.exercise_freeze()
  with patch.object(d,'evaluation_cases',return_value=cases),self.assertRaisesRegex(ValueError,'selection_hash'):
   d.verify_input_freeze(record,CONFIG,frozen,{'selection_hash':'changed'},'synthetic')
 def test_missing_planned_case_blocks(self):
  root,frozen,selection,cases,record=self.exercise_freeze()
  expanded={**cases,'extra':[{'seed':3}]}
  with patch.object(d,'evaluation_cases',return_value=expanded),self.assertRaisesRegex(ValueError,'every planned case'):
   d.verify_input_freeze(record,CONFIG,frozen,selection,'synthetic')

if __name__=='__main__':unittest.main()


def test_flight_freeze_pins_corrections_once_per_date_and_rejects_mutation(tmp_path,monkeypatch):
 from dataclasses import replace
 from orbit_poc.comparison import slr
 import pytest
 config=replace(CONFIG,backend=replace(CONFIG.backend,auxiliary_dir=str(tmp_path/'aux')))
 frozen={'protocol_hash':'p','source':{'sha256':'s'},'native_binary':{'path':'native','sha256':'n'}}
 selection={'selection_hash':'selection'}
 cases={'primary':[{'date':'2024-05-11','coverage':coverage} for coverage in ('normal','blackout')],
        'flight_ar_reference':[{'date':'2024-05-11','coverage':'normal','ambiguity_policy':'integer'}]}
 calls=[]
 def fetch(url,path,**kwargs):
  path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text('auxiliary fixture')
  item={'url':url,'path':str(path),'sha256':p.file_hash(path),'bytes':path.stat().st_size}
  p.write_json(str(path)+'.source.json',item);calls.append(url);return item
 def prepared(runner,actual_frozen,stage,split,case,allowed):
  sub=tmp_path/(case['coverage']+case.get('ambiguity_policy',''));sub.mkdir()
  raw=sub/'raw';raw.write_text('GNSS observations')
  crd=sub/'withheld.crd';crd.write_text('h2 station 7105 0 0 0\n11 invalid numerical content\n')
  gnv=sub/'GNV1B';gnv.write_text('reference bytes that must never be parsed prefit')
  result={'status':'prepared','request_hash':sub.name,'record_path':str(sub/'result.json'),
   'estimation_inputs':[p.artifact_record('gnss_observations',raw)],
   'evaluation_inputs':[p.artifact_record('slr_validation',crd),p.artifact_record('comparison_orbit',gnv)]}
  p.write_json(sub/'result.json',result)
  index={'status':'prepared','request_hash':result['request_hash'],'result_path':result['record_path'],'result_sha256':p.file_hash(sub/'result.json')}
  p.write_json(sub/'result-record.json',index);return result
 monkeypatch.setattr(p,'_selection',lambda *a:selection)
 monkeypatch.setattr(p,'_prepared',prepared)
 monkeypatch.setattr(d,'evaluation_cases',lambda *a:cases)
 monkeypatch.setattr(slr,'fetch_url',fetch)
 monkeypatch.setattr(slr,'inspect_crd',lambda *a,**k:pytest.fail('normal points parsed before evaluation'))
 record=d.freeze_evaluation_inputs(config,tmp_path,frozen,'flight')
 assert len(record['slr_auxiliary'])==1
 assert len(calls)==14
 assert len([item for item in record['inputs'] if item['usage']=='slr_evaluation_corrections'])==29
 monkeypatch.setattr(slr,'fetch_url',lambda *a,**k:pytest.fail('frozen resume downloaded'))
 assert d.freeze_evaluation_inputs(config,tmp_path,frozen,'flight')==record
 changed=next(item for item in record['inputs'] if item['role']=='slr_auxiliary_source')
 Path(changed['path']).write_text('changed correction')
 with pytest.raises(ValueError,match='Frozen SLR correction changed'):
  d.verify_input_freeze(record,config,frozen,selection,'flight')
