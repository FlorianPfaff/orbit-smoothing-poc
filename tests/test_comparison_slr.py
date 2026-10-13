"""SLR metadata and optics gates independent of fitted orbit residuals."""
import math
from pathlib import Path
import numpy as np
import pytest
from orbit_poc.comparison.slr import (SlrPrerequisiteError,inspect_crd,
    prism_correction,station_bias_policy,REFLECTOR_OFFSET_SRF_M)


def dhf_record(station,target,code,start='20:001:00000',end='00:000:00000',value=None,sigma=None):
    line=list(' '*90)
    for offset,text in ((1,station),(6,target),(9,'501'),(13,'A'),(16,start),(29,end),(42,code)):
        line[offset:offset+len(text)]=text
    if value is not None:line[44:56]=f'{value:12.3f}'
    if sigma is not None:line[56:64]=f'{sigma:8.3f}'
    line[75:77]='mm'
    return ''.join(line)


def test_bounded_bias_policy_and_formal_eligibility(tmp_path):
    p=tmp_path/'dhf.snx'
    p.write_text('=SNX\n+MODEL/RANGE_BIAS\n'+ '\n'.join([
        dhf_record('7105','51','R',value=-5.1,sigma=.4),dhf_record('7105','52','R',value=-4.3,sigma=.4),
        dhf_record('7110','51','R',end='21:001:00000',value=123,sigma=.1)])+
        '\n+SOLUTION/DATA_HANDLING\n'+dhf_record('7110','--','E')+'\n+MODEL/TIME_BIAS\n'+
        dhf_record('7105','--','T',start='15:001:00000',end='16:001:00000',value=14.6)+'\n')
    result=station_bias_policy(p,'2024-04-24',['7105','7110'])
    assert result['7105']['formal_prediction_eligible']
    assert result['7105']['range_bias_m']==pytest.approx(-.0047)
    assert result['7105']['range_bias_sigma_m']==pytest.approx(.0004)
    assert result['7110']['range_bias_m']==0
    assert not result['7110']['formal_prediction_eligible']
    assert result['7110']['descriptive_only']


def test_active_unsupported_timing_correction_blocks_and_html_rejected(tmp_path):
    p=tmp_path/'dhf.snx'
    p.write_text('=SNX\n+MODEL/RANGE_BIAS\n+MODEL/TIME_BIAS\n'+dhf_record('7105','--','T',value=14.6)+'\n')
    with pytest.raises(SlrPrerequisiteError,match='active additional'):station_bias_policy(p,'2024-04-24',['7105'])
    p.write_text('<html>File not found</html>')
    with pytest.raises(SlrPrerequisiteError,match='invalid ILRS'):station_bias_policy(p,'2024-04-24',['7105'])


def test_prism_sign_wavelength_and_incidence():
    normal=[.5,.5,math.sqrt(.5)]
    correction,valid=prism_correction(normal,532e-9)
    assert valid and correction==pytest.approx(.0474-.028*1.4853)
    assert REFLECTOR_OFFSET_SRF_M==(-.6,-.3275,.2188)
    assert not prism_correction([0,0,-1],532e-9)[1]
    assert prism_correction(normal,1064e-9)[0]>correction
    with pytest.raises(SlrPrerequisiteError):prism_correction(normal,700e-9)


def crd(path,trop='0',delay='1',met=True):
    h4=['h4','1','2024','4','24','0','0','0','2024','4','24','0','1','0','0',trop,'0','0',delay,'0','2','0']
    rows=['h1 CRD 2 2024 4 24 1','h2 station 7105 0 0 0','h3 gracefo1 1804701 0 0 0',' '.join(h4),'c0 0 532 system','11 10 .01 system 2']
    if met:rows.append('20 10 1000 290 50')
    path.write_text('\n'.join(rows+['h8','h9'])+'\n');return path


def test_crd_applied_correction_flags_and_meteorology(tmp_path):
    p=crd(tmp_path/'np2')
    result=inspect_crd(p,tmp_path/'selected.np2')
    assert result['retained_normal_points']==1 and result['stations']==['7105']
    for kwargs in ({'trop':'1'},{'delay':'0'},{'met':False}):
        with pytest.raises(SlrPrerequisiteError):inspect_crd(crd(p,**kwargs))


