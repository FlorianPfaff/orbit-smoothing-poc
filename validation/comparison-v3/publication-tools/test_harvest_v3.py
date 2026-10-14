"""Scratch collector tests; no campaign is harvested by these checks."""
import gzip
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('harvest',Path(__file__).with_name('harvest_v3.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


def completed_fixture(root):
    """Fictional manifest contracts only; all 1,650 fits are deliberately excluded."""
    native={'path':'fictional-native','sha256':h.NATIVE_74863}
    protocol={'source':{'sha256':h.SOURCE_03},'native_binary':native,
        'config':{'primary_cell':['leo500','disturbed','blackout']}}
    protocol['protocol_hash']=h.canonical(protocol);identity=protocol['protocol_hash']
    gates={'protocol_hash':identity,'gates':{name:{'passed':True} for name in h.GATES}}
    gates['evidence_hash']=h.canonical(gates)
    docs={'protocol.json':protocol,'acceptance-gates.json':gates,
        'campaign-driver.json':{'status':'complete','stages':[{'stage':s,'status':'complete'} for s in ('synthetic','flight')]}}
    for stage in ('synthetic','flight'):
        docs[f'driver-{stage}.json']={'stage':stage,'status':'complete','protocol_hash':identity}
        count=48 if stage=='synthetic' else 12
        docs[f'calibration-input-preparation-{stage}.json']={'status':'prepared','protocol_hash':identity,
            'prepared_cases':count,'prepare_results':[{'case':i} for i in range(count)]}
        selection={'protocol_hash':identity,'selections':{'fictional':{}},'evidence':[],
            'calibration_adequate':False,'calibration_disclosures':['Fictional improving boundary'],
            'boundary_diagnostics':{}}
        selection_hash=h.canonical(selection)
        docs[f'calibration-{stage}.json']={**selection,'selection_hash':selection_hash,'complete':True,
            'stage':stage,'source_hash':h.SOURCE_03,'runs':[]}
        frozen={'stage':stage,'status':'frozen','protocol_hash':identity,'selection_hash':selection_hash,
            'source_hash':h.SOURCE_03,'native_binary':native,'prepare_results':[],'campaign_case_counts':{},'inputs':[]}
        for campaign,(campaign_stage,kind,fits) in h.CAMPAIGNS.items():
            if campaign_stage!=stage:continue
            methods=['groops_pulses_ar'] if kind=='flight_ar_reference' else list(h.PRIMARY_METHODS)
            cases=[{'fictional_case':f'{campaign}-{i}'} for i in range(fits//len(methods))]
            frozen['prepare_results'] += [{'campaign':kind,'case':case} for case in cases]
            frozen['campaign_case_counts'][kind]=len(cases)
            run={'complete':True,'status':'complete','stage':stage,'campaign':kind,'expected_fits':fits,
                'protocol_hash':identity,'selection_hash':selection_hash,'source_hash':h.SOURCE_03,
                'acceptance_evidence_hash':gates['evidence_hash'],'methods':methods,'planned_cases':cases,
                'runs':[{'case':case,'method':method,'status':'excluded'} for case in cases for method in methods]}
            docs[f'run-{campaign}.json']=run
            docs[f'report-{campaign}/report.json']={'orchestration_complete':True,'planned_design_complete':True,
                'observed_fits':fits,'expected_fits':fits,'planned_fit_rows':fits,'missing_planned_fits':0,
                'stage':stage,'status':'complete','source_hash':h.SOURCE_03,'protocol_hash':identity,
                'selection_hash':selection_hash,'metrics_error':None,'all_fits_valid':False}
        frozen['input_freeze_hash']=h.canonical(frozen)
        docs[f'evaluation-input-freeze-{stage}.json']=frozen
    for name in h.original_files():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        if name.endswith('.json'):h.write(path,docs[name])
        else:path.write_text('<p>FICTIONAL QA REPORT — NO RESULTS</p>')
    return docs


class HarvestTests(unittest.TestCase):
    def test_complete_1650_design_with_failures_and_limited_calibration_is_publishable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);completed_fixture(root)
            status=h.readiness(root,h.SOURCE_03)
            self.assertEqual(status['errors'],[])
            self.assertTrue(status['ready'])
            self.assertEqual(status['expected_evaluation_fits'],1650)
            self.assertEqual(len(status['original_file_sha256']),len(h.original_files()))
            self.assertFalse(h.readiness(root,h.SOURCE_F2)['ready'])

    def test_empty_and_non_object_required_manifests_are_not_ready(self):
        for value in ({},[],None):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);completed_fixture(root)
                h.write(root/'report-stress/report.json',value)
                status=h.readiness(root,h.SOURCE_03)
                self.assertFalse(status['ready'])
                self.assertTrue(any('nonempty object' in error for error in status['errors']))

    def test_missing_duplicate_unfrozen_and_wrong_source_rows_are_rejected(self):
        mutations={
            'missing':lambda d:d['run-synthetic.json']['runs'].pop(),
            'duplicate':lambda d:d['run-synthetic.json']['runs'].__setitem__(0,copy.deepcopy(d['run-synthetic.json']['runs'][1])),
            'unknown_method':lambda d:d['run-stress.json']['runs'][0].update(method='external_unknown'),
            'changed_case':lambda d:d['run-flight.json']['runs'][0].update(case={'fictional_case':'unfrozen'}),
            'wrong_source':lambda d:d['report-flight_ar_reference/report.json'].update(source_hash=h.SOURCE_F2),
            'missing_report_count':lambda d:d['report-stress/report.json'].update(planned_fit_rows=19),
            'running_stage':lambda d:d['driver-flight.json'].update(status='running')}
        for label,mutate in mutations.items():
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);docs=completed_fixture(root);mutate(docs)
                for name,value in docs.items():h.write(root/name,value)
                self.assertFalse(h.readiness(root,h.SOURCE_03)['ready'])

    def test_changed_bytes_after_readiness_block_atomic_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';root.mkdir();completed_fixture(root)
            ready=h.readiness(root,h.SOURCE_03)
            with (root/'protocol.json').open('a') as stream:stream.write(' ')
            output=Path(temporary)/'published/v3'
            with self.assertRaisesRegex(RuntimeError,'Changed source artifact'):
                h.collect(root,output,ready)
            self.assertFalse(output.exists())
            retained=list(output.parent.glob('.v3-harvest-*/incomplete-harvest.json'))
            self.assertEqual(len(retained),1)

    @unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'Rendering environment required for fictional integration test')
    def test_fictional_atomic_bundle_preserves_all_1650_excluded_fits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';root.mkdir()
            native=root/'fictional-native';native.write_bytes(b'FICTIONAL NONEXECUTABLE QA')
            with patch.object(h,'NATIVE_74863',h.sha(native)):
                docs=completed_fixture(root)
                def index(name,status):
                    path=root/(name+'.json')
                    result={'status':status,'request_hash':name,'reason':'Explicitly fictional exclusion'}
                    h.write(path,result)
                    return {'result_path':str(path),'result_sha256':h.sha(path),
                        'status':status,'request_hash':name}
                prepared=index('fictional-prepared','prepared');excluded=index('fictional-excluded','excluded')
                for stage in ('synthetic','flight'):
                    for row in docs[f'calibration-input-preparation-{stage}.json']['prepare_results']:
                        row['result_record']=prepared
                renderer=h.load_renderer();_,figure_report=renderer.fixture()
                for row in figure_report['paired_metrics']:
                    row.update(valid_seed_pairs=0,failed_or_missing_seed_pairs=50,
                        mean_difference_a_minus_b=None,bootstrap_95_interval=None)
                for row in figure_report['fixed_epoch_coverage']:
                    row.update(successes=0,trials=0,estimate=None,interval=None,failed_or_unavailable_seeds=50)
                for name in h.CAMPAIGNS:
                    for row in docs[f'run-{name}.json']['runs']:row['fit_record']=excluded
                    report=docs[f'report-{name}/report.json']
                    report.update(primary_cell=['leo500','disturbed','blackout'],paired_metrics=[],fixed_epoch_coverage=[],
                        limitations=['FICTIONAL QA ONLY'],interpretation='Not experimental evidence')
                    if name=='synthetic':
                        report.update({key:figure_report[key] for key in ('paired_metrics','fixed_epoch_coverage')})
                for name,value in docs.items():h.write(root/name,value)
                ready=h.readiness(root,h.SOURCE_03);self.assertTrue(ready['ready'],ready['errors'])
                output=Path(temporary)/'output/v3';h.collect(root,output,ready)
                metrics=[json.loads(line) for line in (output/'metrics.jsonl').read_text().splitlines()]
                self.assertEqual(len(metrics),1650)
                self.assertEqual({row['status'] for row in metrics},{'excluded'})
                self.assertEqual(len((output/'failures.jsonl').read_text().splitlines()),1650)
                summary=h.read(output/'summary.json')
                self.assertEqual(summary['failure_counts'],{'evaluation':1650})
                self.assertFalse(summary['superiority_claim_issued'])
                self.assertFalse(summary['calibration']['synthetic']['calibration_adequate'])
                self.assertEqual(summary['campaign_diagnostics']['stress']['limitations'],['FICTIONAL QA ONLY'])
                publication=h.read(output/'publication.json')
                for name,expected in publication['files'].items():self.assertEqual(h.sha(output/name),expected)
                self.assertEqual((output/'protocol.json').read_bytes(),(root/'protocol.json').read_bytes())
                for name in h.DERIVED:self.assertTrue((output/name).is_file(),name)

    def test_missing_campaign_is_not_ready_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            status=h.readiness(root,h.SOURCE_F2)
            self.assertFalse(status['ready'])
            self.assertIn('Missing campaign-driver.json',status['errors'])
            self.assertEqual(list(root.iterdir()),[])
            with self.assertRaisesRegex(ValueError,'not ready'):
                h.collect(root,root/'uncreated'/'v3',status)
            self.assertFalse((root/'uncreated').exists())

    def test_exact_bytes_compression_deduplication_and_mutation_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir();output=root/'output';output.mkdir()
            path=source/'manifest.json'
            original=b'{"remote_path":"/unchanged/native/orbit.dat","sha256":"do-not-rewrite"}\n'
            path.write_bytes(original)
            collector=h.Collector(source,output)
            destination=collector.copy(path,'manifest.json',h.sha(path))
            self.assertEqual((output/destination).read_bytes(),original)
            large=source/'large.json';large.write_bytes(json.dumps({'payload':'x'*(2*1024*1024)}).encode())
            alias=source/'alias.json';alias.write_bytes(large.read_bytes())
            expected=h.sha(large)
            first=collector.copy(large,f'content/{expected}.json',expected)
            second=collector.copy(alias,f'content/{expected}.json',expected)
            self.assertEqual(first,second)
            self.assertEqual(gzip.decompress((output/first).read_bytes()),large.read_bytes())
            self.assertEqual(collector.inventory[-1]['source_sha256'],expected)
            path.write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError,'Changed source'):
                collector.copy(path,'changed.json',collector.inventory[0]['source_sha256'])

    def test_landing_links_and_flight_interpretations_remain_distinct(self):
        summary={'campaign_source_directory':'/raw/campaign','primary_paired_comparisons':[],
            'primary_coverage':[],'calibration':{},'stress_paired_comparisons':[{
                'cell_id':'leo500/disturbed/blackout','metric':'gap.position_rmse_m',
                'method_a':'density','method_b':'pulses','valid_seed_pairs':3,'planned_seed_pairs':5,
                'failed_or_missing_seed_pairs':2,'mean_difference_a_minus_b':None,'bootstrap_95_interval':None}],
            'campaign_diagnostics':{'stress':{'limitations':['Fictional stress-specific limitation']}},
            'protocol_hash':'protocol','source_hash':'source','native_binary_sha256':'native',
            'failure_counts':{},'superiority_claim_issued':False}
        paths={f'/raw/campaign/report-{name}/index.html':f'report-{name}/index.html' for name in h.CAMPAIGNS}
        html=h.landing(summary,[],paths)
        self.assertIn('href="../../results.html"',html)
        for name in h.CAMPAIGNS:
            self.assertIn(f'href="report-{name}/index.html"',html)
        self.assertIn('Independent flight evidence: SLR',html)
        self.assertIn('GPS-derived GNV1B agreement',html)
        self.assertIn('neither Cartesian NEES nor flight truth coverage',html)
        self.assertNotIn('file://',html)
        self.assertIn('<td>3/5</td><td>2</td><td>unavailable</td><td>unavailable</td>',html)
        self.assertIn('Fictional stress-specific limitation',html)
        for stem in h.FIGURE_STEMS:
            self.assertIn(f'src="figures/{stem}.png"',html)
            self.assertIn(f'href="figures/{stem}.svg"',html)

    def test_figures_and_postprocessing_sources_stay_inside_atomic_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage=Path(temporary)/'stage';stage.mkdir()
            collector=h.Collector(Path(temporary),stage)
            module=h.load_renderer()
            with patch.object(module,'render_bundle',return_value={'figures':[]}) as renderer:
                with patch.object(h,'load_renderer',return_value=module):
                    h.render_publication_figures(stage,collector)
                    renderer.assert_called_once_with(stage)
                    for path in h.POSTPROCESSING:self.assertTrue((stage/path).is_file())
                    (stage/'publication.json').write_text('{}')
                    with self.assertRaisesRegex(ValueError,'after publication'):
                        h.render_publication_figures(stage,collector)
            self.assertEqual(len(collector.inventory),2)


if __name__=='__main__':unittest.main()
