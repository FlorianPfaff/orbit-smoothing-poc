"""Pure generator regression tests; no captured solve is run here."""
import array, hashlib, importlib.util, json, math, pathlib, struct, tempfile, unittest
spec=importlib.util.spec_from_file_location('family',pathlib.Path(__file__).with_name('generate_family.py'));f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
def fixture():
 b=b'OPCTANGENT001\n\0\0'+struct.pack('<5Q2d',1,2,1,0,12,1.,1.)+bytes(72*8)+struct.pack('<Q',0)
 return b+struct.pack('<12d',*([1.,-2.,3.,4.,-5.,6.]+[.001,-.002,.003,.004,-.005,.006]))
class FamilyTests(unittest.TestCase):
 def test_round_trip(self):
  b=fixture();offset,rhs,*_=f.decode(b);self.assertEqual(b[:offset]+f.encode(rhs),b)
 def test_perturbations(self):
  _,rhs,*_=f.decode(fixture())
  for d in ['smooth','alternating']:
   for scale in [1e-12,1e-9]:
    for sign in [-1,1]:
     out,stats=f.perturb(rhs,scale,d,sign);self.assertGreater(stats['changed_entries'],0);self.assertAlmostEqual(stats['actual_relative_balanced_norm']/scale,1.,places=4)
     self.assertEqual(out,f.perturb(rhs,scale,d,sign)[0])
 def test_reject_malformed(self):
  for raw in [b'',fixture()[:-1],fixture()+b'x']:
   with self.assertRaises(ValueError):f.decode(raw)
 def test_freeze_order_identity_and_no_overwrite(self):
  original=f.ANCHORS
  try:
   with tempfile.TemporaryDirectory() as t:
    root=pathlib.Path(t);raw=fixture();(root/'a.bin').write_bytes(raw)
    f.ANCHORS=tuple((name,'a.bin',f.sha(raw)) for name in ('historical_large','current_small','current_large'))
    result=f.generate(root,root/'frozen');m=json.loads((root/'frozen/manifest.json').read_text())
    self.assertEqual((result['cases'],result['attempts']),(27,54));self.assertEqual(len({c['id'] for c in m['cases']}),27)
    for c in m['cases']:
     payload=pathlib.Path(c['path']).read_bytes();self.assertEqual(f.sha(payload),c['sha256']);self.assertEqual(payload[:656],raw[:656])
    for i,c in enumerate(m['cases']):self.assertEqual([j['profile'] for j in m['execution_order'][2*i:2*i+2]],['baseline','wide'] if i%2==0 else ['wide','baseline'])
    with self.assertRaises(FileExistsError):f.generate(root,root/'frozen')
    f.ANCHORS=(('wrong','a.bin','0'*64),)
    with self.assertRaises(ValueError):f.generate(root,root/'wrong')
    self.assertFalse((root/'wrong').exists())
  finally:f.ANCHORS=original
if __name__=='__main__':unittest.main()
