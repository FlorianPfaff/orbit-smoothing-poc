#!/usr/bin/env python3
"""Fabricated recovery controls; never build GROOPS, signal old jobs, or alter prior artifacts."""
import ast
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).parent

def module(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

v=module('validate_candidate_09');w=module('with_correctness_namespace_09')


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='candidate09-mock-',dir=HERE);self.root=Path(self.tmp.name)
        self.stack=ExitStack();self.source=self.root/'source';self.source.mkdir()
        for i in range(8):(self.source/f'file-{i}').write_text(str(i))
        original_receipt=v.source_receipt
        virtual={f'preserved-{i}':'a'*64 for i in range(750)}
        def receipt(path):
            value=original_receipt(path);value['files'].update(virtual)
            value['sha256']=v.digest(value['files']);return value
        self.stack.enter_context(mock.patch.object(v,'source_receipt',receipt))
        self.original=v.source_receipt(self.source)
        (self.source/'file-0').write_text('corrected')
        regressions=['tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py']
        (self.source/'tests').mkdir()
        for name in regressions:(self.source/name).write_text('# fabricated regression')
        for i in range(4):(self.source/('extra-previous-'+str(i))).write_text('# previous')
        self.historical_source=v.source_receipt(self.source)
        historical_regression={'files':list(regressions),'expected_count':18}
        (self.source/'file-0').write_text('corrected again')
        regressions.extend(['tests/test_numerics_precise_residual.py','tests/test_numerics_precise_objective.py'])
        for name in regressions[2:]:(self.source/name).write_text('# previous07 regression')
        for i in range(5):(self.source/('extra-previous07-'+str(i))).write_text('# previous07')
        self.previous_source=v.source_receipt(self.source)
        previous_regression={'files':list(regressions),'expected_count':40}
        (self.source/'file-0').write_text('corrected light time')
        regressions.append('tests/test_numerics_new_precision.py');(self.source/regressions[-1]).write_text('# new')
        regression={'files':regressions,'expected_count':41}
        self.frozen=v.source_receipt(self.source)
        self.control=self.root/'control';self.control.mkdir();self.data=self.root/'data';self.data.mkdir()
        self.paths={key:str(self.root/key) for key in v.PATH_KEYS}
        self.paths.update(root=str(self.root),source=str(self.source),control=str(self.control),wrapper=str(self.control/'with_correctness_namespace_09.py'))
        Path(self.paths['wrapper']).write_text((HERE/'with_correctness_namespace_09.py').read_text())
        runtime={}
        for name in ('python','cmake','bubblewrap','taskset'):
            file=self.root/(name+'-tool');file.write_text(name);runtime[name]={'path':str(file),'sha256':v.sha(file)}
        self.paths.update(python=runtime['python']['path'],cmake=runtime['cmake']['path'])
        # Keep required names canonical; aliases pin the fabricated bytes.
        runtime['bubblewrap']['path']='/usr/bin/bwrap';runtime['taskset']['path']='/usr/bin/taskset'
        runtime['control_python']={'path':str(Path(v.sys.executable).resolve()),'sha256':v.sha(Path(v.sys.executable).resolve())}
        bindings=[{'source':str(self.data),'target':'/canonical/input'},
                  {'source':str(self.root/'bubblewrap-tool'),'target':'/usr/bin/bwrap'},
                  {'source':str(self.root/'taskset-tool'),'target':'/usr/bin/taskset'}]
        self.execution={'schema':'orbit-poc-correctness-execution-v1','host':{'hostname':'fixture','boot_id':'new-boot'},
            'paths':self.paths,'build_cpus':[0,1,2,3],'fit_cpu':4,'read_only_bindings':bindings,
            'runtime_artifacts':runtime,'reserved_cpu_note':'Fabricated CPUs for control testing only.'}
        self.execution_path=self.control/'execution.json';self.execution_path.write_text(json.dumps(self.execution))
        self.inputs={role:Path('/canonical/input')/(role+'.json') for role in v.PINNED_INPUTS}
        for role,path in self.inputs.items():(self.data/path.name).write_text(json.dumps({'role':role}))
        (self.data/'prior_validation.json').write_text(json.dumps({'status':'failed','final_cleanup':{'verified':True},'resume':{'status':'resumed'}}))
        for role,fields in v.REPLAY_DEPENDENCIES.items():
            (self.data/self.inputs[role].name).write_text('<config>'+''.join('<'+tag+'>'+str(self.inputs[dep])+'</'+tag+'>' for tag,dep in fields.items())+'</config>')
        self.source_freeze=self.control/'source-freeze.json';self.source_freeze.write_text(json.dumps({'source':self.original}))
        self.interrupted=self.control/'old-pipeline.json';self.interrupted.write_text(json.dumps({'status':'running','steps':[{'name':'build'}]}))
        self.restart=self.control/'restart.json';self.restart.write_text(json.dumps({'status':'interrupted_by_host_restart',
            'previous_boot_id':'old-boot','observed_boot_id':'new-local-boot','native_tests_produced':False,'native_binary_produced':False,
            'prior_pipeline':{'path':str(self.interrupted),'sha256':v.sha(self.interrupted)},'process_identities':[]}))
        input_artifacts={role:{'path':str(path),'sha256':v.sha(self.data/path.name)} for role,path in self.inputs.items()}
        self.previous=self.control/'candidate03-pins.json';self.previous.write_text(json.dumps({'input_artifacts':input_artifacts,
            'source_sha256':self.original['sha256'],'expected_native_test_count':106,'additional_native_tests':v.ADDITIONAL_TESTS}))
        def pin(path):return {'path':str(path),'sha256':v.sha(path)}
        historicalfreeze=self.control/'historical-source-freeze.json';historicalfreeze.write_text(json.dumps({
            'schema':'orbit-poc-candidate06-source-freeze-v1','source':self.historical_source,'commit':'a'*40,'regression_suite':historical_regression}))
        previousfreeze=self.control/'previous-source-freeze.json';previousfreeze.write_text(json.dumps({
            'schema':'orbit-poc-candidate07-source-freeze-v1','source':self.previous_source,'commit':'b'*40,'original_native_test_count':106,'regression_suite':previous_regression}))
        newfreeze=self.control/'new-source-freeze.json';newfreeze.write_text(json.dumps({
            'schema':'orbit-poc-candidate09-source-freeze-v1','source':self.frozen,'commit':'c'*40,'original_native_test_count':106,'regression_suite':regression}))
        failures={}
        for number in ('04','05','06','07','08'):
            source=self.original if number in ('04','05') else self.historical_source if number=='06' else self.previous_source
            record={'status':'failed','source':source,'finished_at':'finished','final_cleanup':{'verified':True},'resume':{'status':'not_applicable','reason':'no_campaign_running'}}
            if number in ('05','06','08'):record['native']={'sha256':'b'*64}
            path=self.control/('failed'+number+'.json');path.write_text(json.dumps(record));failures[number]=pin(path)
        pastchanges={name:{'before':self.historical_source['files'].get(name),'after':value} for name,value in self.previous_source['files'].items() if self.historical_source['files'].get(name)!=value}
        previouslineage=self.control/'previous-lineage.json';previouslineage.write_text(json.dumps({'schema':'orbit-poc-correctness-correction-lineage-v2',
            'original_source_freeze':pin(self.source_freeze),'previous_source_freeze':pin(historicalfreeze),'previous_source_sha256':self.historical_source['sha256'],'new_source_freeze':pin(previousfreeze),'original_source_sha256':self.original['sha256'],
            'new_source_sha256':self.previous_source['sha256'],'changes':pastchanges,**{'failed_pipeline'+n:failures[n] for n in ('04','05','06')}}))
        changes={name:{'before':self.previous_source['files'].get(name),'after':value} for name,value in self.frozen['files'].items() if self.previous_source['files'].get(name)!=value}
        lineage=self.control/'lineage.json';lineage.write_text(json.dumps({'schema':'orbit-poc-correctness-correction-lineage-v3',
            'original_source_freeze':pin(self.source_freeze),'previous_source_freeze':pin(previousfreeze),'previous_source_sha256':self.previous_source['sha256'],'new_source_freeze':pin(newfreeze),'original_source_sha256':self.original['sha256'],
            'previous_correction_lineage':pin(previouslineage),'new_source_sha256':self.frozen['sha256'],'changes':changes,**{'failed_pipeline'+n:failures[n] for n in ('04','05','06','07','08')}}))
        self.pins={'schema':'orbit-poc-correctness-candidate09-pins-v1','source_sha256':self.frozen['sha256'],'source_file_count':772,
            'driver_sha256':v.sha(v.__file__),'wrapper_sha256':v.sha(self.paths['wrapper']),'execution_sha256':v.sha(self.execution_path),
            'additional_native_tests':v.ADDITIONAL_TESTS.copy(),'expected_native_test_count':106,'input_artifacts':input_artifacts,
            'candidate03_pins':{'path':str(self.previous),'sha256':v.sha(self.previous)},
            'source_freeze':{'path':str(self.source_freeze),'sha256':v.sha(self.source_freeze)},
            'interruption_record':{'path':str(self.restart),'sha256':v.sha(self.restart)},
            'previous_source_freeze':pin(previousfreeze),'previous_correction_lineage':pin(previouslineage),'new_source_freeze':pin(newfreeze),'correction_lineage':pin(lineage),'allowed_correction_paths':sorted(changes),
            'regression_suite':regression,'recovery_verifier_sha256':v.sha(HERE/'recovery_evidence_09.py')}
        self.pin_path=self.control/'pins.json'
        for key,value in {'PINNED_INPUTS':self.inputs,'PRIOR':self.inputs['prior_validation'],'PREVIOUS_SOURCE_SHA256':self.previous_source['sha256'],
            'PREVIOUS_SOURCE_FILE_COUNT':771,'ORIGINAL_SOURCE_SHA256':self.original['sha256'],
            'CANDIDATE03_PINS_SHA256':v.sha(self.previous)}.items():self.stack.enter_context(mock.patch.object(v,key,value))
    def tearDown(self):self.stack.close();self.tmp.cleanup()
    def load(self):
        self.pin_path.write_text(json.dumps(self.pins));return v.load_required_pins(self.pin_path,self.execution_path)
    def verify(self):return v.verify_pins(self.load(),self.execution,self.execution_path)
    def update_restart(self,value):
        self.restart.write_text(json.dumps(value));self.pins['interruption_record']['sha256']=v.sha(self.restart)
    def test_exact_candidate_with_remote_aliases_validates(self):self.assertEqual(self.verify(),self.frozen)
    def test_execution_contract_validates(self):self.assertEqual(v.load_execution(self.execution_path),self.execution)
    def test_unknown_pin_field_rejected(self):
        self.pins['extra']=True
        with self.assertRaisesRegex(RuntimeError,'Unknown or missing'):self.load()
    def test_unknown_execution_field_rejected(self):
        self.execution['extra']=1;self.execution_path.write_text(json.dumps(self.execution))
        with self.assertRaisesRegex(RuntimeError,'Unknown or missing'):v.load_execution(self.execution_path)
    def test_unset_pin_rejected(self):
        self.pins['driver_sha256']=None
        with self.assertRaisesRegex(RuntimeError,'digest'):self.load()
    def test_source_count_immutable(self):
        self.pins['source_file_count']=757
        with self.assertRaisesRegex(RuntimeError,'frozen source'):self.load()
    def test_source_count_must_match_explicit_freeze(self):
        self.pins['source_file_count']=766
        with self.assertRaisesRegex(RuntimeError,'frozen source'):self.load()
    def test_regression_count_must_match_explicit_freeze(self):
        self.pins['regression_suite']['expected_count']=20
        with self.assertRaisesRegex(RuntimeError,'regression inventory'):self.load()
    def test_previous07_source_pin_cannot_be_substituted(self):
        self.pins['previous_source_freeze']=self.pins['source_freeze']
        with self.assertRaisesRegex(RuntimeError,'frozen source'):self.load()
    def test_unpinned_new_freeze_is_rejected(self):
        self.pins['new_source_freeze']['sha256']='f'*64
        with self.assertRaisesRegex(RuntimeError,'Source freeze pin changed'):self.load()
    def test_exact_106_inventory_required(self):
        self.pins['expected_native_test_count']=105
        with self.assertRaisesRegex(RuntimeError,'106'):self.load()
    def test_extra_or_missing_native_test_rejected(self):
        self.pins['additional_native_tests'].append('tests/test_other.py')
        with self.assertRaisesRegex(RuntimeError,'106'):self.load()
    def test_canonical_input_path_cannot_be_relocated(self):
        self.pins['input_artifacts']['initial_state']['path']='/elsewhere'
        with self.assertRaisesRegex(RuntimeError,'canonical path'):self.load()
    def test_input_changed_rejected(self):
        (self.data/'initial_state.json').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'Prescribed input changed'):self.verify()
    def test_rehashed_input_cannot_replace_original(self):
        self.pins['input_artifacts']['initial_state']['sha256']='a'*64
        with self.assertRaisesRegex(RuntimeError,'Scientific inputs differ'):self.verify()
    def test_source_change_rejected(self):
        (self.source/'file-0').write_text('changed')
        with self.assertRaisesRegex(ValueError,'source inventory differs'):self.verify()
    def test_extra_source_file_rejected(self):
        (self.source/'extra').write_text('extra')
        with self.assertRaisesRegex(ValueError,'source inventory differs'):self.verify()
    def test_source_symlink_rejected(self):
        (self.source/'file-0').unlink();(self.source/'file-0').symlink_to(self.source/'file-1')
        with self.assertRaisesRegex(RuntimeError,'symlink'):self.verify()
    def test_prior_source_freeze_tamper_rejected(self):
        self.source_freeze.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'Historical artifact changed'):self.verify()
    def test_runtime_change_rejected(self):
        (self.root/'python-tool').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'Runtime pin changed'):self.verify()
    def test_execution_change_rejected(self):
        self.execution_path.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'Execution configuration changed'):self.load()
    def test_same_boot_cannot_claim_interruption(self):
        x=json.loads(self.restart.read_text());x['observed_boot_id']=x['previous_boot_id'];self.update_restart(x)
        with self.assertRaisesRegex(RuntimeError,'not a restart'):self.verify()
    def test_completed_native_work_cannot_claim_build_only_restart(self):
        x=json.loads(self.restart.read_text());x['native_tests_produced']=True;self.update_restart(x)
        with self.assertRaisesRegex(RuntimeError,'not a restart'):self.verify()
    def test_historical_pipeline_changed_rejected(self):
        self.interrupted.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'Interrupted pipeline changed'):self.verify()
    def test_native_test_in_old_pipeline_disagrees_with_restart_claim(self):
        self.interrupted.write_text(json.dumps({'steps':[{'name':'native-tests'}]}))
        x=json.loads(self.restart.read_text());x['prior_pipeline']['sha256']=v.sha(self.interrupted);self.update_restart(x)
        with self.assertRaisesRegex(RuntimeError,'Interruption claim disagrees'):self.verify()
    def test_longest_canonical_alias_wins(self):
        self.execution['read_only_bindings'].append({'source':'/specific','target':'/canonical/input/child'})
        self.assertEqual(v.host_path('/canonical/input/child/file',self.execution),Path('/specific/file'))
    def test_alias_cannot_overlap_output(self):
        self.execution['read_only_bindings'].append({'source':'/tmp','target':str(self.root)})
        self.execution_path.write_text(json.dumps(self.execution))
        with self.assertRaisesRegex(RuntimeError,'overlap writable'):v.load_execution(self.execution_path)
    def test_writable_source_overlap_rejected(self):
        self.execution['paths']['build']=str(self.source/'build');self.execution_path.write_text(json.dumps(self.execution))
        with self.assertRaisesRegex(RuntimeError,'Frozen source'):v.load_execution(self.execution_path)
    def test_cpu_count_exactly_four_build_one_fit(self):
        self.execution['build_cpus']=[0,1];self.execution_path.write_text(json.dumps(self.execution))
        with self.assertRaisesRegex(RuntimeError,'four distinct'):v.load_execution(self.execution_path)
    def test_fresh_outputs_cannot_overwrite_empty_directory(self):
        Path(self.paths['run']).mkdir()
        with self.assertRaisesRegex(RuntimeError,'fresh and absent'):v.prepare_writable_directories(self.paths)
        self.assertFalse(Path(self.paths['build']).exists())
    def test_fresh_outputs_cannot_use_symlink(self):
        Path(self.paths['build']).symlink_to(self.source,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'fresh and absent'):v.prepare_writable_directories(self.paths)
    def test_wrapper_private_pid_and_narrow_write_list(self):
        v.prepare_writable_directories(self.paths)
        # Alias source files exist; root read-only mount protects original and source inputs.
        command,empty=w.namespace_command(self.execution)
        self.assertIn('--unshare-pid',command);self.assertEqual(command[command.index('--ro-bind')+1:command.index('--ro-bind')+3],['/','/'])
        writable=[command[i+1] for i,x in enumerate(command) if x=='--bind']
        self.assertEqual(set(writable),{self.paths[k] for k in v.MUTABLE_KEYS})
        self.assertNotIn(str(self.root),writable);self.assertNotIn(str(self.source),writable);self.assertTrue(empty.is_dir())
    def test_wrapper_rejects_output_symlink(self):
        v.prepare_writable_directories(self.paths);Path(self.paths['build']).rmdir();Path(self.paths['build']).symlink_to(self.source,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'non-real'):w.namespace_command(self.execution)
    def test_junit_never_accepts_skip_or_incomplete_count(self):
        path=self.root/'junit.xml';path.write_text('<testsuite><testcase><skipped/></testcase></testsuite>')
        with self.assertRaisesRegex(RuntimeError,'failures/errors/skips'):v.verify_native_junit(path,1)
        path.write_text('<testsuite><testcase/></testsuite>')
        with self.assertRaisesRegex(RuntimeError,'inventory differs'):v.verify_native_junit(path,106)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.execution={'host':{'hostname':'fixture','boot_id':'boot'},'build_cpus':[0,1,2,3],'fit_cpu':4,'reserved_cpu_note':'fixture'}
        self.selfitem={'pid':os.getpid(),'start_ticks':1,'state':'R','pid_namespace':'host','parent':1,'argv':['python','validate_candidate_09.py']}
        for name,value in [('boot','boot')]:self.stack.enter_context(mock.patch.object(v,name,return_value=value))
        self.stack.enter_context(mock.patch.object(v.socket,'gethostname',return_value='fixture'))
        self.stack.enter_context(mock.patch.object(v.os,'sched_getaffinity',return_value=set(range(8))))
        self.stack.enter_context(mock.patch.object(v,'proc',return_value=self.selfitem))
    def tearDown(self):self.stack.close()
    def test_idle_host_admitted(self):
        with mock.patch.object(v,'command_processes',return_value={os.getpid():self.selfitem}):self.assertEqual(v.admission(self.execution)['status'],'admitted')
    def test_changed_boot_fails_closed(self):
        self.execution['host']['boot_id']='old'
        with self.assertRaisesRegex(RuntimeError,'boot identity'):v.admission(self.execution)
    def test_unavailable_cpu_fails_closed(self):
        self.execution['fit_cpu']=9
        with self.assertRaisesRegex(RuntimeError,'outside current affinity'):v.admission(self.execution)
    def test_external_native_workload_is_never_signaled(self):
        other={**self.selfitem,'pid':999,'argv':['/tmp/groops-abc']}
        with mock.patch.object(v,'command_processes',return_value={999:other}),mock.patch.object(v.os,'killpg',side_effect=AssertionError('must not signal')):
            with self.assertRaisesRegex(RuntimeError,'Competing native'):v.admission(self.execution)
    def test_owned_private_namespace_workload_allowed(self):
        other={**self.selfitem,'pid':999,'argv':['/tmp/groops-abc'],'pid_namespace':'owned'}
        owned=mock.Mock(known={},namespaces={'owned'})
        with mock.patch.object(v,'command_processes',return_value={999:other}):self.assertEqual(v.admission(self.execution,[owned])['status'],'admitted')
    def test_pid_reuse_is_not_ownership(self):
        other={**self.selfitem,'pid':999,'start_ticks':3,'argv':['groops']}
        owned=mock.Mock(known={999:{**other,'start_ticks':2}},namespaces=set())
        with mock.patch.object(v,'command_processes',return_value={999:other}):
            with self.assertRaisesRegex(RuntimeError,'Competing native'):v.admission(self.execution,[owned])
    def test_native_compiler_and_campaign_match(self):
        for args in [['groops-x'],['cc1plus'],['f951'],['ninja'],['python','build_groops.py'],['python','-m','orbit_poc.numerics.campaign'],['python','validate_numerics_objective.py']]:
            self.assertTrue(v.workload({'argv':args,'state':'R'}),args)
    def test_ordinary_shell_and_zombie_are_not_native_work(self):
        self.assertFalse(v.workload({'argv':['bash'],'state':'S'}));self.assertFalse(v.workload({'argv':['groops'],'state':'Z'}))


