from pathlib import Path
import copy,json,importlib.util,pytest
P=Path(__file__).with_name('test_allowlist.py');s=importlib.util.spec_from_file_location('old_allowlist_fixtures',P)
f=importlib.util.module_from_spec(s);s.loader.exec_module(f);m=f.m

def setup(t):
 p,truth=f.fixture(t);run=Path(p['run_root']);generation='leo500-quiet-610000-continuous72h'
 original=f.file(run/'preparation/generation'/generation/'observations/GPS1B_2024-05-10_C_synthetic.txt','noisy observation values')
 retained=f.file(t/'prepared/preprocessing/GPS1B_2024-05-10_C_04.retained.txt','noisy observation values')
 physical={'orbit':'leo500','atmosphere':'quiet','seed':610000,'duration_hours':72,'coverage':'normal','epoch':'2024-05-10T00:00:00','mask':{'intervals_seconds':[],'duration_seconds':259200}}
 observation={**retained,'role':'gnss_observations','source_sha256':original['sha256'],'mask_hash':m.canonical(physical['mask']),'records':12}
 manifest=json.loads(Path(p['manifest']['path']).read_text());request=manifest['cases'][0]['fit_request'];prep=request['estimation_inputs'][1]
 native=json.loads(Path(prep['path']).read_text());native['native_artifacts'].append(retained);newprep=f.save(Path(prep['path']),native)
 request['estimation_inputs'][1].update(newprep);request['estimation_inputs'].append(observation);request.update(case=physical,mask_hash=observation['mask_hash'])
 rp=f.save(Path(manifest['cases'][0]['request_artifact']['path']),request)
 for c in manifest['cases']:c.update(stage='synthetic',case=physical,generation_id=generation,fit_request=request,request_artifact=rp)
 manifest.pop('manifest_hash');manifest['manifest_hash']=m.canonical(manifest);f.replace(p,'manifest',manifest)
 status=json.loads(Path(p['preparation_status']['path']).read_text());status['manifest_hash']=manifest['manifest_hash'];f.replace(p,'preparation_status',status)
 support=json.loads(Path(p['support_inventory']['path']).read_text());support['manifest_hash']=manifest['manifest_hash'];f.replace(p,'support_inventory',support)
 rows,_=m.derive_estimation(manifest)
 return p,original,retained,manifest,rows,truth

def test_full_build_allows_measurement_copy_but_keeps_original_path_denied(tmp_path):
 p,original,retained,_,_,truth=setup(tmp_path);out=m.build(p)
 assert retained['path'] in {x['path'] for x in out['files']}
 denied=next(x for x in out['denied_files'] if x['path']==original['path'])
 assert denied['content_sensitive'] is False and 'source hash' in denied['shared_input_exception']
 assert original['path'] not in {x['path'] for x in out['files']}
 assert next(x for x in out['denied_files'] if x['path']==truth['path'])['content_sensitive'] is True

@pytest.mark.parametrize('kind',['role','native_dependency','support_only','source_hash','content_hash','bytes','records_zero','records_bool','mask','request_mask','case_mismatch','blackout','duration','generation','flight','path','truth_name','clock_name','ambiguity_name'])
def test_exception_requires_full_measurement_lineage(tmp_path,kind):
 p,original,retained,manifest,rows,_=setup(tmp_path);manifest=copy.deepcopy(manifest);manifest['cases']=manifest['cases'][:1]
 c=manifest['cases'][0];r=c['fit_request'];ref=r['estimation_inputs'][-1];path=original['path']
 if kind=='role':ref['role']='force_auxiliary'
 elif kind=='native_dependency':rows[retained['path']]['reasons'].discard('native_preparation_dependency')
 elif kind=='support_only':rows[retained['path']]['reasons']={'verification_metadata_or_required_native_dependency'}
 elif kind=='source_hash':ref['source_sha256']='0'*64
 elif kind=='content_hash':ref['sha256']='0'*64
 elif kind=='bytes':ref['bytes']+=1
 elif kind=='records_zero':ref['records']=0
 elif kind=='records_bool':ref['records']=True
 elif kind=='mask':ref['mask_hash']='0'*64
 elif kind=='request_mask':r['mask_hash']='0'*64
 elif kind=='case_mismatch':r['case']=dict(c['case'],seed=99)
 elif kind=='blackout':c['case']['coverage']='blackout'
 elif kind=='duration':c['case']['duration_hours']=24
 elif kind=='generation':c['generation_id']='wrong'
 elif kind=='flight':c['stage']='flight'
 elif kind=='path':path=str(Path(path).parent.parent/'other'/Path(path).name)
 elif kind=='truth_name':path=str(Path(path).with_name('truth.npz'))
 elif kind=='clock_name':path=str(Path(path).with_name('receiver_clock.txt'))
 elif kind=='ambiguity_name':path=str(Path(path).with_name('ambiguity_truth.txt'))
 assert not m.shared_observation(path,original,rows,manifest,p['run_root'])

def test_observation_exception_does_not_allow_other_truth_copies(tmp_path):
 p,_,_,_,_,truth=setup(tmp_path);alias=f.file(tmp_path/'truth-copy',Path(truth['path']).read_text())
 support=json.loads(Path(p['support_inventory']['path']).read_text());support['files'].append(alias);f.replace(p,'support_inventory',support)
 with pytest.raises(ValueError,match='denied'):m.build(p)