def test_slr_grouped_scores_retain_correlation_and_station_selection():
    from orbit_poc.comparison.slr import summarize_slr
    data=np.zeros((4,15))
    data[:,0]=[60424+17/86400,60424+18/86400,60424+48/86400,60424+78/86400]
    data[:,1]=[7105,7105,7110,7105]
    data[:,2]=[1,2,3,2]
    data[:,3]=[.1,.2,2.,9.]
    data[:,4]=.01
    data[:,5]=np.deg2rad([25,45,70,45])
    data[:,6]=np.deg2rad([10,100,190,280])
    data[:,9]=[1,1,1,0]
    covariance=np.diag([.04,.04,.09,.04]);covariance[0,1]=covariance[1,0]=.02
    result=summarize_slr(data,predictive_covariance=covariance,formal_prediction_stations=['7105'])
    formal=covariance[:2,:2];residual=data[:2,3]
    expected=.5*(residual@np.linalg.solve(formal,residual)+np.linalg.slogdet(formal)[1]+2*np.log(2*np.pi))
    assert result['predictive']['nll']==pytest.approx(expected)
    assert result['normal_points']==3 and result['native_points']==4
    assert result['per_station']['7110']['count']==1
    assert result['per_station']['7110']['predictive']['status']=='unavailable'
    assert set(result['per_date'])=={'2024-04-23','2024-04-24'}
    assert result['per_pass']=={} and result['passes'] is None
    assert result['pass_mapping']['status']=='unavailable'
    assert result['per_native_arc']['2024-04-24/station-7105/arc-2']['count']==1
    assert result['per_native_arc']['2024-04-24/station-7105/arc-2']['reflector_cutoff_excluded']==1
    assert result['by_geometry']['azimuth']['270_to_360_deg']['status']=='unavailable'
    # Off-diagonal terms change the joint score; no sum of pointwise scores.
    independent=.5*(np.sum(residual**2/.04)+2*np.log(.04)+2*np.log(2*np.pi))
    assert abs(result['predictive']['nll']-independent)>.01


def test_slr_empty_or_reflector_excluded_is_unavailable(tmp_path):
    from orbit_poc.comparison.slr import summarize_slr
    empty=tmp_path/'empty.txt';empty.write_text('# no retained observations\n')
    assert summarize_slr(empty)['status']=='unavailable'
    data=np.zeros((1,15));data[0,0]=60424;data[0,1]=7105;data[0,4]=.01
    result=summarize_slr(data,predictive_covariance=np.array([[.1]]),formal_prediction_stations=['7105'])
    assert result['status']=='unavailable' and result['range_rms_m'] is None
    assert result['predictive']['status']=='unavailable'
    assert result['reflector_cutoff_excluded']==1


def test_slr_grouped_scores_never_repair_invalid_covariance():
    from orbit_poc.comparison.slr import summarize_slr
    data=np.zeros((2,14));data[:,0]=60424;data[:,1]=7105;data[:,4]=.01;data[:,9]=1
    result=summarize_slr(data,predictive_covariance=np.array([[1.,2.],[2.,1.]]),formal_prediction_stations=['7105'])
    assert not result['predictive']['valid']
    assert result['predictive']['status']=='invalid_covariance'


