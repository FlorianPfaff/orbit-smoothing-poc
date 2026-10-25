"""Pure control tests. They never launch native, compiler or SSH processes."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('reference_gates09.py')
spec = importlib.util.spec_from_file_location('reference_gates02', SCRIPT)
g = importlib.util.module_from_spec(spec)
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), 'exec'), g.__dict__)


class ReferenceControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input = self.root / 'scientific-input'
        self.input.write_bytes(b'exact-original-input\x00\xff')
        self.digest = g.sha(self.input)
        self.target = str(g.PREFIXES[1] / 'unit-test-profile/input.dat')
        self.inventory = {'dependencies': [{'expected_sha256': self.digest,
            'local_content': {'available': True, 'sha256': self.digest, 'path': str(self.input)}}]}
        self.historical = {'dependencies': [{'path': self.target, 'sha256': self.digest}], 'data_directories': []}
        self.capture = {'files': []}

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_mapping(self):
        rows, dirs = g.aliases(self.inventory, self.historical, self.capture)
        self.assertEqual(rows, [{'target': self.target, 'source': g.pin(self.input)}])
        self.assertEqual(dirs, [str(Path(self.target).parent)])

    def test_captured_mapping(self):
        rows, _ = g.aliases({'dependencies': []}, self.historical, {'files': [
            {'sha256': self.digest, 'local_path': str(self.input)}]})
        self.assertEqual(rows[0]['source']['sha256'], self.digest)

    def test_null_local_content_uses_exact_capture(self):
        rows, _ = g.aliases({'dependencies': [{'expected_sha256': self.digest, 'local_content': None}]},
            self.historical, {'files': [{'sha256': self.digest, 'local_path': str(self.input)}]})
        self.assertEqual(rows[0]['source']['sha256'], self.digest)

    def test_wrong_captured_bytes_rejected(self):
        self.input.write_text('substitution')
        with self.assertRaisesRegex(ValueError, 'changed'):
            g.aliases(self.inventory, self.historical, self.capture)

    def test_unknown_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No exact'):
            g.aliases({'dependencies': []}, self.historical, self.capture)

    def test_duplicate_dependency_rejected(self):
        self.historical['dependencies'] *= 2
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            g.aliases(self.inventory, self.historical, self.capture)

    def test_file_data_membership_added(self):
        data = g.PREFIXES[1] / 'unit-test-profile/data'
        self.historical['data_directories'] = [{'root': str(data), 'entries': [
            {'relative': '2024-05-10', 'kind': 'directory'},
            {'relative': '2024-05-10/gnss.dat', 'kind': 'file', 'sha256': self.digest}]}]
        rows, dirs = g.aliases(self.inventory, self.historical, self.capture)
        self.assertEqual(len(rows), 2)
        self.assertIn(str(data / '2024-05-10'), dirs)

    def test_conflicting_data_hash_rejected(self):
        data = Path(self.target).parent
        self.historical['data_directories'] = [{'root': str(data), 'entries': [
            {'relative': 'input.dat', 'kind': 'file', 'sha256': '0'*64}]}]
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            g.aliases(self.inventory, self.historical, self.capture)

    def test_symlink_historical_data_rejected(self):
        self.historical['data_directories'] = [{'root': str(Path(self.target).parent), 'entries': [
            {'relative': 'input.dat', 'kind': 'symlink'}]}]
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            g.aliases(self.inventory, self.historical, self.capture)

    def test_current_canonical_substitution_rejected(self):
        self.historical['dependencies'] = [{'path': str(self.input), 'sha256': '0'*64}]
        with self.assertRaisesRegex(ValueError, 'canonical input differs'):
            g.aliases(self.inventory, self.historical, self.capture)

    def test_existing_canonical_not_shadowed(self):
        self.historical['dependencies'] = [{'path': str(self.input), 'sha256': self.digest}]
        self.assertEqual(g.aliases(self.inventory, self.historical, self.capture), ([], []))

    def test_parent_traversal_rejected(self):
        for value in (str(g.PREFIXES[0])+'/../steal', '/etc/passwd', '/home/emper/new', 'relative', str(g.PREFIXES[0])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                g.target_path(value)

    def namespace_fixture(self):
        out = self.root / 'new-output'
        (out / 'stage/tmp').mkdir(parents=True)
        rows, dirs = g.aliases(self.inventory, self.historical, self.capture)
        storage = g.storage_api().create(out, ('stage',))
        self.addCleanup(__import__('shutil').rmtree, storage['root']['path'])
        return {'output': str(out), 'aliases': rows, 'alias_directories': dirs, 'storage': storage}, out / 'stage'

    def test_namespace_input_mounts_readonly_and_parents_sealed(self):
        plan, directory = self.namespace_fixture()
        cmd = g.namespace(plan, directory, ['/bin/true'])
        index = cmd.index(self.target)
        self.assertEqual(cmd[index-2], '--ro-bind')
        self.assertEqual(cmd[-8:-4], ['--remount-ro', '/mnt', '--remount-ro', '/home'])
        self.assertEqual(cmd[-1], '/bin/true')
        self.assertEqual(cmd[cmd.index('--bind')+1:cmd.index('--bind')+3], [str(directory)]*2)

    def test_namespace_output_escape_rejected(self):
        plan, _ = self.namespace_fixture()
        with self.assertRaisesRegex(ValueError, 'escapes'):
            g.namespace(plan, self.root, ['/bin/true'])

    def test_namespace_output_symlink_rejected(self):
        plan, directory = self.namespace_fixture()
        alias = directory.parent / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            g.namespace(plan, alias, ['/bin/true'])

    def test_namespace_duplicate_alias_rejected(self):
        plan, directory = self.namespace_fixture()
        plan['aliases'] *= 2
        with self.assertRaisesRegex(ValueError, 'Duplicate namespace'):
            g.namespace(plan, directory, ['/bin/true'])

    def test_environment_exact_flags_and_single_threads(self):
        env = g.planned_stage_env('/isolated/stage')
        self.assertTrue(all(env[k] == '1' for k in g.THREADS))
        self.assertEqual(env['ORBIT_POC_GNSS_DESIGN_STORAGE'], 'disk')
        self.assertEqual(env['ORBIT_POC_GNSS_DESIGN_SCRATCH'], '/isolated/stage/scratch')
        self.assertEqual(env['ORBIT_POC_NUMERICS_SPOOL_DIRECTORY'], '/isolated/stage/row-spool')
        self.assertNotIn('ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS', env)

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for content in ('{"a":1,"a":2}', '{"a":NaN}'):
            self.input.write_text(content)
            with self.assertRaises(ValueError):
                g.read(self.input)

    def test_evidence_never_overwritten(self):
        g.save(self.root / 'evidence.json', {'failed': True})
        with self.assertRaises(FileExistsError):
            g.save(self.root / 'evidence.json', {'passed': True})
        self.assertEqual(g.read(self.root / 'evidence.json'), {'failed': True})

    def test_extra_data_at_correct_role_is_allowed(self):
        historical = {'dependencies': [{'path': '/cache/data/day/orbit/exact.dat', 'sha256': self.digest}],
                      'data_directories': [{'root': '/original/data', 'entries': []}]}
        actual = [{'root': '/original/data', 'entries': [{'relative': 'day/orbit/exact.dat', 'sha256': self.digest}]}]
        g.validate_data_membership(actual, historical)

    def test_extra_data_wrong_role_with_correct_bytes_rejected(self):
        historical = {'dependencies': [{'path': '/cache/data/day/orbit/exact.dat', 'sha256': self.digest}],
                      'data_directories': [{'root': '/original/data', 'entries': []}]}
        actual = [{'root': '/original/data', 'entries': [{'relative': 'day/orbit/duplicate.dat', 'sha256': self.digest}]}]
        with self.assertRaisesRegex(ValueError, 'role or bytes'):
            g.validate_data_membership(actual, historical)

    def test_original_data_missing_rejected(self):
        historical = {'dependencies': [], 'data_directories': [{'root': '/original/data', 'entries': [
            {'relative': 'exact.dat', 'sha256': self.digest}]}]}
        with self.assertRaisesRegex(ValueError, 'missing'):
            g.validate_data_membership([{'root': '/original/data', 'entries': []}], historical)

    def test_readonly_mount_covered_by_writable_mount(self):
        mounts = [{'id': 1, 'parent': 0, 'path': '/', 'options': ['ro']},
                  {'id': 2, 'parent': 1, 'path': '/tmp', 'options': ['ro']},
                  {'id': 3, 'parent': 2, 'path': '/tmp', 'options': ['rw']}]
        self.assertEqual(g.containing_mount(mounts, '/tmp/cache')['id'], 3)
        self.assertEqual(g.containing_mount(list(reversed(mounts)), '/tmp/cache')['id'], 3)
        self.assertEqual(g.containing_mount(mounts, '/original')['id'], 1)

    def test_readonly_specific_mount_retained(self):
        mounts = [{'id': 1, 'parent': 0, 'path': '/', 'options': ['ro']},
                  {'id': 2, 'parent': 1, 'path': '/home', 'options': ['rw']},
                  {'id': 3, 'parent': 2, 'path': '/home/input', 'options': ['ro']}]
        self.assertEqual(g.containing_mount(mounts, '/home/input/file')['options'], ['ro'])

    def test_cyclic_mount_ancestry_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            g.containing_mount([{'id': 1, 'parent': 1, 'path': '/', 'options': ['ro']}], '/input')

    def test_overlay_only_exact_historical_root(self):
        plan, directory = self.namespace_fixture()
        plan['historical_inputs'] = {'data_directories': [{'root': '/historical/data'}]}
        plan['directory_overlays'] = [{'target': '/different/data', 'source': '/private/data'}]
        with self.assertRaisesRegex(ValueError, 'exact historical'):
            g.namespace(plan, directory, ['/bin/true'])

    def test_historical_symlink_never_silently_converted(self):
        self.historical['data_directories'] = [{'root': '/historical/data', 'entries': [
            {'relative': 'input.dat', 'kind': 'file', 'link_target': '/canonical/data', 'sha256': self.digest}]}]
        with self.assertRaisesRegex(ValueError, 'linked data semantics'):
            g.reconstruct_data(self.root / 'output', self.historical, self.inventory, self.capture)

    def test_reconstruction_exact_membership_and_bytes(self):
        self.historical['data_directories'] = [{'root': '/historical/data', 'entries': [
            {'relative': 'day', 'kind': 'directory', 'link_target': None},
            {'relative': 'day/input.dat', 'kind': 'file', 'link_target': None,
             'bytes': self.input.stat().st_size, 'sha256': self.digest}]}]
        overlays = g.reconstruct_data(self.root / 'output', self.historical, self.inventory, self.capture)
        self.assertEqual(overlays[0]['target'], '/historical/data')
        self.assertEqual(g.sha(Path(overlays[0]['source']) / 'day/input.dat'), self.digest)
        self.assertFalse((Path(overlays[0]['source']) / 'day/input.dat').is_symlink())

    def test_overlay_mount_resolves_ancestor_and_preserves_historical_name(self):
        real = self.root / 'real'
        (real / 'data').mkdir(parents=True)
        alias = self.root / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        target = str(alias / 'data')
        identity = g.overlay_mount_identity(target)
        self.assertEqual(identity['path'], str(real / 'data'))
        self.assertEqual(identity['symlink_ancestors'], [{'path': str(alias), 'target': str(real)}])
        row = {'target': target, 'mount_identity': identity}
        self.assertEqual(g.verified_overlay_mount(row), str(real / 'data'))
        self.assertEqual(row['target'], target)

    def test_overlay_mount_retargeted_symlink_rejected(self):
        a, b, alias = self.root / 'a', self.root / 'b', self.root / 'alias'
        a.mkdir(); b.mkdir(); alias.symlink_to(a, target_is_directory=True)
        row = {'target': str(alias), 'mount_identity': g.overlay_mount_identity(str(alias))}
        alias.unlink(); alias.symlink_to(b, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'resolution changed'):
            g.verified_overlay_mount(row)

    def test_overlay_mount_broken_symlink_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root / 'absent', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            g.overlay_mount_identity(str(alias / 'data'))

    def test_overlay_mount_missing_private_dir_stable_after_creation(self):
        path = self.root / 'absent' / 'private'
        identity = g.overlay_mount_identity(str(path))
        path.mkdir(parents=True)
        self.assertEqual(g.verified_overlay_mount({'target': str(path), 'mount_identity': identity}), str(path))

    def test_overlay_mount_regular_file_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not a directory'):
            g.overlay_mount_identity(str(self.input))

    def test_overlay_mount_unsafe_path_rejected(self):
        for target in ('relative', '/x/../data', '/x//data'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'Unsafe'):
                g.overlay_mount_identity(target)

    def test_overlay_mount_unpinned_mapping_rejected(self):
        with self.assertRaisesRegex(ValueError, 'resolution changed'):
            g.verified_overlay_mount({'target': str(self.root)})

    def test_namespace_mount_uses_frozen_destination_not_historical_spelling(self):
        plan, directory = self.namespace_fixture()
        real, alias = self.root / 'real', self.root / 'alias'
        real.mkdir(); alias.symlink_to(real, target_is_directory=True)
        row = {'target': str(alias), 'source': str(real), 'mount_identity': g.overlay_mount_identity(str(alias))}
        plan['historical_inputs'] = {'data_directories': [{'root': str(alias)}]}
        plan['directory_overlays'] = [row]
        cmd = g.namespace(plan, directory, ['/bin/true'])
        self.assertIn(['--ro-bind', str(real), str(real)], [cmd[i:i+3] for i in range(len(cmd)-2)])
        self.assertNotIn(str(alias), cmd)



# These classes are discovered with unittest discovery; no native process runs.
from unittest import mock
import sys
from types import SimpleNamespace

class RunBoundaryControls(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.root=Path(self.temporary.name)
        self.original=(self.root/'plan.json'); self.original.write_text('{"version":"original"}')
        artifact=self.root/'preflight.json'; artifact.write_text('{}')
        self.jobs=[]
        for name in g.STAGES:
            root=self.root/name
            for leaf in (('tmp','scratch','row-spool','legacy-output') if name in ('objective-log_drag_ou','objective-pulses') else ('tmp','scratch','row-spool')): (root/leaf).mkdir(parents=True)
            self.jobs.append({'stage':name,'directory':str(root),'argv':['unchanged',name],'environment':{},'timeout_seconds':7200})
        self.plan={'output':str(self.root),'runtime':{'python':g.pin(sys.executable)},'jobs':self.jobs,
                   'limits':{'process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3}}
        self.plan['storage']=g.storage_api().create(self.root,g.STAGES)
        self.plan['scratch_required_bytes']=g.SCRATCH_REQUIRED_BYTES
        self.addCleanup(__import__('shutil').rmtree,self.plan['storage']['root']['path'])
        self.freeze=self.root/'freeze.json'
        g.save(self.freeze,{'plan':g.pin(self.original),'validation_inputs':g.pin(artifact),'preflight':g.pin(artifact)})
        self.expected=g.sha(self.freeze);self.original_plan=g.pin(self.original);self.calls=[]
        self.cleanup_mode=None;self.change=None
        import orbit_poc.segmented.supervisor as supervisor
        self.supervisor=supervisor

    def tearDown(self): self.temporary.cleanup()

    def checked_plan(self,path,expected):
        if g.sha(path)!=expected: raise ValueError('Plan hash differs')
        return self.plan

    def owned(self,argv,**kwargs):
        stage=self.jobs[len(self.calls)]['stage'];self.calls.append(argv)
        cleanup={'verified':True,'empty_tree_certificate':'kernel_ECHILD','remaining':[]}
        row={'status':'complete','returncode':0,'owned_process_group_cleaned':True,'cleanup':cleanup}
        if self.cleanup_mode and self.cleanup_mode[0]==len(self.calls):
            if self.cleanup_mode[1]=='false': cleanup['verified']=False
            elif self.cleanup_mode[1]=='missing': cleanup.pop('empty_tree_certificate')
            elif self.cleanup_mode[1]=='group': row['owned_process_group_cleaned']=False
            elif self.cleanup_mode[1]=='remaining': cleanup['remaining']=[{'pid':123}]
            elif self.cleanup_mode[1]=='missing_remaining': cleanup.pop('remaining')
        g.save(kwargs['receipt_path'],row)
        job=self.jobs[len(self.calls)-1]
        g.save(Path(job['directory'])/'strict-result.json',{'stage':stage,'argv':job['argv'],'returncode':0,'status':'passed'})
        if self.change=='plan': self.original.write_text('{"version":"changed"}')
        if self.change=='freeze': self.freeze.write_text('{"version":"changed"}')
        return row

    def execute(self):
        with mock.patch.object(g,'checked_plan',side_effect=self.checked_plan),mock.patch.object(g,'admission',return_value={}),\
             mock.patch.object(g,'namespace',side_effect=lambda plan,root,argv:argv),\
             mock.patch.object(self.supervisor,'run_owned',side_effect=self.owned):
            status=g.run(self.freeze,self.expected)
        return status,g.read(self.root/'result.json')

    def test_all_exact_cleanup_and_strict_results_pass(self):
        status,result=self.execute();self.assertEqual(status,0);self.assertTrue(result['all_ten_strict_passed'])
        self.assertEqual(len(self.calls),len(g.STAGES))
        for argv in self.calls: self.assertEqual(argv[argv.index('--sha256')+1],self.original_plan['sha256'])

    def test_existing_strict_receipt_blocks_any_launch(self):
        protected=Path(self.jobs[0]['directory'])/'strict-result.json'
        protected.write_text('{"status":"passed","stage":"old-attempt"}')
        with self.assertRaisesRegex(ValueError,'Preserve prior stage evidence'):
            self.execute()
        self.assertEqual(self.calls,[])
        self.assertIn('old-attempt',protected.read_text())

    def test_wrong_stage_strict_receipt_cannot_authorize_ten_gate_success(self):
        original=self.owned
        def wrong_stage(*args,**kwargs):
            value=original(*args,**kwargs)
            if len(self.calls)==1:
                path=Path(self.jobs[0]['directory'])/'strict-result.json'
                receipt=g.read(path);receipt['stage']='stale-other-stage'
                path.write_text(json.dumps(receipt))
            return value
        self.owned=wrong_stage
        status,result=self.execute()
        self.assertEqual(status,1)
        self.assertFalse(result['all_ten_strict_passed'])
        self.assertEqual(result['stages'][0]['status'],'failed')

    def test_last_cleanup_failure_cannot_pass(self):
        self.cleanup_mode=(len(g.STAGES),'false');status,result=self.execute()
        self.assertEqual(status,1);self.assertFalse(result['all_ten_strict_passed']);self.assertEqual(result['stages'][-1]['status'],'failed')

    def test_missing_ECHILD_stops_queue(self):
        self.cleanup_mode=(1,'missing');status,result=self.execute()
        self.assertEqual(status,1);self.assertEqual(len(self.calls),1);self.assertFalse(result['all_ten_strict_passed'])

    def test_nonempty_remaining_stops_queue(self):
        self.cleanup_mode=(1,'remaining');status,result=self.execute()
        self.assertEqual(status,1);self.assertEqual(len(self.calls),1)

    def test_missing_remaining_stops_queue(self):
        self.cleanup_mode=(1,'missing_remaining');status,result=self.execute()
        self.assertEqual(status,1);self.assertEqual(len(self.calls),1)

    def test_unclean_group_stops_queue(self):
        self.cleanup_mode=(1,'group');status,result=self.execute()
        self.assertEqual(status,1);self.assertEqual(len(self.calls),1)

    def test_plan_mutation_after_stage_rejected_and_original_attribution(self):
        self.change='plan';status,result=self.execute()
        self.assertEqual(status,1);self.assertEqual(len(self.calls),1)
        self.assertEqual(result['plan'],self.original_plan)
        self.assertEqual(result['stages'][0]['input_identity_after'],'changed')

    def test_freeze_mutation_after_stage_rejected(self):
        self.change='freeze';status,result=self.execute()
        self.assertEqual(status,1);self.assertEqual(len(self.calls),1)
        self.assertEqual(result['freeze']['sha256'],self.expected)

    def test_post_stage_runtime_change_rejected(self):
        original=self.checked_plan
        def check(path,expected):
            if self.calls: raise ValueError('Python runtime changed')
            return original(path,expected)
        self.checked_plan=check
        status,result=self.execute();self.assertEqual(status,1);self.assertEqual(len(self.calls),1)
        self.assertEqual(result['stages'][0]['input_identity_after'],'changed')

    def test_final_validation_error_blocks_aggregate_success(self):
        original=self.checked_plan;count=[0]
        def check(path,expected):
            count[0]+=1
            if count[0]==2*len(g.STAGES)+2: raise ValueError('Final runtime change')
            return original(path,expected)
        self.checked_plan=check
        status,result=self.execute();self.assertEqual(len(self.calls),len(g.STAGES));self.assertEqual(status,1)
        self.assertFalse(result['all_ten_strict_passed']);self.assertIn('Final runtime',result['error'])

class RuntimeClosureControls(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.r=g.runtime_api()
        (self.root/'pkg').mkdir();(self.root/'pkg/value.py').write_text('original')
    def tearDown(self):self.temporary.cleanup()
    def test_tree_membership_includes_added_file(self):
        before=self.r.tree(self.root);(self.root/'pkg/extra.py').write_text('extra')
        self.assertNotEqual(before,self.r.tree(self.root))
    def test_tree_content_change_detected(self):
        before=self.r.tree(self.root);(self.root/'pkg/value.py').write_text('changed')
        self.assertNotEqual(before,self.r.tree(self.root))
    def test_tree_directory_symlink_rejected(self):
        (self.root/'alias').symlink_to(self.root/'pkg',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'directory symlink'):self.r.tree(self.root)
    def test_tree_file_symlink_target_is_pinned(self):
        (self.root/'alias.py').symlink_to(self.root/'pkg/value.py')
        row=self.r.entry(self.root/'alias.py');self.assertIn('link_target',row);self.assertEqual(row['resolved'],str(self.root/'pkg/value.py'))
    def test_tree_exclusion_does_not_swallow_other_directories(self):
        value=self.r.tree(self.root,('site-packages',));self.assertEqual(len(value['entries']),2)
    def test_ldd_resolution_parser(self):
        self.assertEqual(self.r.dependency_paths('linux-vdso.so.1 (0x0)\nlibc.so.6 => /lib/libc.so.6 (0x1)\n /lib/ld.so (0x2)'),['/lib/ld.so','/lib/libc.so.6'])
    def test_ldd_parent_paths_normalized_without_changing_leaf_alias(self):
        self.assertEqual(self.r.dependency_paths('libx.so => /pkg/core/../../bundle/libx.so (0x1)'),['/bundle/libx.so'])

    def test_ldd_missing_library_rejected(self):
        with self.assertRaisesRegex(ValueError,'unresolved'):self.r.dependency_paths('libmissing.so => not found')
    def test_ldd_unknown_output_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unrecognized'):self.r.dependency_paths('unexpected output')

class NestedIdentityControls(unittest.TestCase):
    def test_plan_changed_during_nested_verification_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plan=root/'plan.json';plan.write_text('original')
            data=root/'data.json';data.write_text('{}');freeze=root/'freeze.json'
            g.save(freeze,{'plan':g.pin(plan),'validation_inputs':g.pin(data),'preflight':g.pin(data)})
            expected=g.sha(freeze)
            def mutate(*args):plan.write_text('changed');return {}
            with mock.patch.object(g,'checked_plan',side_effect=mutate),self.assertRaisesRegex(ValueError,'Frozen bytes'):
                g.checked_freeze(freeze,expected)

    def test_validation_inputs_changed_during_nested_verification_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plan=root/'plan.json';plan.write_text('original')
            data=root/'data.json';data.write_text('{}');freeze=root/'freeze.json'
            g.save(freeze,{'plan':g.pin(plan),'validation_inputs':g.pin(data),'preflight':g.pin(data)})
            expected=g.sha(freeze)
            def mutate(*args):data.write_text('changed');return {}
            with mock.patch.object(g,'checked_plan',side_effect=mutate),self.assertRaisesRegex(ValueError,'Frozen bytes'):
                g.checked_freeze(freeze,expected)

class RuntimeVerificationControls(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.r=g.runtime_api()
        self.site=self.root/'site';self.site.mkdir();self.file=self.root/'runtime';self.file.write_text('original')
        self.value={'schema':self.r.SCHEMA,'ld_library_path':'','site_directory':str(self.site),'site_startup_members':[],
                    'absent':[str(self.site/'sitecustomize.py')],'trees':[],'files':[self.r.entry(self.file)],'elf_dependencies':[]}
    def tearDown(self):self.temporary.cleanup()
    def test_new_pth_rejected(self):
        (self.site/'new.pth').write_text('import something')
        with self.assertRaisesRegex(ValueError,'startup membership'):self.r.verify(self.value,{})
    def test_absent_startup_path_appearing_rejected(self):
        (self.site/'sitecustomize.py').write_text('pass')
        with self.assertRaisesRegex(ValueError,'startup path appeared'):self.r.verify(self.value,{})
    def test_runtime_library_changed_rejected(self):
        self.file.write_text('changed')
        with self.assertRaisesRegex(ValueError,'file changed'):self.r.verify(self.value,{})
    def test_changed_elf_resolution_rejected(self):
        self.value['elf_dependencies']=[{'path':str(self.file),'dependencies':['/original/lib.so']}]
        with mock.patch.object(self.r,'linked',return_value=['/substituted/lib.so']),self.assertRaisesRegex(ValueError,'ELF resolution'):
            self.r.verify(self.value,{})
    def test_complete_fixture_verifies(self):
        self.assertTrue(self.r.verify(self.value,{})['hashes_and_membership_verified'])

class AdmissionControls(unittest.TestCase):
    def test_truncated_segmented_solver_and_known_native_names_reject(self):
        for name in ('segmented-qr-2c','segmented_qr','groops-v41-abcd','cc1plus','g++'):
            with tempfile.TemporaryDirectory() as directory:
                row=Path(directory)/'123';row.mkdir();(row/'comm').write_text(name+'\n')
                with mock.patch.object(g.Path,'glob',return_value=[row]),self.assertRaisesRegex(RuntimeError,'Competing native'):
                    g.admission()

    def test_bundled_elf_classifier_leaves_extensions_as_roots(self):
        r=g.runtime_api()
        self.assertTrue(r.is_dependency_only_elf('/python/site-packages/numpy.libs/libgfortran.so'))
        self.assertFalse(r.is_dependency_only_elf('/python/site-packages/numpy/linalg/_umath.so'))

if __name__ == '__main__':
    unittest.main(verbosity=2)
