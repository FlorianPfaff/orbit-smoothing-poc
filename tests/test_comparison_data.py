"""Regression gates for masking, input isolation, and native prior semantics."""
from datetime import datetime
import io
import json
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET

import pytest

from orbit_poc.comparison import data, groops_config as gc


def gps_file(path, seconds):
    origin = (datetime(2024, 4, 24)-datetime(2000, 1, 1, 12)).total_seconds()
    rows = [f"{int(origin+t)} 0 C 1 0 0000000000111111 00000000 23000000 23000001 23000002 1 2 3" for t in seconds]
    path.write_text(f"header:\n  dimensions:\n    num_records: {len(rows)}\n# End of YAML header\n"+"\n".join(rows)+"\n")
    return path


def test_mask_converts_utc_to_gps_before_removal(tmp_path):
    source = gps_file(tmp_path/"GPS1B.txt", [39570, 39600, 39630, 46770, 46800, 46830])
    mask = {"intervals_seconds": [[39600, 46800]], "cadence_seconds": 30, "time_scale": "UTC"}
    split = data.split_gps1b(source, "2024-04-24", tmp_path/"split", mask)
    assert split["retained"]["records"] == 3
    assert split["heldout"]["records"] == 3
    assert data.canonical_hash(mask) == split["mask_hash"]
    _, retained = data._gps1b_text(split["retained"]["path"])
    _, hidden = data._gps1b_text(split["heldout"]["path"])
    assert not set(retained) & set(hidden)
    # 11:00:00 GPS precedes 11:00 UTC by18s, while13:00GPS is still hidden.
    assert retained[1].split()[0] == str(int((datetime(2024,4,24)-datetime(2000,1,1,12)).total_seconds()+39600))


def test_invalid_masks_and_locked_dates():
    with pytest.raises(ValueError): data.normalize_mask({"intervals_seconds": [[1, 4], [3, 5]]})
    with pytest.raises(ValueError): data.normalize_mask({"time_scale": "TAI"})
    with pytest.raises(ValueError): data.validate_flight_date("2024-05-10")
    assert data.validate_flight_date("2024-05-10", allow_frozen_evaluation=True) == "flight_evaluation"
    with pytest.raises(ValueError): data.validate_flight_date("2024-06-10", allow_frozen_evaluation=True)


def test_archive_rejects_traversal_and_symlinks(tmp_path):
    for name, kind in (("../stolen", tarfile.REGTYPE), ("evil", tarfile.SYMTYPE)):
        bundle = tmp_path/"bundle.tgz"
        with tarfile.open(bundle,"w:gz") as archive:
            item = tarfile.TarInfo(name)
            item.type, item.size = kind, 1 if kind == tarfile.REGTYPE else 0
            item.linkname = "/etc/passwd"
            archive.addfile(item, io.BytesIO(b"x") if item.size else None)
        with pytest.raises(ValueError, match="unsafe"):
            data.extract_gracefo_bundle(bundle,tmp_path/"out","2024-04-24")


def test_cached_download_and_manifest_reject_changed_inputs(tmp_path):
    path = tmp_path/"file"
    path.write_bytes(b"original")
    data.write_json(path.with_name("file.source.json"), {"sha256": data.sha256_file(path), "url": "https://example.org/file"})
    manifest = {"estimation_inputs": [data.artifact(path,"gnss_observations")]}
    path.write_bytes(b"changed")
    with pytest.raises(ValueError): data.fetch_url("https://example.org/file",path,download=False)
    with pytest.raises(ValueError): data.verify_manifest(manifest)
    reference = tmp_path/"GNV1B_reference.txt"
    reference.write_text("reference")
    with pytest.raises(ValueError,match="evaluation"):
        data.verify_manifest({"estimation_inputs":[data.artifact(reference,"gnss_observations")]})


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    source = gps_file(tmp_path/"GPS1B.txt",[0,30,60,39600,39630,46800,46830])
    inputs = [data.artifact(source,"gnss_observations")]
    for role in ("attitude","gnss_orbits","gnss_clocks","gnss_biases","gnss_attitudes"):
        path = tmp_path/(role+".txt")
        path.write_text(role)
        inputs.append(data.artifact(path,role))
    reference = tmp_path/"GNV1B.txt"
    reference.write_text("evaluation only")
    auxiliary = tmp_path/"auxiliary"
    auxiliary.mkdir()
    for name in ("auxiliary_manifest.json","flight_auxiliary_manifest.json"):
        data.write_json(auxiliary/name,{"status":"complete","sources":[]})
    def bootstrap(retained,sp3,clock,date,path,**kwargs):
        path.write_text(Path(retained).read_text())
        return data.artifact(path,"bootstrap_orbit",provenance="gnss_only",mask_hash=data.canonical_hash(kwargs["mask"]))
    monkeypatch.setattr(gc,"code_bootstrap",bootstrap)
    manifest = {"date":"2024-04-24","estimation_inputs":inputs,
                "evaluation_inputs":[data.artifact(reference,"reference_orbit")]}
    return manifest,auxiliary,tmp_path


