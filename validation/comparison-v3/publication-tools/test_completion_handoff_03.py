"""Fictional local fixtures only; no actual campaign, collector or estimator runs."""
from contextlib import ExitStack
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('handoff03',Path(__file__).with_name('completion_handoff_03.py'))
h=importlib.util.module_from_spec(spec);sys.modules[spec.name]=h;spec.loader.exec_module(h)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.campaign=self.root/'campaign';self.campaign.mkdir()
        self.project=self.root/'project';(self.project/'src').mkdir(parents=True)
        files={}
        for i in range(89):
            path=self.project/f'src/fictional{i}.py';path.write_text(f'# FICTIONAL RUNTIME {i}\n')
            files[str(path.relative_to(self.project))]=h.sha(path)
        helpers=self.root/'helpers';helpers.mkdir()
        self.collector=helpers/'harvest_v3.py';self.collector.write_text('# FICTIONAL COLLECTOR; NEVER EXECUTED\n')
        renderer=helpers/'render_v3_figures.py';renderer.write_text('# FICTIONAL RENDERER; NEVER EXECUTED\n')
        native=self.root/'native';native.write_text('FICTIONAL NONEXECUTABLE NATIVE')
        protocol={'source':{'sha256':h.canonical(files),'files':files},'native_binary':{'path':str(native),'sha256':h.sha(native)}}
        protocol['protocol_hash']=h.canonical(protocol)
        self.stack.enter_context(patch.multiple(h,SOURCE=protocol['source']['sha256'],PROTOCOL=protocol['protocol_hash'],
            NATIVE=h.sha(native),COLLECTOR=h.sha(self.collector),RENDERER=h.sha(renderer)))
        h.atomic_json(self.campaign/'protocol.json',protocol)
        self.settings=h.Settings(self.campaign,self.project,self.collector,self.root/'publication/v3',
            python='fictional-python',poll_seconds=.01,max_wait_hours=.01)
        self.calls=[]

    def complete_driver(self):
        h.atomic_json(self.campaign/'campaign-driver.json',{'status':'complete','stages':[
            {'stage':stage,'status':'complete','protocol_hash':h.PROTOCOL} for stage in ('synthetic','flight')]})

    def make_bundle(self):
        root=self.settings.output;root.mkdir(parents=True)
        inventory=[]
        def save(name,value,original=False,compressed=False):
            payload=(json.dumps(value,sort_keys=True)+'\n').encode() if isinstance(value,dict) else value
            path=root/(name+('.gz' if compressed else ''));path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(gzip.compress(payload,mtime=0) if compressed else payload)
            if original:
                import hashlib
                inventory.append({'published_path':str(path.relative_to(root)),'published_sha256':h.sha(path),
                    'published_bytes':path.stat().st_size,'source_sha256':hashlib.sha256(payload).hexdigest(),
                    'source_bytes':len(payload),'encoding':'gzip_original_bytes' if compressed else 'original_bytes'})
            return path
        save('protocol.json',(self.campaign/'protocol.json').read_bytes(),True)
        save('campaign-driver.json',(self.campaign/'campaign-driver.json').read_bytes(),True)
        gates={'protocol_hash':h.PROTOCOL,'gates':{name:{'passed':True} for name in h.GATES}}
        gates['evidence_hash']=h.canonical(gates);save('acceptance-gates.json',gates,True)
        selections={};freezes={};metrics=[];failures=[];scores=[]
        for stage in ('synthetic','flight'):
            for prefix in ('driver','calibration-input-preparation'):
                save(f'{prefix}-{stage}.json',{'fictional':True},True)
            selection={'protocol_hash':h.PROTOCOL,'selections':{},'evidence':[],'calibration_adequate':False,
                'calibration_disclosures':['FICTIONAL boundary limitation'],'boundary_diagnostics':{}}
            selection_hash=h.canonical(selection)
            calibration={**selection,'selection_hash':selection_hash,'complete':True,'source_hash':h.SOURCE,'stage':stage,
                'runs':[{'id':'FICTIONAL invalid calibration','valid':False},{'id':'FICTIONAL valid calibration','valid':True}]}
            selections[stage]=selection_hash;save(f'calibration-{stage}.json',calibration,True)
            for row in calibration['runs']:
                score={'stage':stage,**row};scores.append(score)
                if not row['valid']:failures.append({'phase':'calibration','failure_kind':'invalid_candidate_arc_holdout',**score})
            freezes[stage]={'stage':stage,'status':'frozen','source_hash':h.SOURCE,'protocol_hash':h.PROTOCOL,
                'selection_hash':selection_hash,'native_binary':h.read(self.campaign/'protocol.json')['native_binary'],
                'prepare_results':[],'campaign_case_counts':{}}
        for name,count in h.CAMPAIGNS.items():
            stage='synthetic' if name in ('synthetic','stress') else 'flight'
            kind='primary' if name in ('synthetic','flight') else name
            methods=['groops_pulses_ar'] if name=='flight_ar_reference' else ['groops_log_drag_ou','groops_pulses']
            cases=[{'fictional_case':f'{name}-{index}'} for index in range(count//len(methods))]
            rows=[]
            for case in cases:
                freezes[stage]['prepare_results'].append({'case':case,'campaign':kind})
                for method in methods:
                    index={'status':'excluded','result_path':f'/FICTIONAL/{case["fictional_case"]}/{method}',
                        'result_sha256':'f'*64,'request_hash':'e'*64}
                    rows.append({'case':case,'method':method,'valid':False,'fit_record':index,'status':'excluded'})
                    metric={'campaign':name,'case':case,'method':method,'parameters':None,'status':'excluded',
                        'converged':False,'covariance_valid':False,'evaluation_status':'not_run','metrics':{},
                        'source_fit_record':index,'source_evaluation_record':None,'error':'FICTIONAL exclusion'}
                    metrics.append(metric);failures.append({'phase':'evaluation','failure_kind':'invalid_or_unavailable_fit_or_evaluation',**metric})
            freezes[stage]['campaign_case_counts'][kind]=len(cases)
            save(f'run-{name}.json',{'complete':True,'status':'complete','source_hash':h.SOURCE,'protocol_hash':h.PROTOCOL,
                'stage':stage,'campaign':kind,'selection_hash':selections[stage],'methods':methods,
                'expected_fits':count,'planned_cases':cases,'runs':rows},True)
            report={'source_hash':h.SOURCE,'protocol_hash':h.PROTOCOL,'orchestration_complete':True,
                'planned_design_complete':True,'expected_fits':count,'observed_fits':count,
                'planned_fit_rows':count,'missing_planned_fits':0,'metrics_error':None,'selection_hash':selections[stage]}
            save(f'report-{name}/report.json',report,True,compressed=name=='synthetic')
            save(f'report-{name}/index.html',b'FICTIONAL QA ONLY',True)
        save('summary.json',{'source_hash':h.SOURCE,'protocol_hash':h.PROTOCOL,'native_binary_sha256':h.NATIVE,
            'execution_complete':True,'superiority_claim_issued':False,'failure_counts':{'evaluation':1650,'calibration':2}})
        for stage,frozen in freezes.items():
            frozen['input_freeze_hash']=h.canonical(frozen);save(f'evaluation-input-freeze-{stage}.json',frozen,True)
        for name in ('index.html','raw-artifact-locators.jsonl'):
            save(name,b'FICTIONAL QA ONLY')
        for name,rows in (('metrics.jsonl',metrics),('calibration-scores.jsonl',scores),('failures.jsonl',failures)):
            save(name,(''.join(json.dumps(row,sort_keys=True)+'\n' for row in rows)).encode())
        save('postprocessing/harvest_v3.py',self.collector.read_bytes(),True)
        save('postprocessing/render_v3_figures.py',self.collector.with_name('render_v3_figures.py').read_bytes(),True)
        figures=[]
        for stem in h.FIGURES:
            for extension in ('png','svg'):
                path=save(f'figures/{stem}.{extension}',b'FICTIONAL IMAGE PLACEHOLDER')
                figures.append({'path':path.name,'sha256':h.sha(path)})
        inputs=[]
        for name in ('summary.json','report-synthetic/report.json'):
            _,path,payload_hash=h.json_artifact(root,name)
            inputs.append({'path':str(path.relative_to(root)),'sha256':h.sha(path),'uncompressed_payload_sha256':payload_hash})
        save('figures/figure-manifest.json',{'fictional_fixture':False,'renderer_sha256':h.RENDERER,
            'source_hash':h.SOURCE,'protocol_hash':h.PROTOCOL,'statistics_recomputed':False,'figures':figures,'inputs':inputs})
        save('file-inventory.json',{'original_files':inventory})
        self.seal_bundle(len(inventory))

    def seal_bundle(self,original_count=None):
        root=self.settings.output
        if original_count is None:original_count=h.read(root/'publication.json')['collected_original_files']
        files={str(path.relative_to(root)):h.sha(path) for path in sorted(root.rglob('*')) if path.is_file() and path.name!='publication.json'}
        h.atomic_json(root/'publication.json',{'files':files,'bundle_content_hash':h.canonical(files),
            'protocol_hash':h.PROTOCOL,'collector_sha256':h.COLLECTOR,'collected_original_files':original_count})

    def run_fake(self,argv,control,label,lock_fd):
        self.calls.append(argv)
        if argv[-1]=='--check-only':
            value={'ready':True,'protocol_hash':h.PROTOCOL,'expected_source':h.SOURCE,'expected_evaluation_fits':1650}
        else:
            self.assertEqual(argv[-1],'--collect');self.make_bundle();value={'status':'published'}
        stdout=control/(label+'.stdout.json');stderr=control/(label+'.stderr.log')
        h.atomic_json(stdout,value);stderr.write_text('')
        return {'argv':argv,'returncode':0,'stdout':str(stdout),'stdout_sha256':h.sha(stdout),
            'stderr':str(stderr),'stderr_sha256':h.sha(stderr)}

    def test_wait_then_complete_collect_once_and_verify_on_resume(self):
        sleeps=[]
        def sleeper(delay):sleeps.append(delay);self.complete_driver()
        with patch.object(h,'run_logged',side_effect=self.run_fake):
            result=h.handoff(self.settings,sleeper=sleeper)
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['verification']['expected_evaluation_fits'],1650)
            self.assertEqual(result['upstream']['source_files_rehashed'],89)
            self.assertEqual([args[-1] for args in self.calls],['--check-only','--collect'])
            self.assertEqual(len(sleeps),1)
            for argv in self.calls:
                self.assertEqual(argv[:2],['fictional-python',str(self.collector)])
                self.assertEqual(argv[argv.index('--expected-source')+1],h.SOURCE)
            before=h.sha(self.settings.output/'publication.json')
            resumed=h.handoff(self.settings)
            self.assertEqual(resumed['status'],'complete');self.assertTrue(resumed['reused_existing_bundle'])
            self.assertEqual(len(self.calls),2);self.assertEqual(h.sha(self.settings.output/'publication.json'),before)

    def test_driver_failure_is_terminal_and_preserved_without_retry(self):
        failure={'status':'failed','stages':[{'stage':'synthetic','status':'failed','error':'FICTIONAL FAILURE'}]}
        h.atomic_json(self.campaign/'campaign-driver.json',failure)
        with patch.object(h,'run_logged') as command:
            first=h.handoff(self.settings);before=(self.settings.control/'status.json').read_bytes()
            self.complete_driver();second=h.handoff(self.settings)
            self.assertEqual(first['status'],'blocked');self.assertEqual(first['driver'],failure)
            self.assertEqual(first,second);self.assertEqual((self.settings.control/'status.json').read_bytes(),before)
            command.assert_not_called()

    def test_failed_readiness_or_collector_is_not_retried(self):
        for fail_phase in ('--check-only','--collect'):
            with self.subTest(fail_phase=fail_phase):
                # Separate control/output parent for each explicitly fictional scenario.
                settings=h.Settings(self.campaign,self.project,self.collector,self.root/fail_phase/'v3')
                self.complete_driver();calls=[]
                def command(argv,control,label,lock_fd):
                    calls.append(argv[-1]);stdout=control/(label+'.stdout.json');stderr=control/(label+'.stderr.log')
                    h.atomic_json(stdout,{'ready':True,'protocol_hash':h.PROTOCOL,'expected_source':h.SOURCE,'expected_evaluation_fits':1650})
                    stderr.write_text('FICTIONAL failure retained')
                    return {'returncode':2 if argv[-1]==fail_phase else 0,'stdout':str(stdout),'stderr':str(stderr)}
                with patch.object(h,'run_logged',side_effect=command):
                    result=h.handoff(settings);self.assertEqual(result['status'],'blocked')
                    original_calls=calls.copy();h.handoff(settings);self.assertEqual(calls,original_calls)
                    self.assertIn('FICTIONAL failure retained',Path(result['command']['stderr']).read_text())
                self.assertFalse(settings.output.exists())

    def test_interrupted_wait_can_resume_but_interrupted_collect_without_bundle_cannot(self):
        with patch.object(h,'run_logged') as command:
            result=h.handoff(self.settings,sleeper=lambda _:(_ for _ in ()).throw(KeyboardInterrupt()))
            self.assertEqual(result['status'],'interrupted');self.assertFalse(result['collection_started']);command.assert_not_called()
        self.complete_driver()
        def interrupt_collect(argv,*args):
            if argv[-1]=='--collect':raise KeyboardInterrupt()
            return self.run_fake(argv,*args)
        with patch.object(h,'run_logged',side_effect=interrupt_collect):
            interrupted=h.handoff(self.settings);self.assertTrue(interrupted['collection_started'])
        with patch.object(h,'run_logged') as command:
            blocked=h.handoff(self.settings);command.assert_not_called()
            self.assertEqual(blocked['phase'],'interrupted_collection')
        self.assertTrue(list(self.settings.control.glob('*-interrupted.json')))

    def test_crash_after_bundle_rename_resumes_with_hash_verification_only(self):
        self.complete_driver()
        def crash_after_collect(argv,*args):
            value=self.run_fake(argv,*args)
            if argv[-1]=='--collect':raise KeyboardInterrupt()
            return value
        with patch.object(h,'run_logged',side_effect=crash_after_collect):
            result=h.handoff(self.settings);self.assertEqual(result['status'],'interrupted')
        with patch.object(h,'run_logged') as command:
            resumed=h.handoff(self.settings);command.assert_not_called()
            self.assertEqual(resumed['status'],'complete');self.assertTrue(resumed['reused_existing_bundle'])

    def test_lock_timeout_binding_and_protected_paths(self):
        with h.exclusive_lock(self.settings.control):
            with self.assertRaisesRegex(RuntimeError,'holds'):h.handoff(self.settings)
        clock=iter([0,100])
        result=h.handoff(self.settings,monotonic=lambda:next(clock));self.assertEqual(result['phase'],'wait_limit')
        self.assertFalse(self.settings.output.exists())
        different=h.Settings(self.campaign,self.root/'different-project',self.collector,self.settings.output)
        with self.assertRaisesRegex(ValueError,'binding differs'):h.handoff(different)
        for protected in (self.campaign,self.project,self.collector.parent):
            unsafe=h.Settings(self.campaign,self.project,self.collector,protected/'v3')
            with self.assertRaisesRegex(ValueError,'outside'):h.handoff(unsafe)

    def test_changed_runtime_or_reviewed_helper_blocks_before_commands(self):
        self.complete_driver();(self.project/'src/fictional0.py').write_text('# changed')
        with patch.object(h,'run_logged') as command:
            result=h.handoff(self.settings);command.assert_not_called()
            self.assertIn('runtime snapshot changed',result['reason'])
        other=h.Settings(self.campaign,self.project,self.collector,self.root/'other/v3')
        self.collector.write_text('# changed')
        result=h.handoff(other);self.assertIn('reviewed',result['reason'])

    def test_bundle_verification_rejects_tampering_unlisted_files_and_fictional_figures(self):
        self.complete_driver();self.make_bundle()
        verified=h.verify_bundle(self.settings.output);self.assertEqual(verified['verified_figures'],6)
        extra=self.settings.output/'unlisted.txt';extra.write_text('bad')
        with self.assertRaisesRegex(ValueError,'unlisted'):h.verify_bundle(self.settings.output)
        extra.unlink();inventory_path=self.settings.output/'file-inventory.json';saved=inventory_path.read_bytes()
        inventory=h.read(inventory_path);inventory['original_files'][0]['source_sha256']='0'*64
        h.atomic_json(inventory_path,inventory);self.seal_bundle()
        with self.assertRaisesRegex(ValueError,'payload changed'):h.verify_bundle(self.settings.output)
        inventory_path.write_bytes(saved)
        figures_path=self.settings.output/'figures/figure-manifest.json';figures=h.read(figures_path)
        figures['fictional_fixture']=True;h.atomic_json(figures_path,figures);self.seal_bundle()
        with self.assertRaisesRegex(ValueError,'fictional'):h.verify_bundle(self.settings.output)

    def test_previously_completed_bundle_change_blocks_and_preserves_history(self):
        self.complete_driver()
        with patch.object(h,'run_logged',side_effect=self.run_fake):h.handoff(self.settings)
        path=self.settings.output/'publication.json';record=h.read(path);record['unexpected_edit']=True;h.atomic_json(path,record)
        with patch.object(h,'run_logged') as command:
            result=h.handoff(self.settings);command.assert_not_called()
            self.assertEqual(result['status'],'blocked');self.assertIn('manifest changed',result['reason'])
        self.assertTrue(list(self.settings.control.glob('*-complete.json')))

    def test_runtime_change_during_collection_prevents_completed_handoff(self):
        self.complete_driver()
        def change_after_collect(argv,*args):
            value=self.run_fake(argv,*args)
            if argv[-1]=='--collect':(self.project/'src/fictional0.py').write_text('# changed after collect')
            return value
        with patch.object(h,'run_logged',side_effect=change_after_collect):result=h.handoff(self.settings)
        self.assertEqual(result['status'],'blocked');self.assertIn('runtime snapshot changed',result['reason'])
        self.assertTrue(self.settings.output.exists())

    def test_logged_child_inherits_destination_lock_descriptor(self):
        with h.exclusive_lock(self.settings.control) as descriptor:
            # Toy subprocess only, proving pass_fds/logging without invoking a collector.
            argv=[sys.executable,'-c','import os,sys; os.fstat(int(sys.argv[1])); print("fictional child")',str(descriptor)]
            result=h.run_logged(argv,self.settings.control,'fictional-child',descriptor)
            self.assertEqual(result['returncode'],0)
            self.assertEqual(Path(result['stdout']).read_text().strip(),'fictional child')
            self.assertEqual(result['stdout_sha256'],h.sha(result['stdout']))
            with self.assertRaises(FileExistsError):h.run_logged(argv,self.settings.control,'fictional-child',descriptor)

    def test_missing_duplicate_or_unfrozen_metrics_and_failure_rows_are_rejected(self):
        self.complete_driver();self.make_bundle()
        verified=h.verify_bundle(self.settings.output)
        self.assertEqual(verified['verified_metric_rows'],1650)
        self.assertEqual(verified['verified_failure_rows'],1652)
        self.assertEqual(verified['verified_calibration_rows'],4)
        for filename,mutate in (
            ('metrics.jsonl',lambda rows:rows.pop()),
            ('metrics.jsonl',lambda rows:rows.__setitem__(0,rows[1])),
            ('metrics.jsonl',lambda rows:rows[0].update(case={'fictional_case':'UNFROZEN'})),
            ('failures.jsonl',lambda rows:rows.pop()),
            ('failures.jsonl',lambda rows:rows.pop(0)),
            ('calibration-scores.jsonl',lambda rows:rows.pop())):
            with self.subTest(filename=filename,mutation=mutate):
                path=self.settings.output/filename;original=path.read_bytes()
                rows=[json.loads(line) for line in path.read_text().splitlines()];mutate(rows)
                path.write_text(''.join(json.dumps(row)+'\n' for row in rows));self.seal_bundle()
                with self.assertRaisesRegex(ValueError,'Metrics|Archived (failure|calibration-score)'):
                    h.verify_bundle(self.settings.output)
                path.write_bytes(original);self.seal_bundle()

    def test_publication_size_limit_applies_even_to_listed_hashed_files(self):
        self.complete_driver();self.make_bundle()
        largest=max(path.stat().st_size for path in self.settings.output.rglob('*') if path.is_file())
        with patch.object(h,'MAX_ARTIFACT_BYTES',largest-1):
            with self.assertRaisesRegex(ValueError,'95 MiB cap'):h.verify_bundle(self.settings.output)


if __name__=='__main__':unittest.main()
