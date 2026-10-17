"""Real XML/mask/product operations with native execution excluded."""
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from orbit_poc.segmented import multiday as m,protocol as p
from orbit_poc.comparison import data,groops_config as legacy


def gps_file(path,seconds,date='2024-05-10'):
    origin=(datetime.fromisoformat(date)-datetime(2000,1,1,12)).total_seconds()
    rows=[f'{int(origin+t)} 0 C 1 0 0000000000111111 00000000 23000000 23000001 23000002 1 2 3' for t in seconds]
    path.write_text(f'header:\n  num_records: {len(rows)}\n# End of YAML header\n'+'\n'.join(rows)+'\n');return path


def test_daily_blackouts_and_prefix_selection(tmp_path):
    times=[d*86400+t for d in range(3) for t in (0,39600,39630,46800,46830)]
    path=gps_file(tmp_path/'gps.txt',times)
    for hours in (24,48,72):
        result=m.split_gps1b(path,'2024-05-10',tmp_path/str(hours),p.mask(hours,'blackout'),duration_hours=hours)
        assert result['retained']['records']==3*hours//24
        assert result['heldout']['records']==2*hours//24
        assert result['mask_hash']==p.canonical_hash(p.mask(hours,'blackout'))
    with pytest.raises(ValueError):data.normalize_mask(p.mask(72,'blackout'))


@pytest.mark.parametrize('value',[{'duration_seconds':259201},{'duration_seconds':86400,'intervals_seconds':[[86300,86500]]},{'duration_seconds':172800,'intervals_seconds':[[10,20],[19,40]]},{'cadence_seconds':False},{'x':1}])
def test_multiday_mask_is_strict(value):
    with pytest.raises(ValueError):m.normalize_mask(value)


def test_all_daily_products_and_interpolation_margin():
    assert m.product_dates('2024-05-10T00:00:00',72)==['2024-05-09','2024-05-10','2024-05-11','2024-05-12','2024-05-13']
    with pytest.raises(ValueError):m.product_dates('2024-05-10',72,30)


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    gps=gps_file(tmp_path/'GPS1B.txt',[d*86400+t for d in range(3) for t in (0,30,60,39630,46830)])
    files=[data.artifact(gps,'gnss_observations')]
    for role in ('attitude','gnss_orbits','gnss_clocks','gnss_biases','gnss_attitudes'):
        path=tmp_path/(role+'.txt');path.write_text(role);files.append(data.artifact(path,role))
    aux=tmp_path/'aux';aux.mkdir()
    for name in ('auxiliary_manifest.json','flight_auxiliary_manifest.json'):data.write_json(aux/name,{'status':'complete','sources':[]})
    calls=[]
    def bootstrap(retained,sp3,clock,date,path,**kw):
        calls.append((Path(retained).read_text(),kw));path.write_text('bootstrap retained data')
        return data.artifact(path,'bootstrap_orbit',provenance='gnss_only',mask_hash=data.canonical_hash(kw['mask']))
    monkeypatch.setattr(m,'code_bootstrap',bootstrap)
    return {'date':'2024-05-10','stage':'synthetic','estimation_inputs':files},aux,calls


@pytest.mark.parametrize('hours',[24,48,72])
@pytest.mark.parametrize('method',['groops_pulses','groops_log_drag_ou'])
def test_arc_xml_covers_whole_interval_and_prior_boundaries(inputs,tmp_path,hours,method):
    raw,aux,calls=inputs
    result=m.build_arc_configs(raw,None,aux,tmp_path/'prepared',method=method,duration_hours=hours,mask=p.mask(hours,'blackout'))
    assert result['duration_hours']==hours and len(calls)==1
    assert calls[0][1]['duration_hours']==hours
    assert calls[0][0].count('\n')>2
    for label in ('convert_gnss','variational','estimate'):
        tree=ET.parse(result['configs'][label]);assert tree.find("global/time[@label='timeEnd']").text==f'timeStart+{hours*3600.0}/86400'
        assert all(x.text==f'{hours*3600.0}/86400' for x in tree.findall('.//timeIntervals/timeIntervals/uniformSampling/sampling'))
    tree=ET.parse(result['configs']['convert_gnss']);assert tree.find('.//GnssClockRinex2InstrumentClock/intervals/uniformSampling/timeEnd').text=='timeEnd+1'
    if method=='groops_log_drag_ou':assert len((tmp_path/'prepared/log_density.txt').read_text().splitlines())==hours*60+1
    assert result['mask_hash']==p.canonical_hash(p.mask(hours,'blackout'))