def test_native_models_share_inputs_but_use_distinct_correct_priors(prepared):
    source,aux,tmp = prepared
    mask = {"intervals_seconds":[[39600,46800]],"cadence_seconds":30,"time_scale":"UTC"}
    pulse = gc.build_day_configs(source,None,aux,tmp/"pulse",mask=mask,pulse_sigma_velocity_m_s=1e-4)
    density = gc.build_day_configs(source,None,aux,tmp/"density",mask=mask,method="groops_log_drag_ou")
    for key in ("force_model_hash","measurement_model_hash","preprocessing_hash"):
        assert pulse[key] == density[key]
    assert pulse["status"] == "configured" and not pulse["metadata"]["native_execution_verified"]
    assert pulse["calibration_inputs"][0]["role"] == "heldout_gnss_code"
    assert not any(x["role"] == "heldout_gnss_code" for x in pulse["estimation_inputs"])
    for prepared in (pulse,density):
        xml = "".join(Path(p).read_text() for p in prepared["configs"].values())
        assert "GNV1B" not in xml and "resolveAmbiguities" not in xml
        initial = ET.parse(prepared["configs"]["variational"]).find(".//PreprocessingVariationalEquationOrbitFit")
        assert initial.find("stochasticPulse") is None
    estimate = ET.parse(pulse["configs"]["estimate"])
    assert float(estimate.find(".//constraints/sigma").text) == 100.
    assert estimate.find(".//constraints/parameters/wildcard/type").text == "stochasticPulse.*"
    assert estimate.find(".//timeSeries/uniformSampling/sampling").text == "30/86400"
    steps = list(estimate.findall(".//GnssProcessing/processingStep"))
    names = [list(step)[0].tag for step in steps]
    assert names.index("computeCovarianceMatrix") < names.index("writeResults")
    force = ET.parse(density["configs"]["variational"]).find(".//forces")
    assert force.find("miscAccelerations/logDensity/nominalDrag/atmosphericDrag") is not None
    assert force.find("miscAccelerations/relativisticEffect") is not None
    assert force.find("miscAccelerations/radiationPressure") is not None
    assert force.find("miscAccelerations/radiationPressure/orbitPocThermalMaximumStep").text == "0.1"


def test_campaign_thermal_setting_is_in_common_force_hash(prepared,monkeypatch):
    source,aux,tmp=prepared
    selected=gc.build_day_configs(source,None,aux,tmp/'thermal-selected')
    original=gc._flight_thermal_step
    def refinement(tree):
        original(tree)
        tree.find('.//radiationPressure/orbitPocThermalMaximumStep').text='0.05'
    monkeypatch.setattr(gc,'_flight_thermal_step',refinement)
    refined=gc.build_day_configs(source,None,aux,tmp/'thermal-refined')
    assert selected['force_model_hash']!=refined['force_model_hash']
    assert selected['measurement_model_hash']==refined['measurement_model_hash']


