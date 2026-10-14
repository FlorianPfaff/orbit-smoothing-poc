"""Fictional manifests and mocked Git/SSH only. Never read campaign outcomes."""
from contextlib import ExitStack
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import publication_worker_03 as w


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.repo=self.root/'local';self.repo.mkdir()
        (self.repo/'src').mkdir()
        files={}
        for i in range(89):
            path=self.repo/f'src/runtime{i}.py';path.write_text('# FICTIONAL RUNTIME\n'+str(i))
            files[path.relative_to(self.repo).as_posix()]=w.sha(path)
        self.protocol={'source':{'files':files,'sha256':w.canonical(files)},
            'native_binary':{'path':'FICTIONAL NONEXECUTABLE','sha256':'fictional-native'}}
        self.protocol['protocol_hash']=w.canonical(self.protocol)
        values={'SOURCE':self.protocol['source']['sha256'],'PROTOCOL':self.protocol['protocol_hash'],'NATIVE':'fictional-native'}
        self.stack.enter_context(patch.multiple(w,**values));self.stack.enter_context(patch.multiple(w.integrity,**values))
        self.helpers=self.root/'helpers';self.helpers.mkdir()
        for name in ('harvest_v3.py','render_v3_figures.py'):(self.helpers/name).write_text('# FICTIONAL HELPER '+name)
        self.stack.enter_context(patch.multiple(w.integrity,COLLECTOR=w.sha(self.helpers/'harvest_v3.py'),
                                                 RENDERER=w.sha(self.helpers/'render_v3_figures.py')))
        meta=self.repo/w.METADATA;meta.mkdir(parents=True)
        self.save(meta/'manifest.json',{'source_hash':w.SOURCE,'files':[]})
        (self.repo/'runs/v2').mkdir(parents=True);(self.repo/'runs/v2/original.txt').write_text('immutable v2')
        (self.repo/'results.html').write_text('original v2 landing')
        (self.repo/'README.md').write_text('Preamble\n\n## GROOPS comparison protocol v3\n\nOld pending status.\n\n## Completed v2 campaign\n\nOriginal v2 description.\n')
        self.stack.enter_context(patch.object(w,'README_PENDING_SHA',hashlib.sha256(
            b'## GROOPS comparison protocol v3\n\nOld pending status.\n\n').hexdigest()))
        self.bundle=self.root/'bundle/v3';self.bundle.mkdir(parents=True)
        self.control=self.root/'control';self.control.mkdir()
        self.journal=w.Journal(self.control,self.repo)
        self.make_bundle()

    def save(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,sort_keys=True)+'\n')

    def save_lines(self,name,values):
        (self.bundle/name).write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in values))

    def make_bundle(self):
        self.save(self.bundle/'protocol.json',self.protocol)
        self.save(self.bundle/'campaign-driver.json',{'status':'complete','stages':[
            {'stage':stage,'status':'complete','protocol_hash':w.PROTOCOL} for stage in ('synthetic','flight')]})
        gates={'protocol_hash':w.PROTOCOL,'gates':{name:{'passed':True} for name in w.integrity.GATES}}
        gates['evidence_hash']=w.canonical(gates);self.save(self.bundle/'acceptance-gates.json',gates)
        metrics=[];calibration_rows=[]
        for stage in ('synthetic','flight'):
            self.save(self.bundle/f'driver-{stage}.json',{'status':'complete','protocol_hash':w.PROTOCOL})
            self.save(self.bundle/f'calibration-input-preparation-{stage}.json',{'fictional':True})
            calibration={'protocol_hash':w.PROTOCOL,'selections':{'fictional':{}},'evidence':[],
                'calibration_adequate':False,'calibration_disclosures':['Fictional boundary'], 'boundary_diagnostics':{}}
            calibration['selection_hash']=w.canonical(calibration)
            calibration.update(complete=True,stage=stage,source_hash=w.SOURCE,runs=[{'valid':False,'case':'fictional','error':'fixture'}])
            self.save(self.bundle/f'calibration-{stage}.json',calibration)
            calibration_rows.extend({'stage':stage,**row} for row in calibration['runs'])
            frozen={'status':'frozen','stage':stage,'protocol_hash':w.PROTOCOL,'source_hash':w.SOURCE,
                'native_binary':self.protocol['native_binary'],'selection_hash':calibration['selection_hash'],
                'prepare_results':[],'campaign_case_counts':{}}
            for campaign,(candidate_stage,kind,count) in w.CAMPAIGNS.items():
                if stage!=candidate_stage:continue
                methods=['groops_pulses_ar'] if kind=='flight_ar_reference' else ['groops_log_drag_ou','groops_pulses']
                cases=[{'fictional_case':campaign+'-'+str(i)} for i in range(count//len(methods))]
                frozen['prepare_results'].extend({'campaign':kind,'case':case} for case in cases)
                frozen['campaign_case_counts'][kind]=len(cases)
                run={'planned_cases':cases,'methods':methods,'status':'complete','complete':True,'source_hash':w.SOURCE,
                    'stage':stage,'campaign':kind,'expected_fits':count,
                    'protocol_hash':w.PROTOCOL,'selection_hash':calibration['selection_hash'],'runs':[]}
                for case in cases:
                    for method in methods:
                        index={'result_path':'FICTIONAL/'+case['fictional_case']+'/'+method,'result_sha256':'fictional','status':'failed'}
                        run['runs'].append({'case':case,'method':method,'fit_record':index})
                        metrics.append({'campaign':campaign,'case':case,'method':method,'status':'failed',
                            'converged':False,'covariance_valid':False,'evaluation_status':'not_run',
                            'source_fit_record':index,'source_evaluation_record':None,'metrics':{},'error':'FICTIONAL'})
                self.save(self.bundle/f'run-{campaign}.json',run)
                report={'source_hash':w.SOURCE,'protocol_hash':w.PROTOCOL,'selection_hash':calibration['selection_hash'],
                    'orchestration_complete':True,'planned_design_complete':True,'expected_fits':count,'observed_fits':count,
                    'planned_fit_rows':count,'missing_planned_fits':0,'metrics_error':None}
                self.save(self.bundle/f'report-{campaign}/report.json',report)
                (self.bundle/f'report-{campaign}/index.html').write_text('FICTIONAL QA ONLY')
            frozen['input_freeze_hash']=w.canonical(frozen)
            self.save(self.bundle/f'evaluation-input-freeze-{stage}.json',frozen)
        self.save_lines('metrics.jsonl',metrics);self.save_lines('calibration-scores.jsonl',calibration_rows)
        failures=[{'phase':'evaluation','failure_kind':'invalid_or_unavailable_fit_or_evaluation',**row} for row in metrics]
        failures.extend({'phase':'calibration','failure_kind':'invalid_candidate_arc_holdout',**row} for row in calibration_rows)
        self.save_lines('failures.jsonl',failures)
        self.save(self.bundle/'summary.json',{'source_hash':w.SOURCE,'protocol_hash':w.PROTOCOL,'native_binary_sha256':w.NATIVE,
            'execution_complete':True,'superiority_claim_issued':False,'failure_counts':{'evaluation':1650,'calibration':2}})
        for name in ('harvest_v3.py','render_v3_figures.py'):
            (self.bundle/'postprocessing').mkdir(exist_ok=True);shutil.copyfile(self.helpers/name,self.bundle/'postprocessing'/name)
        for name in ('index.html','raw-artifact-locators.jsonl'):(self.bundle/name).write_text('FICTIONAL QA ONLY')
        figures=[]
        for stem in w.integrity.FIGURES:
            for extension in ('png','svg'):
                path=self.bundle/'figures'/f'{stem}.{extension}';path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'FICTIONAL IMAGE PLACEHOLDER');figures.append({'path':path.name,'sha256':w.sha(path)})
        self.save(self.bundle/'figures/figure-manifest.json',{'fictional_fixture':False,'renderer_sha256':w.integrity.RENDERER,
            'source_hash':w.SOURCE,'protocol_hash':w.PROTOCOL,'statistics_recomputed':False,'figures':figures,'inputs':[
                {'path':name,'sha256':w.sha(self.bundle/name),'uncompressed_payload_sha256':w.sha(self.bundle/name)}
                for name in ('summary.json','report-synthetic/report.json')]})
        original=self.bundle/'protocol.json'
        self.save(self.bundle/'file-inventory.json',{'original_files':[{'published_path':'protocol.json',
            'published_sha256':w.sha(original),'published_bytes':original.stat().st_size,
            'source_sha256':w.sha(original),'source_bytes':original.stat().st_size,'encoding':'original_bytes'}]})
        self.seal()

    def seal(self):
        files={p.relative_to(self.bundle).as_posix():w.sha(p) for p in self.bundle.rglob('*') if p.is_file() and p.name!='publication.json'}
        self.save(self.bundle/'publication.json',{'files':files,'bundle_content_hash':w.canonical(files),
            'protocol_hash':w.PROTOCOL,'collector_sha256':w.integrity.COLLECTOR,'collected_original_files':1})

    def remote(self,status='complete'):
        return {'status':status,'phase':'FICTIONAL','estimators_launched':False,'helper_sha256':w.VERIFIER_SHA,'binding':{
            'campaign':w.DATA+'/campaign-v3-03','project':w.BASE+'/project-test-candidate-03-complete',
            'collector':w.BASE+'/publication-audit-03/harvest_v3.py','output':w.REMOTE_BUNDLE,
            'source_sha256':w.SOURCE,'protocol_hash':w.PROTOCOL,'native_sha256':w.NATIVE,
            'collector_sha256':w.integrity.COLLECTOR,'renderer_sha256':w.integrity.RENDERER},
            'verification':w.verify_bundle(self.bundle),'upstream':{'source_files_rehashed':89}}

    def test_exact_bundle_design_and_failed_rows_are_publishable(self):
        result=w.verify_bundle(self.bundle)
        self.assertEqual(result['verified_evaluation_rows'],1650);self.assertEqual(result['verified_failure_rows'],1652)
        self.assertEqual(w.verify_runtime(self.repo,self.protocol),89)

    def test_missing_duplicate_fit_and_hidden_failures_rejected_after_rehash(self):
        original=(self.bundle/'metrics.jsonl').read_text();values=w.rows(self.bundle,'metrics.jsonl')
        self.save_lines('metrics.jsonl',values[1:]);self.seal()
        with self.assertRaisesRegex(ValueError,'Compact metrics|1650'):w.verify_bundle(self.bundle)
        self.save_lines('metrics.jsonl',[values[1],*values[1:]]);self.seal()
        with self.assertRaisesRegex(ValueError,'Duplicate|1650 unique'):w.verify_bundle(self.bundle)
        (self.bundle/'metrics.jsonl').write_text(original)
        self.save_lines('failures.jsonl',w.rows(self.bundle,'failures.jsonl')[1:]);self.seal()
        with self.assertRaisesRegex(ValueError,'Failure publication|failure rows'):w.verify_bundle(self.bundle)

    def test_unlisted_fixture_and_changed_source_rejected(self):
        alias=self.root/'bundle-symlink';alias.symlink_to(self.bundle,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):w.verify_bundle(alias)
        (self.bundle/'unexpected').write_text('extra')
        with self.assertRaisesRegex(ValueError,'unlisted'):w.verify_bundle(self.bundle)
        (self.bundle/'unexpected').unlink();(self.bundle/'fixture-image.png').write_text('FICTIONAL');self.seal()
        with self.assertRaisesRegex(ValueError,'Fictional'):w.verify_bundle(self.bundle)
        (self.repo/'src/runtime0.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'runtime changed'):w.verify_runtime(self.repo,self.protocol)

    def test_extra_runtime_file_and_bad_archive_mapping_rejected(self):
        (self.repo/'src/extra.py').write_text('new implementation')
        with self.assertRaisesRegex(ValueError,'paths differ'):w.verify_runtime(self.repo,self.protocol)
        (self.repo/'src/extra.py').unlink()
        self.save(self.repo/w.METADATA/'manifest.json',{'source_hash':w.SOURCE,'files':[{'source_path':'surprise'}]})
        with self.assertRaisesRegex(ValueError,'mapping'):w.verify_runtime(self.repo,self.protocol)

    def test_archived_egg_metadata_substitution_checks_exact_bytes(self):
        expected=dict(self.protocol['source']['files']);digest=expected.pop('src/runtime88.py')
        logical='src/orbit_poc.egg-info/SOURCES.txt';expected[logical]=digest
        original=self.repo/'src/runtime88.py';archive=self.repo/w.METADATA/'SOURCES.txt'
        original.rename(archive);identity=w.canonical(expected)
        self.save(self.repo/w.METADATA/'manifest.json',{'source_hash':identity,'files':[
            {'source_path':logical,'file':'SOURCES.txt','sha256':digest}]})
        protocol={'source':{'files':expected}}
        with patch.object(w,'SOURCE',identity):
            self.assertEqual(w.verify_runtime(self.repo,protocol),89)
            archive.write_text('changed metadata')
            with self.assertRaisesRegex(ValueError,'runtime changed'):w.verify_runtime(self.repo,protocol)

    def test_atomic_install_and_same_bundle_reuse_conflict_preserved(self):
        staging=self.repo/'runs/.transfer';shutil.copytree(self.bundle,staging)
        expected=w.sha(staging/'publication.json');w.copy_to_repo(staging,self.repo,expected)
        self.assertFalse(staging.exists());self.assertEqual(w.verify_bundle(self.repo/'runs/v3')['publication_sha256'],expected)
        self.assertEqual(w.copy_to_repo(staging,self.repo,expected)['publication_sha256'],expected)
        with self.assertRaisesRegex(ValueError,'differs'):w.copy_to_repo(staging,self.repo,'wrong')
        self.assertEqual(w.sha(self.repo/'runs/v3/publication.json'),expected)

    def test_wait_only_remote_status_then_transfer(self):
        waiting=self.remote('waiting');complete=self.remote();calls=[];sleeps=[]
        def run(argv,**kwargs):
            calls.append(argv);self.assertEqual(argv[0],'rsync')
            shutil.copytree(self.bundle,Path(argv[-1]),dirs_exist_ok=True);return ''
        with patch.object(w,'check_local_repo'),patch.object(w,'protected_tree',return_value={'v2':'old'}), \
             patch.object(w,'remote_status',side_effect=[waiting,complete,complete]),patch.object(w,'command',side_effect=run):
            result=w.wait_for_bundle(self.repo,self.journal,sleeper=sleeps.append)
        self.assertEqual(result['status'],'bundle_ready');self.assertEqual(sleeps,[60]);self.assertEqual(len(calls),1)
        self.assertEqual((self.repo/'runs/v2/original.txt').read_text(),'immutable v2')

    def test_remote_failure_and_bounded_transient_ssh_errors_never_transfer(self):
        with patch.object(w,'check_local_repo'),patch.object(w,'protected_tree',return_value={}), \
             patch.object(w,'remote_status',return_value=self.remote('blocked')),patch.object(w,'command') as run:
            with self.assertRaisesRegex(ValueError,'terminated'):w.wait_for_bundle(self.repo,self.journal)
            run.assert_not_called()
        sleeps=[]
        with patch.object(w,'check_local_repo'),patch.object(w,'protected_tree',return_value={}), \
             patch.object(w,'remote_status',side_effect=RuntimeError('ssh offline')) as remote:
            with self.assertRaisesRegex(RuntimeError,'Five consecutive'):w.wait_for_bundle(self.repo,self.journal,sleeper=sleeps.append)
        self.assertEqual(remote.call_count,5);self.assertEqual(sleeps,[60]*4)

    def test_valid_status_resets_consecutive_transport_failure_budget(self):
        complete=self.remote();waiting=self.remote('waiting');sequence=[RuntimeError('offline')]*4+[waiting]+[RuntimeError('offline')]*4+[complete,complete]
        def run(argv,**kwargs):shutil.copytree(self.bundle,Path(argv[-1]),dirs_exist_ok=True);return ''
        sleeps=[]
        with patch.object(w,'check_local_repo'),patch.object(w,'protected_tree',return_value={}), \
             patch.object(w,'remote_status',side_effect=sequence),patch.object(w,'command',side_effect=run):
            result=w.wait_for_bundle(self.repo,self.journal,sleeper=sleeps.append)
        self.assertEqual(result['status'],'bundle_ready');self.assertEqual(sleeps,[60]*9)

    def test_lock_excludes_duplicate_worker(self):
        with w.lock(self.control):
            with self.assertRaisesRegex(RuntimeError,'Another'):
                with w.lock(self.control):pass

    def test_readme_is_concrete_idempotent_and_preserves_other_sections(self):
        old=(self.repo/'README.md').read_text();new=w.readme_result(old,{'publication_sha256':'abc'})
        self.assertTrue(new.startswith('Preamble\n'));self.assertTrue(new.endswith('Original v2 description.\n'))
        self.assertIn('1,650',new);self.assertIn('runs/v3/index.html',new);self.assertIn('does not',new)
        self.assertEqual(w.readme_result(new,{'publication_sha256':'abc'}),new)
        with self.assertRaisesRegex(ValueError,'structure'):w.readme_result('unexpected README',{})
        with self.assertRaisesRegex(ValueError,'manual edits'):
            w.readme_result(old.replace('Old pending status.','New user analysis.'),{'publication_sha256':'abc'})

    def fake_publish(self,advance=False,dirty=False,remote_corrupt=False,pr_update_fail=False):
        shutil.copytree(self.bundle,self.repo/'runs/v3')
        verified=w.verify_bundle(self.bundle)
        self.journal.record('bundle_ready','fictional',verification=verified)
        journal=w.Journal(self.control,self.repo);state={'head':'base','calls':[],'pr_body':'Old pending body','pr_edits':0}
        def run(argv,**kwargs):
            self.assertIn('clone',argv);clone=Path(argv[-1]);shutil.copytree(self.repo,clone,ignore=shutil.ignore_patterns('v3'))
            return ''
        def git(project,*args,**kwargs):
            state['calls'].append(args)
            if args[:2]==('remote','get-url'):return w.REPOSITORY
            if args==('branch','--show-current'):return w.BRANCH
            if args==('status','--porcelain'):return ' M README.md' if dirty else ''
            if args[:2]==('rev-parse','HEAD'):return state['head']
            if args[0]=='rev-parse':return state['head']
            if args[:2]==('diff','--cached') and '--name-only' in args:return 'README.md\0runs/v3/publication.json\0'
            if args[0]=='config' and len(args)==2:return 'Fixture'
            if args[0]=='commit':
                self.assertNotIn('[codex]',args[-1]);state['head']='new-commit';return ''
            if args[0]=='ls-remote':return ('advanced' if advance else 'base')+'\trefs/heads/'+w.BRANCH
            if args[0]=='worktree':
                target=Path(args[3]);shutil.copytree(project,target)
                if remote_corrupt:(target/'runs/v3/metrics.jsonl').write_text('corrupt')
                return ''
            return ''
        def pr_request(body=None):
            if body is not None:
                state['pr_edits']+=1
                if pr_update_fail:raise RuntimeError('Fictional PATCH failure after verified push')
                state['pr_body']=body
            return {'number':1,'state':'open','draft':True,'body':state['pr_body'],
                'head':{'ref':w.BRANCH,'sha':state['head'],'repo':{'full_name':'FlorianPfaff/orbit-smoothing-poc'}},
                'base':{'ref':'main','repo':{'full_name':'FlorianPfaff/orbit-smoothing-poc'}}}
        fakegh=self.root/'gh';fakegh.write_text('unused')
        with patch.object(w,'GH',str(fakegh)),patch.object(w,'check_local_repo'), \
             patch.object(w,'protected_tree',return_value={'v2':'unchanged'}),patch.object(w,'command',side_effect=run), \
             patch.object(w,'git',side_effect=git),patch.object(w,'pr_request',side_effect=pr_request):
            return w.publish(self.repo,journal),state

    def test_mock_publish_pushes_once_then_verifies_fetched_bytes(self):
        result,state=self.fake_publish()
        self.assertEqual(result['status'],'published');self.assertEqual(result['commit'],'new-commit')
        pushes=[args for args in state['calls'] if args[0]=='push']
        self.assertEqual(pushes,[('push','origin',w.BRANCH)])
        self.assertTrue(any(args[0]=='fetch' for args in state['calls']))
        self.assertTrue(any(args[0]=='worktree' for args in state['calls']))
        self.assertEqual(state['pr_edits'],1)
        self.assertIn('1,650 planned evaluation attempts',state['pr_body'])
        self.assertEqual(result['pr_body_sha256'],hashlib.sha256(state['pr_body'].encode()).hexdigest())

    def test_advanced_branch_and_dirty_clone_refuse_publication(self):
        with self.assertRaisesRegex(ValueError,'advanced'):self.fake_publish(advance=True)

    def test_dirty_clone_refuses_publication(self):
        with self.assertRaisesRegex(ValueError,'not clean'):self.fake_publish(dirty=True)

    def test_fetched_corruption_cannot_claim_published(self):
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.fake_publish(remote_corrupt=True)
        self.assertNotEqual(w.read(self.control/'status.json')['status'],'published')

    def test_pr_update_failure_retains_verified_published_repository_status(self):
        result,state=self.fake_publish(pr_update_fail=True)
        self.assertEqual(result['status'],'published_repo_pr_update_failed')
        self.assertEqual(result['commit'],'new-commit');self.assertTrue(result['repository_bytes_verified'])
        self.assertTrue(result['external_publication_performed']);self.assertFalse(result['automatic_retry'])
        self.assertEqual(state['pr_edits'],1)

    def test_pr_identity_and_structured_patch_only(self):
        response={'number':1,'state':'open','head':{'ref':w.BRANCH,'sha':'commit','repo':{'full_name':'FlorianPfaff/orbit-smoothing-poc'}},
            'base':{'ref':'main','repo':{'full_name':'FlorianPfaff/orbit-smoothing-poc'}}}
        w.check_pr(response,'commit');response['base']['ref']='unexpected'
        with self.assertRaisesRegex(ValueError,'identity'):w.check_pr(response,'commit')
        with patch.object(w,'command',return_value=json.dumps(response)) as command:
            w.pr_request('Literal $() `body`\nsecond line')
        argv=command.call_args.args[0]
        self.assertEqual(argv[-4:],['--method','PATCH','--input','-'])
        self.assertEqual(json.loads(command.call_args.kwargs['input']),{'body':'Literal $() `body`\nsecond line'})


if __name__=='__main__':unittest.main()