def test_simulation_is_one_continuous_72h_arc(inputs,tmp_path):
    raw,aux,_=inputs;products=[r for r in raw['estimation_inputs'] if r['role'].startswith('gnss_') and r['role']!='gnss_observations']
    target=tmp_path/'simulate';target.mkdir()
    configs=m.simulation_configs({'epoch':'2024-05-10','duration_hours':72,'cadence':30,'seed':610000}, {'mjd_start':60440,'orbit':'truth-orbit','attitude':'truth-attitude'},products,target,{'auxiliary_dir':str(aux)})
    for key in ('simulate','convert_gnss'):
        tree=ET.parse(configs[key]);assert tree.find("global/time[@label='timeEnd']").text=='timeStart+72/24'
        assert all(x.text=='3.0' for x in tree.findall('.//timeIntervals/timeIntervals/uniformSampling/sampling'))


def test_catalog_generates_four_times_initializes_each_prefix_once(tmp_path,monkeypatch):
    generated=[];prepared=[]
    def generate(case,root,options):generated.append(case);return {'status':'observations_ready','case':case}
    def prepare(case,root,runtime,options,raw):prepared.append(case);return {'stage':case['stage'],'case':case['case'],'method':case['method'],'parameters':case['parameters'],'estimation_inputs':[]}
    monkeypatch.setattr(m,'generate_continuous_case',generate);monkeypatch.setattr(m,'prepare_one',prepare)
    monkeypatch.setattr(m.data,'prepare_flight_day',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('flight regeneration forbidden')))
    monkeypatch.setattr(m,'acquire_products',lambda *args,**kwargs:[])
    interpreter=tmp_path/'tudat-python';interpreter.write_bytes(b'controlled test interpreter')
    options={k:'configured' for k in ('cache_dir','auxiliary_dir','example_directory')}
    options.update(tudat_python=str(interpreter),tudat_python_sha256=p.file_hash(interpreter),flight_requests={c['case_id']:{'frozen_original':c['case_id']} for c in p.planned_cases() if c['stage']=='flight'})
    catalog=m.prepare_catalog(p.planned_cases(),tmp_path,{'native':{'path':'never-executed'}},options)
    assert len(generated)==4 and all(c['duration_hours']==72 and 'mask' not in c for c in generated)
    assert len(prepared)==12 and len(catalog['entries'])==28
    for entry in catalog['entries']:
        if entry['case_id'].startswith('flight-'):assert p.read_json(entry['request']['path'])==options['flight_requests'][entry['case_id']]