def test_crd_session_bounds_hashes_and_epoch_event_conversion(tmp_path):
    import hashlib
    p=crd(tmp_path/'np2')
    text=p.read_text().replace('11 10 .01 system 2',
        '11 10.01 .01 system 0\n11 20.005 .01 system 1\n11 30 .01 system 2')
    p.write_text(text)
    qc=inspect_crd(p)
    session=qc['sessions'][0]
    assert session['source_sha256']==qc['source_sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
    assert list(map(float,session['transmit_seconds_from_origin']))==[10,20,30]
    assert session['header_start_utc']=='2024-04-24T00:00:00'
    assert session['header_end_utc']=='2024-04-24T00:01:00'
    assert session['transmit_start_utc']=='2024-04-24T00:00:10'
    assert session['transmit_end_utc']=='2024-04-24T00:00:30'
    assert len(session['header_sha256'])==64


def session_fixture(tmp_path):
    p=crd(tmp_path/'np2')
    first=p.read_text().replace('11 10 .01 system 2','11 10 .01 system 2\n11 20 .01 system 2')
    second=first.replace('2024 4 24 0 0 0 2024 4 24 0 1 0',
                         '2024 4 24 0 2 0 2024 4 24 0 3 0')
    second=second.replace('11 10 .01','11 130 .01').replace('11 20 .01','11 140 .01')
    p.write_text(first.replace('h9\n','')+second)
    qc=inspect_crd(p)
    data=np.zeros((4,14));data[:,0]=60424+(np.array([10,20,130,140])+18)/86400
    data[:,1]=7105;data[:,2]=0  # Native conversion merged both sessions.
    data[:,3]=[.01,-.02,.015,.01];data[:,4]=.005;data[:,9]=1
    covariance=np.eye(4)*.0001+np.ones((4,4))*.00005
    return qc,data,covariance


def test_true_crd_pass_groups_preserve_whole_station_date_correlated_scores(tmp_path):
    from orbit_poc.comparison.slr import summarize_slr
    from orbit_poc.comparison.metrics import gaussian_score
    qc,data,covariance=session_fixture(tmp_path)
    opts=dict(predictive_covariance=covariance,formal_prediction_stations=['7105'])
    before=summarize_slr(data,**opts)
    after=summarize_slr(data,pass_sessions=qc['sessions'],pass_source_sha256=qc['source_sha256'],**opts)
    for key in ('predictive','per_station','per_date','by_geometry'):
        assert before[key]==after[key]
    assert after['passes']==2 and len(after['per_native_arc'])==1
    assert after['pass_mapping']['predicted_rows_matched']==4
    assert after['pass_mapping']['source_sha256']==qc['source_sha256']
    assert len(after['pass_mapping']['session_bounds_sha256'])==64
    for index,indices in enumerate(([0,1],[2,3])):
        group=after['per_pass'][f'2024-04-24/station-7105/crd-session-{index}']
        expected=gaussian_score(data[indices,3],covariance[np.ix_(indices,indices)])
        assert group['predictive']['nll']==pytest.approx(expected['nll'])
        assert group['native_arc_ids']==[0] and group['count']==2
        assert group['source_sha256']==qc['source_sha256']


def test_crd_pass_mapping_rejects_missing_ambiguous_or_wrong_source_epochs(tmp_path):
    from copy import deepcopy
    from orbit_poc.comparison.slr import summarize_slr
    qc,data,_=session_fixture(tmp_path)
    options=dict(pass_sessions=qc['sessions'],pass_source_sha256=qc['source_sha256'])
    changed=data.copy();changed[0,0]+=1/86400
    with pytest.raises(SlrPrerequisiteError,match='map uniquely'):
        summarize_slr(changed,**options)
    duplicate=deepcopy(qc['sessions'][0]);duplicate['session']=2
    with pytest.raises(SlrPrerequisiteError,match='map uniquely'):
        summarize_slr(data,pass_sessions=qc['sessions']+[duplicate],pass_source_sha256=qc['source_sha256'])
    with pytest.raises(SlrPrerequisiteError,match='hash mismatch'):
        summarize_slr(data,pass_sessions=qc['sessions'],pass_source_sha256='0'*64)


def test_crd_pass_without_native_points_remains_explicitly_unavailable(tmp_path):
    from orbit_poc.comparison.slr import summarize_slr
    qc,data,covariance=session_fixture(tmp_path)
    result=summarize_slr(data[:2],predictive_covariance=covariance[:2,:2],
        formal_prediction_stations=['7105'],pass_sessions=qc['sessions'],pass_source_sha256=qc['source_sha256'])
    missing=result['per_pass']['2024-04-24/station-7105/crd-session-1']
    assert missing['status']=='unavailable' and missing['source_normal_points']==2
    assert missing['predictive']['status']=='unavailable'
    assert result['passes']==1 and result['pass_mapping']['source_sessions']==2


def fake_slr_download(monkeypatch):
    """Recorded local fixtures only: tests must never access public flight data."""
    from orbit_poc.comparison import slr
    calls=[]
    def fetch(url,path,**kwargs):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        if path.suffix=='.snx':
            path.write_text('=SNX\n+MODEL/RANGE_BIAS\n'+dhf_record('7105','51','R',value=-5.1,sigma=.4)+'\n'+dhf_record('7105','52','R',value=-4.3,sigma=.4)+'\n')
        else:path.write_text('frozen auxiliary fixture '+url)
        item={'url':url,'path':str(path.resolve()),'sha256':slr.sha256_file(path),'bytes':path.stat().st_size}
        slr.write_json(str(path)+'.source.json',item);calls.append(item)
        return item
    monkeypatch.setattr(slr,'fetch_url',fetch)
    return calls


def test_slr_preflight_uses_station_headers_without_observation_interpretation(tmp_path,monkeypatch):
    from orbit_poc.comparison import slr
    path=tmp_path/'evaluation.crd'
    path.write_text('h2 station 7105 0 0 0\n11 THIS IS DELIBERATELY NOT NUMERIC\n20 ALSO NOT NUMERIC\n')
    calls=fake_slr_download(monkeypatch)
    monkeypatch.setattr(slr,'inspect_crd',lambda *a,**k:pytest.fail('normal-point QC ran before fit'))
    record=slr.preflight_slr_auxiliary('2024-05-11',path,tmp_path/'aux',tmp_path/'corrections.json',allow_frozen_evaluation=True)
    assert record['stations']==['7105']
    assert len(calls)==14
    assert len(slr.slr_auxiliary_inventory(tmp_path/'corrections.json',record))==29
    assert 'THIS IS DELIBERATELY' not in (tmp_path/'corrections.json').read_text()
    monkeypatch.setattr(slr,'fetch_url',lambda *a,**k:pytest.fail('freeze resume accessed network'))
    assert slr.preflight_slr_auxiliary('2024-05-11',path,tmp_path/'aux',tmp_path/'corrections.json',allow_frozen_evaluation=True)==record


@pytest.mark.parametrize('target',['source','acquisition','crd','manifest'])
def test_slr_frozen_corrections_block_mutation_without_refetch(tmp_path,monkeypatch,target):
    from orbit_poc.comparison import slr
    path=crd(tmp_path/'evaluation.crd');fake_slr_download(monkeypatch)
    record=slr.preflight_slr_auxiliary('2024-04-24',path,tmp_path/'aux',tmp_path/'corrections.json')
    monkeypatch.setattr(slr,'fetch_url',lambda *a,**k:pytest.fail('mutation caused network replacement'))
    if target=='manifest':record['stations'].append('7110')
    else:
        changed=path if target=='crd' else Path(record['sources'][0]['path' if target=='source' else 'acquisition_path'])
        changed.write_text(changed.read_text()+'changed')
    with pytest.raises(ValueError,match='changed|modified'):
        slr.verify_slr_auxiliary(record,'2024-04-24',path,tmp_path/'aux')


def test_slr_prediction_reuses_complete_frozen_corrections_offline(tmp_path,monkeypatch):
    from orbit_poc.comparison import slr
    path=crd(tmp_path/'evaluation.crd');fake_slr_download(monkeypatch)
    record=slr.preflight_slr_auxiliary('2024-04-24',path,tmp_path/'aux',tmp_path/'corrections.json')
    monkeypatch.setattr(slr,'fetch_url',lambda *a,**k:pytest.fail('frozen evaluator accessed network'))
    orbit=tmp_path/'orbit';orbit.write_text('fit')
    attitude=tmp_path/'attitude';attitude.write_text('attitude')
    built=slr.build_slr_configs('2024-04-24',path,orbit,attitude,tmp_path/'aux',tmp_path/'prediction',
                               download=False,frozen_auxiliary=record)
    assert built['slr_auxiliary_freeze_hash']==record['manifest_hash']
    assert built['formal_prediction_stations']==['7105']
    assert built['station_bias_policy']['7105']['range_bias_m']==pytest.approx(-.0047)
    # Every direct auxiliary input in the generated predictor was pinned, not
    # just the extra station files originally fetched during evaluation.
    import xml.etree.ElementTree as ET
    sources={item['path'] for item in record['sources']}
    inputs=[node.text for node in ET.parse(built['configs']['predict_slr']).iter() if node.tag.startswith('inputfile') and node.text and node.text.startswith(str(tmp_path/'aux'))]
    assert inputs
    assert all(value.replace('{station}','7105') in sources for value in inputs)
    with pytest.raises(ValueError,match='offline'):
        slr.build_slr_configs('2024-04-24',path,orbit,attitude,tmp_path/'aux',tmp_path/'bad',frozen_auxiliary=record)


def test_frozen_slr_evaluator_requires_campaign_inventory_and_exact_sources(tmp_path,monkeypatch):
    from orbit_poc.comparison import slr
    path=crd(tmp_path/'evaluation.crd');fake_slr_download(monkeypatch)
    manifest=tmp_path/'corrections.json'
    record=slr.preflight_slr_auxiliary('2024-04-24',path,tmp_path/'aux',manifest)
    job={'protocol_hash':'p','source_hash':'s','expected_native_binary_sha256':'n',
         'case':{'date':'2024-04-24'},'backend':{'auxiliary_dir':str(tmp_path/'aux')}}
    output=tmp_path/'jobs/evaluate';output.mkdir(parents=True)
    with pytest.raises(ValueError,match='requires its SLR auxiliary'):
        slr.frozen_slr_auxiliary(job,output,path)
    frozen={'stage':'flight','status':'frozen','protocol_hash':'p','source_hash':'s','native_binary':{'sha256':'n'},
        'slr_auxiliary':[{'date':'2024-04-24','path':str(manifest),'sha256':slr.sha256_file(manifest)}],
        'inputs':slr.slr_auxiliary_inventory(manifest,record)}
    def save():
        payload={k:v for k,v in frozen.items() if k!='input_freeze_hash'}
        frozen['input_freeze_hash']=slr.canonical_hash(payload)
        slr.write_json(tmp_path/'evaluation-input-freeze-flight.json',frozen)
    save()
    assert slr.frozen_slr_auxiliary(job,output,path)==record
    frozen['inputs'].pop();save()
    with pytest.raises(ValueError,match='missing from'):
        slr.frozen_slr_auxiliary(job,output,path)