class StructuralTests(unittest.TestCase):
    def test_corrected_source_production_count_is_frozen(self):self.assertEqual(v.PREVIOUS_SOURCE_FILE_COUNT,771)
    def test_owned_supervision_cleanup_unchanged(self):
        old=ast.parse((HERE/'validate_candidate_03.py').read_text());new=ast.parse((HERE/'validate_candidate_09.py').read_text())
        for name in ('interrupted','cleanup_signals','proc','table','OwnedCommand','supervise'):
            a=next(n for n in old.body if getattr(n,'name',None)==name);b=next(n for n in new.body if getattr(n,'name',None)==name)
            self.assertEqual(ast.dump(a,include_attributes=False),ast.dump(b,include_attributes=False),name)
    def test_no_obsolete_pause_or_resume_call(self):
        tree=ast.parse((HERE/'validate_candidate_09.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):self.assertNotIn(node.func.attr,{'resume','check_spec','verify_boundary'})
        text=(HERE/'validate_candidate_09.py').read_text();self.assertIn("'status':'not_applicable','reason':'no_campaign_running'",text)
    def test_all_scientific_commands_retained_with_limits(self):
        text=(HERE/'validate_candidate_09.py').read_text()
        for name in ('flight-refinement','eccentric-24h-refinement','nuisance-replay','nuisance-replay-candidate1-point012'):self.assertIn("run('"+name+"'",text)
        self.assertIn("for method in ('log_drag_ou','pulses')",text)
        self.assertIn("'--allow-floor-limited'],7500,required=False)",text)
        self.assertIn("'7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'",text)
        self.assertIn("'--numerics','--jobs','4'",text)
        self.assertIn("'-m','pytest','-q','-s','-p','no:cacheprovider'",text)
    def test_missing_sealed_pin_fails_before_any_output(self):
        with tempfile.TemporaryDirectory(prefix='candidate09-empty-',dir=HERE) as folder:
            root=Path(folder);pins=root/'pins';pins.write_text('{}')
            with mock.patch.object(v,'prepare_writable_directories',side_effect=AssertionError('no outputs')):
                with self.assertRaisesRegex(RuntimeError,'Sealed pin file changed'):
                    v.main(['--execution',str(root/'missing'),'--pins',str(pins),'--pins-sha256','a'*64])



class SymlinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='candidate09-links-',dir=HERE);self.root=Path(self.tmp.name)
        self.execution={'read_only_bindings':[{'source':str(self.root),'target':'/canonical'}]}
        (self.root/'real').write_text('actual scientific interpreter')
    def tearDown(self):self.tmp.cleanup()
    def test_absolute_canonical_link_resolves_staged_binary(self):
        (self.root/'python').symlink_to('/canonical/real')
        self.assertEqual(v.resolved_host_path('/canonical/python',self.execution),self.root/'real')
    def test_relative_link_resolves_staged_binary(self):
        (self.root/'python').symlink_to('real')
        self.assertEqual(v.resolved_host_path('/canonical/python',self.execution),self.root/'real')
    def test_nested_prefix_link_resolves_staged_binary(self):
        (self.root/'env').mkdir();(self.root/'env'/'python').symlink_to('/canonical/real');(self.root/'venv').symlink_to('/canonical/env')
        self.assertEqual(v.resolved_host_path('/canonical/venv/python',self.execution),self.root/'real')
    def test_cycle_fails_closed(self):
        (self.root/'a').symlink_to('/canonical/b');(self.root/'b').symlink_to('/canonical/a')
        with self.assertRaisesRegex(RuntimeError,'cycle'):v.resolved_host_path('/canonical/a',self.execution)
    def test_missing_target_fails_closed(self):
        (self.root/'a').symlink_to('/canonical/missing')
        with self.assertRaisesRegex(RuntimeError,'missing'):v.resolved_host_path('/canonical/a',self.execution)
    def test_symlink_traversal_limit_fails_closed(self):
        for i in range(70):(self.root/str(i)).symlink_to('/canonical/'+str(i+1))
        (self.root/'70').write_text('end')
        with self.assertRaisesRegex(RuntimeError,'limit'):v.resolved_host_path('/canonical/0',self.execution)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='candidate09-lifecycle-',dir=HERE);self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir();self.control=self.root/'control';self.control.mkdir()
        self.paths={key:str(self.root/key) for key in v.PATH_KEYS};self.paths.update(source=str(self.source),control=str(self.control),wrapper=str(HERE/'with_correctness_namespace_09.py'))
        self.execution={'paths':self.paths,'runtime_artifacts':{'control_python':{'path':str(Path(v.sys.executable).resolve())}},'build_cpus':[0,1,2,3],'fit_cpu':4}
        self.execution_path=self.control/'execution.json';self.execution_path.write_text('{}');self.pin_path=self.control/'pins.json';self.pin_path.write_text('{}')
        self.prior=self.control/'prior.json';self.prior.write_text('{}');self.interruption=self.control/'interruption.json';self.interruption.write_text('{}')
        self.pins={'execution_sha256':v.sha(self.execution_path),'additional_native_tests':v.ADDITIONAL_TESTS,
                   'interruption_record':{'path':str(self.interruption)},'correction_lineage':{'path':str(self.interruption)},
                   'regression_suite':{'files':['tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py','tests/test_numerics_new_precision.py'],'expected_count':19}}
        self.stack=ExitStack();self.cleanups=[];self.started=[]
        for name,result in [('load_execution',self.execution),('load_required_pins',self.pins),('verify_pins',{'files':{},'sha256':'mock'}),('admission',{'status':'admitted'})]:
            self.stack.enter_context(mock.patch.object(v,name,return_value=result))
        self.stack.enter_context(mock.patch.object(v,'host_path',side_effect=lambda path,execution:Path(path)))
        self.stack.enter_context(mock.patch.object(v,'PRIOR',self.prior))
        self.stack.enter_context(mock.patch.object(v.signal,'signal'))
    def tearDown(self):self.stack.close();self.tmp.cleanup()
    def call(self):return v.main(['--execution',str(self.execution_path),'--pins',str(self.pin_path),'--pins-sha256',v.sha(self.pin_path)])
    def child(self,argv,**kwargs):
        cleanup={'verified':True,'live_owned_processes':[]};owner=mock.Mock();owner.child.poll.return_value=0;owner.last_cleanup=cleanup
        owner.cleanup.side_effect=lambda **k:self.cleanups.append(k) or cleanup;kwargs['registry'].append(owner)
        self.started.append(argv);kwargs['on_started'](987654)
        if any(str(x).endswith('/scripts/build_groops.py') for x in argv):
            build=Path(self.paths['build']);(build/'groops').write_text('fake binary')
            (build/'build-manifest.json').write_text(json.dumps({'executable_sha256':v.sha(build/'groops')}))
        if 'pytest' in argv:
            name='correction-regression-tests.xml' if any('regression-tests.xml' in str(arg) for arg in argv) else 'native-tests.xml'
            count=self.pins['regression_suite']['expected_count'] if name.startswith('correction') else 106
            (Path(self.paths['run'])/name).write_text('<testsuite>'+'<testcase/>'*count+'</testsuite>')
        kwargs['on_finished']({'cleanup':cleanup,'elapsed_seconds':.01,'interrupted_or_timeout':False})
        return 0
    def test_interruption_records_failure_and_cleanup_without_resume(self):
        def failed(argv,**kwargs):self.child(argv,**kwargs);raise KeyboardInterrupt('fabricated cancellation')
        with mock.patch.object(v,'supervise',side_effect=failed),mock.patch.object(v.os,'kill',side_effect=AssertionError('no signals to old jobs')):
            with self.assertRaises(KeyboardInterrupt):self.call()
        journal=json.loads((Path(self.paths['run'])/'pipeline.json').read_text())
        self.assertEqual(journal['status'],'failed');self.assertTrue(journal['final_cleanup']['verified'])
        self.assertEqual(journal['resume'],{'status':'not_applicable','reason':'no_campaign_running'});self.assertEqual(len(self.cleanups),1)
    def test_all_steps_execute_serially_with_distinct_replays(self):
        with mock.patch.object(v,'supervise',side_effect=self.child):self.assertEqual(self.call(),0)
        journal=json.loads((Path(self.paths['run'])/'pipeline.json').read_text())
        self.assertEqual(journal['schema'],'orbit-poc-correctness-validation09-run-v1')
        self.assertEqual(len(journal['steps']),13);self.assertEqual(journal['native_test_inventory']['passed'],106)
        self.assertEqual(journal['correction_regression_inventory']['passed'],19)
        self.assertEqual(journal['status'],'passed');self.assertEqual(len(self.cleanups),13)
        replay=[s for s in journal['steps'] if s['name'].startswith('nuisance-replay')]
        sources=[s['argv'][s['argv'].index('--source-profile')+1] for s in replay]
        self.assertEqual(len(set(sources)),2)
    def test_failed_separate_regressions_preserve_original_gates_and_replays(self):
        def child(argv,**kwargs):
            code=self.child(argv,**kwargs)
            return 1 if any('correction-regression-tests.xml' in str(arg) for arg in argv) else code
        with mock.patch.object(v,'supervise',side_effect=child):self.assertEqual(self.call(),1)
        journal=json.loads((Path(self.paths['run'])/'pipeline.json').read_text())
        self.assertEqual(journal['status'],'failed');self.assertEqual(journal['native_test_inventory']['passed'],106)
        self.assertEqual(len(journal['steps']),13)
        self.assertEqual(len([s for s in journal['steps'] if s['name'].startswith('nuisance-replay')]),2)
    def test_preexisting_run_never_reused(self):
        Path(self.paths['run']).mkdir()
        with mock.patch.object(v,'supervise',side_effect=AssertionError('must not launch')):
            with self.assertRaisesRegex(RuntimeError,'fresh and absent'):self.call()


if __name__=='__main__':unittest.main(verbosity=2)