@pytest.mark.parametrize('method',['groops_pulses','groops_log_drag_ou'])
def test_prepare_one_selects_corrected_profile_through_shared_closure(inputs,tmp_path,monkeypatch,method):
    import numpy as np
    from orbit_poc.comparison import backend,synthetic
    raw,aux,_=inputs
    case=next(c for c in p.planned_cases() if c['stage']=='synthetic'
              and c['case']['orbit']=='leo500' and c['case']['atmosphere']=='quiet'
              and c['case']['duration_hours']==48 and c['method']==method)
    raw={**raw,'duration_hours':72,'case':{**case['case'],'duration_hours':72}}
    binary=tmp_path/'native';binary.write_bytes(b'mocked native executable')
    monkeypatch.setattr(data,'fetch_example_auxiliary',lambda *a:None)
    monkeypatch.setattr(legacy,'fetch_flight_auxiliary',lambda *a:None)
    monkeypatch.setattr(backend,'_verify_transmitters',lambda *a:None)
    configure=synthetic.configure_synthetic_forces
    before={};calls=[]
    def configure_and_capture(*args):
        configured=configure(*args)
        tree=ET.parse(configured['configs']['variational'])
        assert tree.find('.//orbitPocDerivativeProfile') is None
        before['forces']=ET.tostring(tree.find('.//PreprocessingVariationalEquation/forces'))
        before['estimate']=Path(configured['configs']['estimate']).read_bytes()
        before['hashes']={key:configured[key] for key in
                          ('force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash')}
        return configured
    monkeypatch.setattr(synthetic,'configure_synthetic_forces',configure_and_capture)
    states=np.array([[1.,2.,3.,4.,5.,6.],[11.,12.,13.,14.,15.,16.]])
    def execute(binary,config,output_dir,label,**kwargs):
        tree=ET.parse(config)
        if label in ('convert_gnss','convert_receiver'):
            if label=='convert_receiver':
                for node in tree.iter():
                    if node.tag.startswith('outputfile') and node.text.startswith('/'):
                        path=Path(node.text);path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(b'unchanged converted receiver or bootstrap input')
            return {'returncode':0,'config':str(config)}
        propagation=tree.find('.//PreprocessingVariationalEquation')
        assert [n.text for n in propagation.findall('orbitPocDerivativeProfile')]==['synthetic_complete_v1']
        assert ET.tostring(propagation.find('forces'))==before['forces']
        initializer=tree.find('.//PreprocessingVariationalEquationOrbitFit')
        evaluation=tree.find('.//OrbitPocEvaluateVariational')
        if not calls:
            assert initializer is not None
            assert all(initializer.find(name) is None for name in ('stochasticPulse','parametrizationAcceleration'))
        else:
            assert initializer is None
            np.testing.assert_array_equal(backend.read_native_table(
                evaluation.findtext('inputfileInitialState')).ravel(),states[0])
        current=states.copy();current[1,0]+=[0.,.01,.0100005][len(calls)]
        orbit=Path(evaluation.findtext('outputfileOrbit'));orbit.write_bytes(current.tobytes())
        np.savetxt(orbit.with_suffix('.txt'),np.c_[[60440.,60440.+5/86400],current,np.zeros((2,3))])
        calls.append(str(config))
        return {'returncode':0,'config':str(config)}
    monkeypatch.setattr(backend,'run_native',execute)
    output=tmp_path/'prefix'
    result=m.prepare_one(case,output,{'native':{'path':str(binary)}},
                         {'example_directory':None,'auxiliary_dir':str(aux)},raw)
    assert len(calls)==3 and result['method']==method
    blind=p.read_json(output/'native_preparation.json')
    assert blind['nominal_initialization']['converged']
    assert blind['nominal_initialization']['iterations']==2
    for key,value in before['hashes'].items():assert result[key]==blind[key]==value
    assert Path(blind['configs']['estimate']).read_bytes()==before['estimate']
    initialization=p.read_json(blind['nominal_initialization']['record_path'])
    assert initialization['position_tolerance_m']==2e-6
    assert initialization['velocity_tolerance_m_s']==3e-9
    assert initialization['maximum_iterations']==10
    assert initialization['immutable_inputs_unchanged']
    assert initialization['source_configuration']['sha256']==p.file_hash(blind['configs']['variational'])
    assert all(p.file_hash(item['path'])==item['sha256'] for item in blind['native_artifacts'])


def test_prefix_rejects_wrong_continuous_generation(tmp_path):
    case=p.planned_cases()[0]
    with pytest.raises(ValueError,match='continuous72'):m.prefix_inputs({'duration_hours':24},case)


def test_bootstrap_actual_least_squares_over72h(tmp_path,monkeypatch):
    import numpy as np
    date='2024-05-10';t0=(datetime.fromisoformat(date)-datetime(2000,1,1,12)).total_seconds()
    times=t0+np.arange(0,259201,21600);tabletimes=t0+np.arange(-3600,262801,300)
    satellites={};clocks={};observations={};position=np.array([6878137.,0.,0.])
    geometry=np.array([[1,1,1],[1,1,-1],[1,-1,1],[-1,1,1],[-1,-1,1],[-1,1,-1],[1,-1,-1],[-1,-1,-1]],float)
    geometry*=26.56e6/np.sqrt(3)
    for i,xyz in enumerate(geometry):
        sat=f'G{i+1:02d}';satellites[sat]=np.column_stack([tabletimes,np.tile(xyz,(len(tabletimes),1))]);clocks[sat]=np.column_stack([tabletimes,np.zeros(len(tabletimes))])
    for t in times:
        values=[]
        for i,xyz in enumerate(geometry):
            distance=np.linalg.norm(position-xyz)
            for _ in range(8):
                a=7.292115e-5*(distance+30)/299792458.;rot=np.array([[np.cos(a),np.sin(a),0],[-np.sin(a),np.cos(a),0],[0,0,1]])
                distance=np.linalg.norm(position-rot@xyz)
            values.append((f'G{i+1:02d}',distance+30))
        observations[t]=values
    monkeypatch.setattr(m,'read_sp3',lambda x:satellites);monkeypatch.setattr(m,'read_clock',lambda x:clocks);monkeypatch.setattr(m,'read_gps1b_code',lambda x:observations)
    files=[]
    for name in ('gps','sp3','clk'):
        x=tmp_path/name;x.write_text(name);files.append(x)
    result=m.code_bootstrap(*files,date,tmp_path/'initial.txt',duration_hours=72,integration_step_seconds=21600,include_endpoint=True,mask={'cadence_seconds':21600,'duration_seconds':259200})
    values=np.loadtxt(result['path']);assert values.shape==(13,10)
    np.testing.assert_allclose(values[:,1:4],np.tile(position,(13,1)),atol=1e-5)
    assert result['provenance']=='gnss_only' and result['solved_epochs']==13


