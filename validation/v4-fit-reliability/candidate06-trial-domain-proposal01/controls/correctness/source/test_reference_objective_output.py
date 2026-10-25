"""Pure namespace-control regressions; no native or remote execution."""
from pathlib import Path
import copy
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

P = Path(__file__).with_name('reference_objective_output.py')
spec = importlib.util.spec_from_file_location('reference_objective_output', P)
o = importlib.util.module_from_spec(spec)
exec(compile(P.read_bytes(), str(P), 'exec'), o.__dict__)


class PrivateObjectiveOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / 'original'
        self.target.mkdir()
        (self.target / 'data').mkdir()
        (self.target / 'data/input').write_bytes(b'unchanged science\x00\xff')
        (self.target / 'estimate.xml').write_text('exact original XML')
        self.output = self.root / 'new-attempt'
        (self.output / 'prepared').mkdir(parents=True)
        self.mount = {'path': str(self.target), 'symlink_ancestors': []}
        self.mapping = o.create(self.output, self.mount, target=self.target)
        self.plan = {'output': str(self.output), 'objective_outputs': self.mapping, 'directory_overlays':[{'target':str(self.target/'data')}]}
        self.patch = patch.object(o, 'TARGET', self.target)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def verify(self):
        return o.verify(self.plan, lambda x: self.mount)

    def test_copy_bytes_exact_original_untouched(self):
        self.verify()
        self.assertEqual(o.tree(self.target), self.mapping['original_tree'])
        self.assertFalse((self.target / 'output').exists())

    def test_isolated_stage_outputs(self):
        paths = [Path(x['path']) for x in self.mapping['stage_outputs'].values()]
        (paths[0] / 'new-result').write_text('stage one')
        self.assertFalse((paths[1] / 'new-result').exists())
        self.verify()

    def test_binding_only_objective_stages(self):
        for stage in ('prepared', 'flight-refinement', 'nuisance-replay'):
            self.assertEqual(o.binds(self.plan, self.output / stage, lambda x:self.mount), [])
        for stage in o.STAGES:
            args = o.binds(self.plan, self.output / stage, lambda x:self.mount)
            self.assertEqual(args[:3], ['--ro-bind', self.mapping['view'], str(self.target)])
            self.assertEqual(args[3:], ['--bind', str(self.output/stage/o.LEAF), str(self.target/'output')])

    def test_existing_output_is_preserved_and_rejected(self):
        (self.target / 'output').mkdir()
        (self.root/'different/prepared').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            o.create(self.root/'different', self.mount, target=self.target)

    def test_original_modification_rejected(self):
        (self.target / 'estimate.xml').write_text('different')
        with self.assertRaisesRegex(ValueError, 'Original prepared parent changed'):
            self.verify()

    def test_view_modification_rejected(self):
        (Path(self.mapping['view'])/'estimate.xml').write_text('different')
        with self.assertRaisesRegex(ValueError, 'view changed'):
            self.verify()

    def test_view_member_addition_rejected(self):
        (Path(self.mapping['view'])/'extra').write_text('different')
        with self.assertRaisesRegex(ValueError, 'view changed'):
            self.verify()

    def test_stage_backing_replacement_rejected(self):
        p=Path(self.mapping['stage_outputs'][o.STAGES[0]]['path'])
        p.rename(p.with_name('preserved'))
        p.mkdir()
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.verify()

    def test_stage_backing_escape_rejected(self):
        self.mapping['stage_outputs'][o.STAGES[0]]['path'] = str(self.target)
        with self.assertRaisesRegex(ValueError, 'backing'):
            self.verify()

    def test_resolution_change_rejected(self):
        with self.assertRaisesRegex(ValueError, 'resolution changed'):
            o.verify(self.plan, lambda x: {'path':'/other','symlink_ancestors':[]})

    def test_missing_stage_rejected(self):
        del self.mapping['stage_outputs'][o.STAGES[0]]
        with self.assertRaisesRegex(ValueError, 'mapping'):
            self.verify()

    def test_symlink_member_rejected(self):
        (self.target/'link').symlink_to(self.target/'estimate.xml')
        with self.assertRaisesRegex(ValueError, 'Linked or special'):
            o.tree(self.target)

    def test_extra_view_tree_entry_rejected(self):
        self.mapping['original_tree']=[]
        with self.assertRaisesRegex(ValueError, 'exact original'):
            self.verify()

    def test_unsupported_schema_rejected(self):
        self.mapping['schema']='other'
        with self.assertRaisesRegex(ValueError, 'mapping'):
            self.verify()

    def test_literal_data_link_preserved_without_following(self):
        (self.target/'data/link').symlink_to('/missing/historical/input')
        rows=o.tree(self.target)
        link=next(r for r in rows if r['relative']=='data/link')
        self.assertEqual(link, {'relative':'data/link','kind':'symlink','link_target':'/missing/historical/input'})

    def test_missing_frozen_data_overlay_rejected(self):
        self.plan['directory_overlays']=[]
        with self.assertRaisesRegex(ValueError,'exact frozen data overlay'):
            self.verify()

    def test_no_output_proof_for_other_stages(self):
        self.assertEqual(o.proof(self.plan,'flight-refinement',lambda x:None), {'active':False})

    def test_proof_requires_actual_private_parent(self):
        with self.assertRaisesRegex(ValueError, 'not the frozen copy'):
            o.proof(self.plan,o.STAGES[0],lambda x: {'options':['ro']})


if __name__=='__main__':
    unittest.main()
