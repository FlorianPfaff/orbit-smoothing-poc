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