def test_acquire_products_merges_full_daily_coverage(tmp_path,monkeypatch):
    import gzip
    fetched=[]
    def fetch(url,path):
        name=Path(path).name;day=datetime.strptime(name.split('_')[1][:7],'%Y%j');fetched.append((day,name))
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        if name.endswith('SP3.gz'):
            text='#cP2024 05 09 00 00 00.00000000       2 ORBIT\n'
            for hour in (0,12):text+=f'*  {day.year} {day.month} {day.day} {hour} 0 0.00000000\n'+'PG01'+''.join(f'{v:14.6f}' for v in (1,2,3,4))+'\n'
            text+='EOF\n'
        elif name.endswith('CLK.gz'):
            text='END OF HEADER\n'+''.join(f'AS G01 {day.year} {day.month} {day.day} {hour} 0 0.000000 1 0.0\n' for hour in (0,12))
        elif name.endswith('OBX.gz'):
            text='+EPHEMERIS/DATA\n'+''.join(f'## {day.year} {day.month} {day.day} {hour} 0 0.0 1\nATT G01 4 1 0 0 0\n' for hour in (0,12))+'-EPHEMERIS/DATA\n'
        else:text='OSB fixture'
        with gzip.open(path,'wt') as f:f.write(text)
        return {'path':str(path),'url':url}
    monkeypatch.setattr(m,'fetch_url',fetch);monkeypatch.setattr(m.data,'read_gps_osb',lambda path:{'G01':{'C1C':0.}})
    from orbit_poc.segmented import products as audit
    monkeypatch.setattr(audit,'read_gps_osb',lambda path:{'G01':{'C1C':0.}})
    products=m.acquire_products({'epoch':'2024-05-10T00:00:00','duration_hours':72},{'cache_dir':str(tmp_path/'cache')},tmp_path/'products')
    assert len(fetched)==20 and len(products)==4
    for record in products:
        assert len(record['daily_sources'])==5
        p.verify_nested_artifacts(record['boundary_audit'])
        for day in record['daily_sources']:assert Path(day['path']).is_file()
    assert len(data.read_sp3(products[0]['path'])['G01'])==10
    assert products[-1]['path'].endswith('20241310000_01D_01D_OSB.BIA.gz')


def test_real_generation_entry_uses_tudat_and_native_pipeline(inputs,tmp_path,monkeypatch):
    import numpy as np
    from orbit_poc import simulator
    raw,aux,_=inputs;products=[r for r in raw['estimation_inputs'] if r['role'].startswith('gnss_') and r['role']!='gnss_observations'];calls=[]
    monkeypatch.setattr(m.data,'fetch_example_auxiliary',lambda *a:None)
    monkeypatch.setattr(legacy,'fetch_flight_auxiliary',lambda *a:None)
    monkeypatch.setattr(m,'acquire_products',lambda *a:products)
    def generate(cfg,root,**kwargs):
        assert cfg['duration_hours']==72 and cfg['coverage']=='normal' and kwargs['truth_backend']=='tudat'
        root=Path(root);root.mkdir(parents=True);truth=root/'truth.npz';np.savez(truth,times=[0.,30.,259170.],states=np.zeros((3,6)))
        return {'truth':str(truth),'dataset':str(root/'unused-dataset')}
    monkeypatch.setattr(simulator,'generate',generate)
    def instruments(truth,root,epoch):
        root=Path(root);att=root/'attitude.txt';orb=root/'orbit.txt';att.write_text('attitude');orb.write_text('orbit')
        return {'mjd_start':60440.,'orbit':str(orb),'attitude':str(att)}
    monkeypatch.setattr(m,'write_truth_instruments',instruments)
    def execute(binary,config,root,seed):
        calls.append(Path(config).name);(Path(root)/'ambiguity_truth.txt').write_text('injected ambiguity fixture');return {'returncode':0,'fixture':True}
    monkeypatch.setattr(m,'_execute',execute)
    def export(source,target,**kwargs):
        Path(target).parent.mkdir(parents=True,exist_ok=True);gps_file(Path(target),[0,30,259170]);return {'slips':[]}
    monkeypatch.setattr(m,'receiver_to_gps1b',export);monkeypatch.setattr(m,'read_receiver_ascii',lambda p:[{'mjd':60440.,'clock_seconds':0.}])
    case={**p.planned_cases()[0]['case'],'duration_hours':72}
    result=m.generate_continuous_case(case,tmp_path/'actual-entry',{'auxiliary_dir':str(aux),'cache_dir':str(tmp_path/'cache'),'example_directory':None,'groops_executable':'fixture','retain_native_diagnostics':True})
    assert calls==['convert_transmitters.xml','simulate_receiver.xml'] and result['duration_hours']==72
    assert result['native_simulation']['bootstrap_performed'] is False and result['native_simulation']['mask_applied'] is False
    assert all(x['role']!='truth' for x in result['estimation_inputs']) and result['evaluation_inputs'][0]['role']=='truth'


