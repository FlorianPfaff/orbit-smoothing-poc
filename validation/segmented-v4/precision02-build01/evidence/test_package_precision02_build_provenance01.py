import copy,importlib.util,json,unittest
from pathlib import Path
C=Path('/mnt/d/orbit-segmented-v4/control')
s=importlib.util.spec_from_file_location('subject',C/'package_precision02_build_provenance01.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class BuildPublicationGuards(unittest.TestCase):
 def setUp(self):
  self.key='misc/orbitPoc/sixStateTangent.h';self.target='CMakeFiles/groopscore.dir/programs/preprocessing/preprocessingVariationalEquation.cpp.o'
  before={self.key:'0'*64,**{f'f{i}':'1'*64 for i in range(1130)}};after=dict(before);after[self.key]=m.HEADER
  objects={self.target:'2'*64,**{f'o{i}':'3'*64 for i in range(610)}};rebuilt=list(objects)[:27]
  native={'path':'/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/tangent-precision-02/binaries/test-fixture','sha256':'4'*64}
  self.r={'schema':'orbit-poc-tangent-precision-candidate-build-v1','status':'built_precision_candidate','native':native,'fit_attempts':0,'release_evidence':False,'baseline_relinked_sha256':m.BASELINE,'original_native':{'sha256':m.BASELINE},'source_before':before,'source_after':after,'compile_commands':{k:['fixture']for k in rebuilt},'rebuilt_objects':rebuilt,'original_object_sha256':objects,'changed_objects':[self.target],'reused_object_count':584,'all_original_link_inputs':{f'input{i}':'5'*64 for i in range(637)}}
  self.p={'path':'/fixture/result.json','sha256':'6'*64,'bytes':12}
  self.a={'passed':True,'plan':{'sha256':m.PLAN},'execution':{'sha256':m.EXECUTION},'result':{'path':'/fixture/tangent-precision-02/run/result.json','sha256':'6'*64,'bytes':12},'native':copy.deepcopy(native)}
  self.source=json.loads((C/'precision02-source-identity01.json').read_text())
 def valid(self):return m.validate_documents(self.r,self.a,self.source,self.p)
 def test_exact_complete_fixture(self):self.assertEqual(self.valid()['recompiled_translation_units'],27)
 def test_running_is_not_complete(self):
  self.r['status']='building'
  with self.assertRaises(ValueError):self.valid()
 def test_audit_is_required(self):
  self.a['passed']=False
  with self.assertRaises(ValueError):self.valid()
 def test_audit_result_bytes_exact(self):
  self.a['result']['bytes']=13
  with self.assertRaises(ValueError):self.valid()
 def test_old_plan_rejected(self):
  self.a['plan']['sha256']='0'*64
  with self.assertRaises(ValueError):self.valid()
 def test_native_mismatch_rejected(self):
  self.a['native']['sha256']='0'*64
  with self.assertRaises(ValueError):self.valid()
 def test_incomplete_dependency_rebuild_rejected(self):
  self.r['rebuilt_objects'].pop()
  with self.assertRaises(ValueError):self.valid()
 def test_second_source_change_rejected(self):
  self.r['source_after']['f1']='7'*64
  with self.assertRaises(ValueError):self.valid()
 def test_original_baseline_exact(self):
  self.r['baseline_relinked_sha256']='0'*64
  with self.assertRaises(ValueError):self.valid()
 def test_missing_link_input_rejected(self):
  self.r['all_original_link_inputs'].pop('input1')
  with self.assertRaises(ValueError):self.valid()
 def test_supplemental_identity_not_implicit(self):
  self.source['files'][1]['committed_sha256']='0'*64
  with self.assertRaises(ValueError):self.valid()
 def test_no_scope_expansion(self):
  self.r['fit_attempts']=1
  with self.assertRaises(ValueError):self.valid()
if __name__=='__main__':unittest.main(verbosity=2)
