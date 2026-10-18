from pathlib import Path
import ast,importlib.util,json,re,tempfile,unittest
HERE=Path(__file__).parent;OLD=HERE.parent/'bwrap-cap-build-packet01/build_and_test.py'
spec=importlib.util.spec_from_file_location('v',HERE/'validate_existing.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
class Checks(unittest.TestCase):
 def fixture(self,change=None):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d);(b/'.deps').mkdir();(b/'config.h').write_text('config');objects=['bwrap-bubblewrap.o','bwrap-bind-mount.o','bwrap-network.o','bwrap-utils.o'];text='\n'.join('gcc -MT '+x+' -c source' for x in objects)
   for obj in objects:
    (b/obj).write_text('object');src=b/(obj[6:-2]+'.c');src.write_text('source');(b/'.deps'/(obj[:-2]+'.Po')).write_text(obj+': '+str(src)+' config.h\n')
   for name in ('utils.Po','test-utils.Po','try-syscall.Po'):(b/'.deps'/name).write_text('# dummy\n')
   if change:text=change(b,text)
   return v.dependency_inventory(b,text)
 def test_positive(self):self.assertEqual(len(self.fixture()['compiled_objects']),4)
 def test_missing_active(self):
  def edit(b,t):(b/'.deps/bwrap-utils.Po').unlink();return t
  with self.assertRaises(ValueError):self.fixture(edit)
 def test_active_dummy(self):
  def edit(b,t):(b/'.deps/bwrap-utils.Po').write_text('# dummy\n');return t
  with self.assertRaises(ValueError):self.fixture(edit)
 def test_unexpected_dependency(self):
  def edit(b,t):(b/'.deps/unexpected.Po').write_text('# dummy\n');return t
  with self.assertRaises(ValueError):self.fixture(edit)
 def test_non_dummy_unused(self):
  def edit(b,t):(b/'.deps/utils.Po').write_text('utils.o: unknown\n');return t
  with self.assertRaises(ValueError):self.fixture(edit)
 def test_missing_compile_command(self):
  with self.assertRaises(ValueError):self.fixture(lambda b,t:t.split('\n',1)[1])
 def test_missing_object(self):
  def edit(b,t):(b/'bwrap-utils.o').unlink();return t
  with self.assertRaises(ValueError):self.fixture(edit)
 def test_actual_make_targets(self):
  t=(HERE.parent/'bwrap-cap-build-terminal01/build/logs/make.stdout').read_text();self.assertEqual(set(re.findall(r'-MT (bwrap-[a-z-]+\.o)\b',t)),{'bwrap-bubblewrap.o','bwrap-bind-mount.o','bwrap-network.o','bwrap-utils.o'})
 def test_real_fixture_unchanged(self):
  trees=[ast.parse(p.read_text()) for p in (OLD,HERE/'validate_existing.py')]
  for name in ('payload','test'):
   f=[next(n for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name==name) for t in trees];self.assertEqual(ast.dump(f[0]),ast.dump(f[1]))
if __name__=='__main__':unittest.main()