def test_preparation_components_resume_only_sealed_complete_outputs(tmp_path,monkeypatch):
    from orbit_poc.segmented import preparation as jobs
    from orbit_poc.segmented.config import SegmentedConfig
    from dataclasses import replace
    calls=[];config=replace(SegmentedConfig(),output_dir=str(tmp_path));runtime={'source_root':'fixture','native':{'path':'fixture'}};plan={'plan_hash':'a'*64,'cases':p.planned_cases()}
    monkeypatch.setattr(p,'admission',lambda *args:None)
    monkeypatch.setattr(p,'wrap_flight_request',lambda value,*args:value)
    flight={c['case_id']:{'historical':c['case_id']} for c in plan['cases'] if c['stage']=='flight'}
    def execute(job,*args):
        calls.append(job);output=Path(job['output']);output.mkdir(parents=True);(output/'observations.dat').write_bytes(b'fixture native output')
        value={'stage':job['case']['stage'],'case':job['case']['case'],'estimation_inputs':[{'role':'fixture',**p.artifact(output/'observations.dat')}]}
        return {'status':'prepared','component':job['component'],'record':value,'harness_execution':{'owned_process_group_cleaned':True}}
    monkeypatch.setattr(p,'_execute_job',execute)
    first=jobs.prepare_inputs(config,plan,tmp_path,tmp_path,runtime,flight)
    assert len(first['entries'])==28 and len(calls)==16 and sum(j['component']=='generation' for j in calls)==4
    assert jobs.prepare_inputs(config,plan,tmp_path,tmp_path,runtime,flight)==first and len(calls)==16
    (Path(calls[0]['output'])/'new-input.G32.dat').write_bytes(b'new wildcard member')
    with pytest.raises(ValueError,match='membership'):jobs.prepare_inputs(config,plan,tmp_path,tmp_path,runtime,flight)


def test_failed_preparation_component_is_preserved_and_never_overwritten(tmp_path,monkeypatch):
    from orbit_poc.segmented import preparation as jobs
    from orbit_poc.segmented.config import SegmentedConfig
    monkeypatch.setattr(p,'admission',lambda *args:None)
    monkeypatch.setattr(p,'_execute_job',lambda *args:{'status':'timeout','error':'controlled deadline','harness_execution':{'owned_process_group_cleaned':True}})
    args=(SegmentedConfig(),{'plan_hash':'a'*64},tmp_path,tmp_path,{},'one','generation',p.planned_cases()[0],tmp_path/'output')
    with pytest.raises(p.NotReady,match='component failed'):jobs.component(*args)
    path=tmp_path/'preparation-jobs'/'one'/'execution.json';before=path.read_bytes()
    with pytest.raises(p.NotReady,match='preserved'):jobs.component(*args)
    assert path.read_bytes()==before and not (path.parent/'checkpoint.json').exists()


def test_real_component_worker_calls_continuous_generator(tmp_path,monkeypatch):
    from orbit_poc.segmented import preparation as jobs
    interpreter=tmp_path/'python';interpreter.write_bytes(b'fixture interpreter');seen=[]
    monkeypatch.setattr(m,'generate_continuous_case',lambda case,output,options:seen.append((case,output,options)) or {'status':'observations_ready'})
    job={'component':'generation','case':p.planned_cases()[0],'output':str(tmp_path/'generation'),'runtime':{'native':{'path':'native'}},'options':{'tudat_python':str(interpreter),'tudat_python_sha256':p.file_hash(interpreter)}}
    assert jobs.worker(job,tmp_path)['status']=='prepared'
    assert seen[0][0]['duration_hours']==72 and 'mask' not in seen[0][0] and seen[0][2]['groops_executable']=='native'
