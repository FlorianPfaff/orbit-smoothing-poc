"""Composed namespace guards, independent of the unchanged numerical model."""
from pathlib import Path
import hashlib
import json
import shutil
from unittest.mock import patch
import unittest
import test_reference_objective_output as original
o = original.o


class ComposedPreparedParent(unittest.TestCase):
    def setUp(self):
        original.PrivateObjectiveOutput.setUp(self)
        self.source=self.output/'mirrors/data'
        (self.source/'2024-04-24').mkdir(parents=True)
        (self.source/'2024-04-24/observation').write_bytes(b'exact frozen measurement bytes')
        self.inventory=self.output/'mirrors/inventory.json'
        self.inventory.write_text(json.dumps({'root':str(self.source),'entries':o.tree(self.source)}))
        raw=self.inventory.read_bytes()
        self.plan['directory_overlays']=[{'target':str(self.target/'data'),'source':str(self.source),'inventory':{'path':str(self.inventory),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}}]
        self.real_identity=o.identity
        self.mirror_identity=o.identity(self.source)

    def tearDown(self):
        original.PrivateObjectiveOutput.tearDown(self)

    def verify(self):
        return original.PrivateObjectiveOutput.verify(self)

    def composed(self):
        (self.target/'data').rename(self.root/'original-data')
        shutil.copytree(self.source,self.target/'data')
        return patch.object(o,'identity',side_effect=lambda p:self.mirror_identity if Path(p)==self.target/'data' else self.real_identity(p))

    def objective(self):
        mounted=self.composed();mounted.start()
        (self.target/'output').mkdir()
        stage=o.STAGES[0]
        def identity(path):
            path=Path(path)
            if path==self.target:return self.mapping['view_identity']
            if path==self.target/'data':return self.mirror_identity
            if path==self.target/'output':return self.mapping['stage_outputs'][stage]['identity']
            return self.real_identity(path)
        mounted.stop()
        return patch.object(o,'identity',side_effect=identity),patch.dict('os.environ',{'TMPDIR':str(self.output/stage/'tmp')})

    def test_exact_nonobjective_composition(self):
        with self.composed():self.verify()

    def test_composed_nondata_change_rejected(self):
        with self.composed():
            (self.target/'estimate.xml').write_text('changed physical input')
            with self.assertRaisesRegex(ValueError,'outside the data overlay'):self.verify()

    def test_composed_extra_nondata_member_rejected(self):
        with self.composed():
            (self.target/'extra').write_text('extra')
            with self.assertRaisesRegex(ValueError,'outside the data overlay'):self.verify()

    def test_composed_missing_nondata_member_rejected(self):
        with self.composed():
            (self.target/'estimate.xml').unlink()
            with self.assertRaisesRegex(ValueError,'outside the data overlay'):self.verify()

    def test_composed_data_byte_change_rejected(self):
        with self.composed():
            (self.target/'data/2024-04-24/observation').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Visible data overlay differs'):self.verify()

    def test_composed_extra_data_member_rejected(self):
        with self.composed():
            (self.target/'data/extra').write_text('extra')
            with self.assertRaisesRegex(ValueError,'Visible data overlay differs'):self.verify()

    def test_composed_missing_data_member_rejected(self):
        with self.composed():
            (self.target/'data/2024-04-24/observation').unlink()
            with self.assertRaisesRegex(ValueError,'Visible data overlay differs'):self.verify()

    def test_changed_inventory_pin_rejected(self):
        with self.composed():
            self.inventory.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Frozen data inventory changed'):self.verify()

    def test_wrong_backing_identical_original_bytes_rejected(self):
        (self.target/'data').rename(self.root/'saved-data')
        shutil.copytree(self.root/'saved-data',self.target/'data')
        self.assertEqual(o.tree(self.target),self.mapping['original_tree'])
        with self.assertRaisesRegex(ValueError,'data backing identity differs'):self.verify()

    def test_wrong_backing_identical_overlay_bytes_rejected(self):
        with self.composed():pass
        self.assertEqual(o.tree(self.target/'data'),o.tree(self.source))
        with self.assertRaisesRegex(ValueError,'data backing identity differs'):self.verify()

    def test_objective_composition_allows_only_named_output_contents(self):
        identities,environment=self.objective()
        with identities,environment:
            (self.target/'output/allowed-export').write_bytes(b'new output')
            self.verify()

    def test_objective_composed_data_change_rejected(self):
        identities,environment=self.objective()
        with identities,environment:
            (self.target/'data/2024-04-24/observation').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Visible data overlay differs'):self.verify()

    def test_objective_wrong_output_backing_rejected(self):
        identities,environment=self.objective()
        with environment,patch.object(o,'identity',side_effect=lambda p:self.mapping['view_identity'] if Path(p)==self.target else self.real_identity(p)):
            with self.assertRaisesRegex(ValueError,'output backing differs'):self.verify()

    def test_objective_wrong_stage_rejected(self):
        identities,environment=self.objective()
        with identities,patch.dict('os.environ',{'TMPDIR':str(self.output/'prepared/tmp')}):
            with self.assertRaisesRegex(ValueError,'output backing differs'):self.verify()

    def checked_fixture(self):
        import contextlib
        from types import SimpleNamespace
        from test_reference_gates09 import g
        runtime_api=g.runtime_api()
        site=self.root/'site';site.mkdir()
        runtime_path=self.root/'runtime.json'
        g.save(runtime_path,{'schema':runtime_api.SCHEMA,'ld_library_path':g.base_env()['LD_LIBRARY_PATH'],
               'site_directory':str(site),'site_startup_members':[],'absent':[],
               'trees':[],'files':[runtime_api.entry(self.target/'estimate.xml')],'elf_dependencies':[]})
        storage={'output':str(self.output),'stages':{s:{} for s in sorted(('prepared',*g.STAGES))}}
        storage_path=self.root/'storage.json';g.save(storage_path,storage)
        overlay=self.plan['directory_overlays'][0]
        overlay['mount_identity']={'path':overlay['target'],'symlink_ancestors':[]}
        command=lambda stage,historical,runtime,directory:['tiny-fixture',stage,str(directory)]
        multiday=SimpleNamespace(native_data_inventory=lambda root:{'root':str(root),'entries':o.tree(root)})
        self.plan.update(schema='orbit-poc-v41-reference-gates-plan-v7-composition07',stages=list(g.STAGES),
          environment=g.base_env(),cpu=4,controller_limits={'readonly_inventory_preflight_seconds':1800},
          limits={'process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3},runner=g.pin(g.__file__),
          pins=[],storage_manifest=g.pin(storage_path),storage=storage,scratch_required_bytes=g.SCRATCH_REQUIRED_BYTES,
          python_runtime=g.pin(runtime_path),aliases=[],historical_inputs={'data_directories':[{'root':overlay['target']}]},runtime={})
        self.plan['jobs']=[{'stage':stage,'directory':str(self.output/stage),'timeout_seconds':7500 if stage.startswith('nuisance-replay') else 7200,
          'environment':g.planned_stage_env(self.output/stage),'argv':command(stage,None,None,self.output/stage)} for stage in g.STAGES]
        path=self.root/'plan.json';g.save(path,self.plan)
        stack=contextlib.ExitStack()
        stack.enter_context(patch.object(g,'api',return_value=(SimpleNamespace(command=command),multiday)))
        stack.enter_context(patch.object(g,'objective_output_api',return_value=o))
        stack.enter_context(patch.object(g,'overlay_mount_identity',side_effect=lambda path:{'path':path,'symlink_ancestors':[]}))
        return g,path,stack

    def test_checked_plan_host_wiring(self):
        g,path,stack=self.checked_fixture()
        with stack:self.assertEqual(g.checked_plan(path,g.sha(path))['objective_outputs'],self.mapping)

    def test_checked_plan_composed_wiring(self):
        g,path,stack=self.checked_fixture()
        with stack,self.composed():self.assertEqual(g.checked_plan(path,g.sha(path))['objective_outputs'],self.mapping)

    def test_checked_plan_wrong_backing_wiring(self):
        g,path,stack=self.checked_fixture()
        with self.composed():pass
        with stack,self.assertRaisesRegex(ValueError,'data backing identity differs'):
            g.checked_plan(path,g.sha(path))