def test_fit_clone_preserves_physics_and_has_no_evaluation_inputs(prepared):
    source,aux,tmp = prepared
    prepared = gc.build_day_configs(source,None,aux,tmp/"prepared")
    tree = ET.parse(prepared["configs"]["variational"])
    tree.find(".//forces/gravityfield/potentialCoefficients/maxDegree").text = "42"
    tree.write(prepared["configs"]["variational"])
    clone = gc.build_fit_configs(prepared,tmp/"clone","groops_log_drag_ou",
                                 {"knot_seconds":60,"tau_seconds":1800,"sigma_log_density":.1})
    assert "evaluation_inputs" not in clone and "calibration_inputs" not in clone
    assert ET.parse(clone["configs"]["variational"]).find(".//forces/gravityfield/potentialCoefficients/maxDegree").text == "42"
    assert ET.parse(clone["configs"]["estimate"]).find(".//logDensityOu/tau").text == "1800.0"
    assert not ET.parse(clone["configs"]["estimate"]).findall(".//stochasticPulse")
    back = gc.build_fit_configs(clone,tmp/"back","groops_pulses",{"interval_seconds":600,"sigma_velocity_m_s":.001})
    assert not ET.parse(back["configs"]["variational"]).findall(".//logDensity")
    assert float(ET.parse(back["configs"]["estimate"]).find(".//constraints/sigma").text) == 1000.


def test_short_arc_and_stock_ar_exports_are_ordered(prepared):
    source,aux,tmp=prepared
    item=gc.build_day_configs(source,None,aux,tmp/'short',duration_hours=1,method='groops_log_drag_ou')
    assert item['duration_hours']==1
    assert len((tmp/'short/log_density.txt').read_text().splitlines())==61
    tree=ET.parse(item['configs']['variational'])
    assert tree.find("global/time[@label='timeEnd']").text=='timeStart+3600.0/86400'
    assert tree.find('.//timeIntervals/timeIntervals/uniformSampling/sampling').text=='3600.0/86400'
    ar=gc.build_fit_configs(item,tmp/'ar','groops_pulses_ar',{})
    tree=ET.parse(ar['configs']['estimate']);gnss=tree.find('.//GnssProcessing')
    assert tree.find('.//supportsIntegerAmbiguities').text=='1'
    assert tree.find('.//constraints') is None
    assert tree.find('.//stochasticPulse/uniformSampling/sampling').text=='1200/86400'
    assert ET.parse(ar['configs']['variational']).find('.//PreprocessingVariationalEquationOrbitFit/stochasticPulse') is not None
    steps=[list(x)[0].tag for x in gnss.findall('processingStep')]
    assert steps[:3]==['estimate','resolveAmbiguities','estimate']
    assert steps[-1]=='writeAprioriSolution'
    assert max(i for i,c in enumerate(gnss) if c.tag=='parametrization') < min(i for i,c in enumerate(gnss) if c.tag=='processingStep')
    assert tree.find('.//leoDynamicOrbits/outputfileParameterCovariance').text==ar['result_paths']['parameter_covariance']
    back=gc.build_fit_configs(ar,tmp/'float','groops_pulses',{'interval_seconds':600,'sigma_velocity_m_s':1e-4})
    assert ET.parse(back['configs']['estimate']).find('.//resolveAmbiguities') is None
    assert ET.parse(back['configs']['variational']).find('.//PreprocessingVariationalEquationOrbitFit/stochasticPulse') is None


def test_flight_screening_blocks_orbit_maneuver_not_routine_attitude_event(tmp_path):
    def native(name,rows):
        p=tmp_path/name;p.write_text('header:\n# End of YAML header\n'+'\n'.join(rows)+'\n')
        return data.artifact(p,'spacecraft_metadata')
    row=['0']*47
    row[0:4]=['767188800','0','G','C'];row[18]='600';row[46]='00001100'
    inputs=[native('THR1B_test.txt',[' '.join(row)]),native('SCA1B_test.txt',['767188800 C 23 1 0 0 0 0 00000000']),
            data.artifact(gps_file(tmp_path/'GPS1B_test.txt',[0,30]),'gnss_observations')]
    manifest={'date':'2024-04-24','estimation_inputs':inputs}
    result=data.screen_flight_inputs(manifest)
    assert result['status']=='eligible' and result['counts']['thruster']['attitude_control_events']==1
    row[30]='1200';inputs[0]=native('THR1B_test.txt',[' '.join(row)])
    result=data.screen_flight_inputs(manifest)
    assert result['status']=='excluded' and 'orbital_control_thruster_activity' in result['exclusion_reasons']
    assert not result['replacement_date_allowed']


def test_provider_quality_removed_before_native_conversion(tmp_path):
    p=gps_file(tmp_path/'GPS1B.txt',[0,30,60])
    s=p.read_text().splitlines();s[-2]=s[-2].replace('00000000','00000011');p.write_text('\n'.join(s)+'\n')
    result=data.split_gps1b(p,'2024-04-24',tmp_path/'split',None)
    assert result['provider_quality_excluded_records']==1 and result['retained']['records']==2


def test_shared_acquired_product_cache_is_offline_and_isolated(tmp_path,monkeypatch):
    source=tmp_path/'old/product.gz';source.parent.mkdir();source.write_bytes(b'original public input')
    url='https://example.org/product.gz'
    record={'url':url,'sha256':data.sha256_file(source),'bytes':source.stat().st_size,'acquired_at':'original acquisition'}
    data.write_json(source.with_name(source.name+'.source.json'),record)
    cache=tmp_path/'cache/gnss/product.gz'
    monkeypatch.setattr(data,'urlopen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('network access')))
    first=data._cached_day_product(url,cache,source,download=False)
    second_path=tmp_path/'new/product.gz'
    second=data._cached_day_product(url,cache,second_path,download=False)
    assert first['sha256']==second['sha256']==record['sha256']
    assert second['acquired_at']=='original acquisition'
    assert json.loads(cache.with_name(cache.name+'.source.json').read_text())==record
    second_path.write_bytes(b'changed isolated job input')
    assert cache.read_bytes()==b'original public input'
    with pytest.raises(ValueError,match='isolated product changed'):
        data._cached_day_product(url,cache,second_path,download=False)


def test_native_bootstrap_epochs_canonicalized_before_differentiation(prepared):
    source,aux,tmp=prepared
    configured=gc.build_day_configs(source,None,aux,tmp/'canonical',duration_hours=1,integration_step_seconds=2.5)
    tree=ET.parse(configured['configs']['convert_receiver'])
    programs=[list(p)[0] for p in tree.findall('program')]
    types=[p.tag for p in programs]
    first_resample=types.index('InstrumentResample')
    assert types.index('GroopsAscii2Orbit')<first_resample<types.index('OrbitAddVelocityAndAcceleration')
    grid=programs[first_resample].find('timeSeries/uniformSampling')
    assert grid.find('sampling').text=='2.5/86400'
    assert grid.find('timeEnd').text.endswith('(3600-1.25)/86400') or grid.find('timeEnd').text.endswith('(3600.0-1.25)/86400')


def test_auxiliary_selection_frozen_and_relocation_explicit(tmp_path,monkeypatch):
    root=tmp_path/'aux';p=root/'earthRotation/model.dat';p.parent.mkdir(parents=True);p.write_bytes(b'pinned model')
    record={'url':data.GROOPS_DATA+'earthRotation/model.dat','path':'/old-machine/earthRotation/model.dat',
            'sha256':data.sha256_file(p),'bytes':p.stat().st_size}
    data.write_json(p.with_name(p.name+'.source.json'),record)
    data.write_json(root/'auxiliary_manifest.json',{'status':'complete','sources':[record]})
    monkeypatch.setattr(data,'urlopen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('network access')))
    with pytest.raises(ValueError,match='explicit offline relocation'):
        data.fetch_example_auxiliary(tmp_path/'unused-example',root,download=True)
    moved=data.reuse_auxiliary_manifest(root,relocate=True)
    assert moved['sources'][0]['path']==str(p.resolve())
    assert moved['sources'][0]['sha256']==record['sha256']
    assert data.fetch_example_auxiliary(tmp_path/'unused-example',root,download=True)==moved
    p.write_bytes(b'changed model')
    with pytest.raises(ValueError,match='checksum mismatch'):
        data.fetch_example_auxiliary(tmp_path/'unused-example',root,download=True)


def test_utc_arc_retains_next_gps_midnight_on_native_cadence(tmp_path):
    arc=data.flight_arc('2024-04-24')
    origin=(datetime(2024,4,24)-datetime(2000,1,1,12)).total_seconds()
    assert arc['start_gps_seconds_since_j2000']==origin+18
    assert arc['end_gps_seconds_since_j2000']==origin+86418
    source=gps_file(tmp_path/'GPS1B.txt',[0,10,18,20,30,86370,86400,86410,86418,86430])
    split=data.split_gps1b(source,'2024-04-24',tmp_path/'split',
        {'time_scale':'UTC','cadence_seconds':30},arc_start_offset_seconds=18)
    _,rows=data._gps1b_text(split['retained']['path'])
    assert [float(row.split()[0])-origin for row in rows]==[30,86370,86400]


def _osb_file(path,entries):
    lines=[]
    for signal,value in entries:
        row=[' ']*103
        for index,text in ((1,'OSB'),(6,'G049'),(11,'G01'),(25,signal),(35,'2024:115:00000'),
                           (50,'2024:116:00000'),(65,'ns'),(70,f'{value:21.8f}')):
            row[index:index+len(text)]=text
        lines.append(''.join(row))
    path.write_text('\n'.join(lines)+'\n');return path


def test_boundary_osb_native_sign_and_phase_attribute_mapping(tmp_path):
    base=data.read_gps_osb(_osb_file(tmp_path/'base.bia',[('C1C',1),('C1W',2),('C2W',3),('L1C',4),('L1W',99),('L2W',5)]))
    active=data.read_gps_osb(_osb_file(tmp_path/'active.bia',[('C1C',6),('C1W',7),('C2W',8),('L1W',9),('L2W',10)]))
    row='767275200 0 C 1 0 0000000000111111 00000000 23000000 23000001 23000002 23000003 23000004 23000005'
    normalized,corrections=data.normalize_boundary_osb(row,base,active)
    old=list(map(float,row.split()[7:]));new=list(map(float,normalized.split()[7:]))
    # Native GnssObservationEquation subtracts antennaVariations, and native
    # GnssTransceiver adds signalBias.compute(types) to those variations.
    for bit,signal in enumerate(('C1C','C1W','C2W','L1','L1','L2')):
        assert new[bit]-base['G01'][signal]==pytest.approx(old[bit]-active['G01'][signal],abs=8e-9)
        assert corrections[str(bit)]['native_signal']==signal
    assert base['G01']['L1']==pytest.approx(4e-9*299792458.)  # first frequency bias, not99ns
    assert normalized.split()[5:7]==row.split()[5:7]  # no injected quality/slip flags


def test_utc_native_grids_and_immutable_preprocessing(prepared,monkeypatch):
    source,aux,tmp=prepared
    source={**source,'arc':data.flight_arc('2024-04-24')}
    pulse=gc.build_day_configs(source,None,aux,tmp/'utc',duration_hours=24)
    tree=ET.parse(pulse['configs']['convert_receiver'])
    grid=tree.find('.//InstrumentResample/timeSeries/uniformSampling')
    assert grid.find('timeStart').text=='60424'
    assert grid.find('offsetSeconds').text=='18'
    assert grid.find('timeEnd').text=='60424+(86400+2.5)/86400'
    estimate=ET.parse(pulse['configs']['estimate'])
    obs=estimate.find('.//GnssProcessing/timeSeries/uniformSampling')
    assert obs.find('offsetSeconds').text=='30'
    assert obs.find('timeEnd').text=='loopTimeEnd-27.0/86400'
    density=gc.build_fit_configs(pulse,tmp/'utc-density','groops_log_drag_ou',
        {'tau_seconds':7200,'sigma_log_density':.3,'knot_seconds':60})
    from decimal import Decimal
    t=Decimal((tmp/'utc-density/log_density.txt').read_text().split()[0])
    assert abs((t-Decimal(60424))*Decimal(86400)-18)<Decimal('0.000000001')
    estimate=ET.parse(density['configs']['estimate'])
    receiver=estimate.find('.//receiver/lowEarthOrbiter')
    assert receiver.find('inputfileOrbit').text==pulse['native_paths']['receiver_orbit']
    assert receiver.find('inputfileStarCamera').text==pulse['native_paths']['receiver_attitude']
    assert receiver.find('orbitPocPreprocessFromInputOrbit').text=='1'
    assert receiver.find('outputfileOrbitPocPreprocessingAudit').text==density['result_paths']['preprocessing_audit']
    assert estimate.find('.//leoDynamicOrbits/outputfileCovarianceObservationEpochs').text==density['result_paths']['covariance_observations']
    assert ET.parse(density['configs']['variational']).find('.//orbitPocAtmosphericForce/logDensity/nominalDrag/atmosphericDrag') is not None
    assert ET.parse(density['configs']['variational']).find('.//orbitPocAtmosphericHasDensityKnots').text=='1'
    assert ET.parse(density['configs']['variational']).find('.//orbitPocAtmosphericQuadratureStep').text=='1'
    assert ET.parse(pulse['configs']['variational']).find('.//orbitPocAtmosphericHasDensityKnots') is None
    assert estimate.find('.//parametrizationAcceleration/logDensity/orbitPocAtmosphereEvents').text=='1'
    assert estimate.find('.//parametrizationAcceleration/logDensity/orbitPocAtmosphericQuadratureStep').text=='1'
    ar=gc.build_fit_configs(pulse,tmp/'utc-ar','groops_pulses_ar',{})
    for item in (pulse,density,ar):
        assert ET.parse(item['configs']['variational']).find('.//radiationPressure/orbitPocThermalMaximumStep').text=='0.1'
    # The independently reproduced official template keeps its native default.
    assert ET.parse(gc.TEMPLATES/'03groopsVariational.xml').find('.//orbitPocThermalMaximumStep') is None
    receiver=ET.parse(ar['configs']['estimate']).find('.//receiver/lowEarthOrbiter')
    assert receiver.find('orbitPocPreprocessFromInputOrbit') is None
    assert receiver.find('outputfileOrbitPocPreprocessingAudit') is None


def test_synthetic_clone_has_no_flight_event_fields(prepared):
    source,aux,tmp=prepared
    item=gc.build_day_configs(source,None,aux,tmp/'prepared')
    tree=ET.parse(item['configs']['variational'])
    force=tree.find('.//forces/miscAccelerations/atmosphericDrag');force.tag='syntheticDrag'
    tree.write(item['configs']['variational'])
    clone=gc.build_fit_configs(item,tmp/'synthetic','groops_log_drag_ou',{'tau_seconds':7200,'sigma_log_density':.3})
    assert ET.parse(clone['configs']['variational']).find('.//orbitPocAtmosphericForce') is None
    assert ET.parse(clone['configs']['estimate']).find('.//orbitPocAtmosphereEvents') is None
    assert ET.parse(clone['configs']['estimate']).find('.//orbitPocAtmosphericQuadratureStep') is None
    assert ET.parse(clone['configs']['variational']).find('.//orbitPocAtmosphericQuadratureStep') is None


def test_flight_attitude_is_canonical_across_state_grids(prepared):
    source,aux,tmp=prepared
    source={**source,'arc':data.flight_arc('2024-04-24')}
    coarse=gc.build_day_configs(source,None,aux,tmp/'attitude-coarse',integration_step_seconds=5)
    fine=gc.build_day_configs(source,None,aux,tmp/'attitude-fine',integration_step_seconds=2.5)
    assert 'attitude_integration' not in coarse['native_paths']
    assert 'attitude_integration' in fine['native_paths']
    tree=ET.parse(fine['configs']['convert_receiver'])
    samplers=tree.findall('.//InstrumentResample')
    canonical=next(p for p in samplers if p.find('outputfileInstrument').text==fine['native_paths']['attitude'])
    assert canonical.find('timeSeries/uniformSampling/sampling').text=='5/86400'
    synchronized=next(p for p in samplers if p.find('outputfileInstrument').text==fine['native_paths']['attitude_integration'])
    assert synchronized.find('inputfileInstrument').text==fine['native_paths']['attitude']
    assert synchronized.find('method/polynomial/polynomialDegree').text=='7'
    assert ET.parse(fine['configs']['variational']).find('.//PreprocessingVariationalEquation/inputfileStarCamera').text==fine['native_paths']['attitude_integration']
    receiver=ET.parse(fine['configs']['estimate']).find('.//receiver/lowEarthOrbiter')
    assert receiver.find('inputfileStarCamera').text==fine['native_paths']['receiver_attitude']
    with pytest.raises(ValueError,match='subdivide'):
        gc.build_day_configs(source,None,aux,tmp/'invalid-attitude-grid',integration_step_seconds=2)


def test_receiver_geometry_uses_actual_observation_epochs_and_canonical_curve(prepared):
    source,aux,tmp=prepared
    source={**source,'arc':data.flight_arc('2024-04-24')}
    configured=gc.build_day_configs(source,None,aux,tmp/'receiver-epochs',integration_step_seconds=2.5)
    conversion=ET.parse(configured['configs']['convert_receiver'])
    samplers=conversion.findall('.//InstrumentResample')
    for target,source_key in [('receiver_orbit','orbit'),('receiver_attitude','attitude')]:
        sampler=next(p for p in samplers if p.find('outputfileInstrument').text==configured['native_paths'][target])
        assert sampler.find('inputfileInstrument').text==configured['native_paths'][source_key]
        assert sampler.find('timeSeries/instrument/inputfileInstrument').text==configured['native_paths']['receiver']
        assert sampler.find('timeSeries/uniformSampling') is None
        assert sampler.find('method/polynomial/polynomialDegree').text=='7'
    estimate=ET.parse(configured['configs']['estimate'])
    observation_grid=estimate.find('.//GnssProcessing/timeSeries/uniformSampling')
    assert observation_grid.find('offsetSeconds').text=='30'
    assert observation_grid.find('sampling').text=='30/86400'
    assert estimate.find("global/filename[@label='orbitPocCanonicalAttitude']").text==configured['native_paths']['attitude']
    assert configured['preprocessing_orbit_path']==configured['native_paths']['receiver_orbit']


def test_prediction_resamples_piecewise_orbit_and_canonical_attitude(prepared):
    source,aux,tmp=prepared
    source={**source,'arc':data.flight_arc('2024-04-24')}
    configured=gc.build_day_configs(source,None,aux,tmp/'prediction-source',
        mask={'intervals_seconds':[[39600,46800]],'cadence_seconds':30,'time_scale':'UTC'})
    model=gc.build_prediction_config(configured['configs']['estimate'],tmp/'fitted.dat',
                                    configured['calibration_inputs'],tmp/'prediction')
    conversion=ET.parse(model['configs']['convert_holdout'])
    assert conversion.find("global/filename[@label='orbitPocCanonicalAttitude']").text==configured['native_paths']['attitude']
    orbit=conversion.find('.//OrbitPocResampleOrbit')
    assert orbit.find('inputfileOrbit').text==str(tmp/'fitted.dat')
    assert orbit.find('stochasticPulse/uniformSampling/offsetSeconds').text=='1218'
    assert orbit.find('timeSeries/instrument/inputfileInstrument').text.endswith('heldout_receiver.dat')
    attitude=conversion.find('.//InstrumentResample')
    assert attitude.find('inputfileInstrument').text==configured['native_paths']['attitude']
    receiver=ET.parse(model['configs']['predict']).find('.//receiver/lowEarthOrbiter')
    assert ET.parse(model['configs']['predict']).find('.//outputfileSupport').text==model['predictive_support']
    assert receiver.find('inputfileOrbit').text==model['receiver_orbit']
    assert receiver.find('inputfileStarCamera').text==model['receiver_attitude']
    assert receiver.find('preprocessing') is not None
    assert 'loopTime' not in Path(model['configs']['convert_holdout']).read_text()


def test_utc_assembly_clips_support_data_and_never_reads_reference(tmp_path,monkeypatch):
    origin=int((datetime(2024,4,24)-datetime(2000,1,1,12)).total_seconds())
    bundles=[]
    for index in (0,1):
        d=tmp_path/f'day{index}';d.mkdir();items=[]
        def put(product,rows,role):
            path=d/f'{product}.txt'
            path.write_text(f'header:\n  dimensions:\n    num_records: {len(rows)}\n# End of YAML header\n'+'\n'.join(rows)+'\n')
            items.append(data.artifact(path,role,product=product))
        offsets=([0,10,20,30,86390] if not index else [0,10,20,30])
        put('GPS1B',[f'{origin+index*86400+t} 0 C 1 0 0000000000111111 00000000 23000000 23000001 23000002 1 2 3' for t in offsets],'gnss_observations')
        put('SCA1B',[f'{origin+index*86400+t} C 19 1 0 0 0 0 00000000' for t in (range(86400) if not index else range(20))],'attitude')
        row=['0']*47;row[:4]=[str(origin+index*86400+(16 if not index else 30)),'0','G','C'];row[46]='00001100'
        if not index:row[18]='3000'  # begins before UTC arc but remains active within it
        put('THR1B',[' '.join(row)],'spacecraft_metadata')
        put('MAS1B',[f'{origin+index*86400+10} 0 G C 0 0'],'spacecraft_metadata')
        bundles.append({'estimation_inputs':items,'evaluation_inputs':[{'path':'GNV-MUST-NOT-BE-OPENED'}]})
    b0=_osb_file(tmp_path/'base.bia',[('C1C',1),('C1W',2),('C2W',3)])
    b1=_osb_file(tmp_path/'next.bia',[('C1C',4),('C1W',5),('C2W',6)])
    original=data._gps1b_text
    def guard(path):
        assert 'GNV' not in str(path)
        return original(path)
    monkeypatch.setattr(data,'_gps1b_text',guard)
    assembly=data.assemble_utc_mission_inputs('2024-04-24',*bundles,tmp_path/'utc',[b0,b1])
    gps=next(x for x in assembly['estimation_inputs'] if x['role']=='gnss_observations')
    _,rows=original(gps['path'])
    assert [int(x.split()[0])-origin for x in rows]==[20,30,86390,86400,86410]
    sca=next(x for x in assembly['estimation_inputs'] if x['role']=='attitude')
    assert sca['records']==86401
    thr=next(x for x in assembly['estimation_inputs'] if x.get('product')=='THR1B')
    assert [int(x.split()[0])-origin for x in original(thr['path'])[1]]==[16]
    ledger=json.loads(Path(assembly['normalization']).read_text())
    assert len(ledger['corrections'])==2 and not ledger['reference_inputs_used']
    assert all('GNV' not in x['path'] for x in assembly['estimation_inputs'])


def test_merged_transmitter_clock_keeps_next_day_boundary(tmp_path):
    header='     3.00           C                                       RINEX VERSION / TYPE\n                                                            END OF HEADER\n'
    p=tmp_path/'a.clk';q=tmp_path/'b.clk'
    p.write_text(header+'AS G01 2024 04 24 23 59 30.000000 1 1e-9\nAS G01 2024 04 25 00 00 00.000000 1 2e-9\n')
    q.write_text(header+'AS G01 2024 04 25 00 00 00.000000 1 3e-9\nAS G01 2024 04 25 00 00 30.000000 1 4e-9\nAS G01 2024 04 26 00 00 00.000000 1 5e-9\n')
    merged=data.merge_gnss_products([p,q],tmp_path/'merged.CLK','gnss_clocks')
    clock=data.read_clock(merged['path'])['G01']
    assert len(clock)==3
    assert clock[:,1].tolist()==[1e-9,3e-9,4e-9]
    assert clock[-1,0]-clock[0,0]==60


def test_verified_auxiliary_alias_returns_requested_paths_without_rewriting_manifest(tmp_path):
    root=tmp_path/'aux';root.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True)
    path=root/'model.dat';path.write_bytes(b'pinned')
    record={'url':data.GROOPS_DATA+'model.dat','path':str(alias/'model.dat'),
            'sha256':data.sha256_file(path),'bytes':path.stat().st_size}
    data.write_json(path.with_name(path.name+'.source.json'),record)
    manifest=root/'auxiliary_manifest.json'
    data.write_json(manifest,{'status':'complete','sources':[record]})
    original=manifest.read_bytes()
    checked=data.reuse_auxiliary_manifest(root)
    assert checked['sources'][0]['path']==str(path)
    assert checked['sources'][0]['sha256']==record['sha256']
    assert manifest.read_bytes()==original
