"""Real inherited-environment checks with exec intercepted; no native process."""
from pathlib import Path
import importlib.util
import os
import sys
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/nuisance_profile_launch.py'
spec=importlib.util.spec_from_file_location('guard_test',SCRIPT);guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)

@pytest.fixture
def binding(tmp_path,monkeypatch):
    root=tmp_path;native=root/'native';native.write_text('never executed')
    pulse=root/'pulse.txt';pulse.write_text('fixed pulse reference')
    config=root/'config.xml';config.write_text('<groops><orbitPocNumerics><outputfilePrefix>'+str(root/'qr')+
        '</outputfilePrefix><inputfilePulseReference>'+str(pulse)+'</inputfilePulseReference></orbitPocNumerics></groops>')
    frozen=root/'freeze.json';guard.save(frozen,{'fixture':'isolated'})
    env={**{key:'1' for key in guard.THREADS},**guard.scientific_controls(config,root),
         'ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS':'1','ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE':'0',
         'ORBIT_POC_NUISANCE_WARM_STARTS':'0'}
    for key in list(os.environ):
        if key.startswith(('ORBIT_POC_','LD_')):monkeypatch.delenv(key)
    for key,value in env.items():monkeypatch.setenv(key,value)
    value={'schema':'orbit-poc-nuisance-profile-launch-binding-v1','mode':guard.MODE,'root':str(root),'cpu':0,
           'freeze':guard.pin(frozen),'native':guard.pin(native),'config':guard.pin(config),'guard':guard.pin(SCRIPT),'environment':env,'job_id':'fixture'}
    path=root/'launch-binding.json';guard.save(path,value);pinned=guard.pin(path)
    monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--binding',str(path),'--binding-sha256',pinned['sha256']])
    monkeypatch.setattr(guard.os,'sched_getaffinity',lambda _: {0})
    calls=[]
    class Intercepted(Exception):pass
    def intercept(*args):calls.append(args);raise Intercepted()
    monkeypatch.setattr(guard.os,'execve',intercept)
    return root,value,calls,Intercepted

def test_guard_records_actual_environment_then_execs_exact_native_with_same_environment(binding):
    root,value,calls,intercepted=binding
    with pytest.raises(intercepted):guard.main()
    receipt=guard.read(root/'native-launch.json')
    assert receipt['environment']==value['environment']
    assert calls[0][:2]==(value['native']['path'],[value['native']['path'],value['config']['path']])
    assert all(calls[0][2][key]==v for key,v in receipt['environment'].items())
    assert receipt['pid']==os.getpid() and 'release_authority' not in receipt

@pytest.mark.parametrize('key',['QR_PREFIX','SOLVER','MODE','LAMBDA','PULSE_REFERENCE'])
@pytest.mark.parametrize('mutation',['missing','wrong'])
def test_guard_rejects_actual_missing_or_wrong_controls_before_native(binding,monkeypatch,key,mutation):
    root,_,calls,_=binding;key='ORBIT_POC_NUMERICS_'+key
    if mutation=='missing':monkeypatch.delenv(key)
    else:monkeypatch.setenv(key,'wrong')
    with pytest.raises(ValueError,match='actual launch override'):guard.main()
    assert calls==[] and not (root/'native-launch.json').exists()

def test_density_xml_forbids_ambient_pulse_reference(binding):
    root,value,_,_=binding
    config=root/'density.xml';config.write_text('<groops><orbitPocNumerics><outputfilePrefix>'+str(root/'qr')+'</outputfilePrefix></orbitPocNumerics></groops>')
    with pytest.raises(ValueError,match='PULSE_REFERENCE'):guard.validate_environment(value['environment'],config,root)

def test_pilot_xml_transform_retains_same_scientific_variant(tmp_path):
    pilotpath=SCRIPT.parents[1]/'pilot_prior_fixture05.py'
    spec=importlib.util.spec_from_file_location('pilot05',pilotpath);pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
    original='<groops><parametrization><codeBiases><name>parameter.codeBiases</name><sigmaZeroMeanConstraint>1</sigmaZeroMeanConstraint></codeBiases></parametrization><parametrization><tecBiases><name>parameter.tecBiases</name><sigmaZeroMeanConstraint>1</sigmaZeroMeanConstraint></tecBiases></parametrization><outputfilePrefix>/old/qr</outputfilePrefix></groops>'
    transformed=pilot.transform(original,'/old',str(tmp_path))
    addition='\n          <selectTransmitters><all /></selectTransmitters>'
    assert transformed.count(addition)==2
    assert transformed.replace(addition,'').replace(str(tmp_path)+'/','/old/')==original
    assert pilot.OUT.name=='prior-fixture-pilot05' and pilot.R.name=='source-candidate05'


def load_pilot():
    spec=importlib.util.spec_from_file_location('pilot_regression',SCRIPT.parents[1]/'pilot_prior_fixture05.py')
    pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot);return pilot


def test_pilot_environment_matches_xml_and_preserves_disabled_treatment(binding):
    root,value,_,_=binding;pilot=load_pilot();old={k:v for k,v in value['environment'].items()
        if k not in guard.scientific_controls(root/'config.xml',root)}
    old['LD_LIBRARY_PATH']='/pinned/runtime'
    env=pilot.pilot_environment(old,root/'config.xml',root,{'runtime_environment':{'LD_LIBRARY_PATH':'/pinned/runtime'}})
    assert all(env[key]==v for key,v in guard.scientific_controls(root/'config.xml',root).items())
    assert env['ORBIT_POC_NUISANCE_WARM_STARTS']=='0' and old.get('ORBIT_POC_NUMERICS_QR_PREFIX') is None


@pytest.mark.parametrize('mutation',['valid','missing_datum','legacy_without_preinit_evidence','floor_limited','missing_code_prior'])
def test_pilot_extraction_requires_actual_datum_and_unchanged_strict_gates(tmp_path,mutation):
    spec=importlib.util.spec_from_file_location('profile_fixture_for_pilot',Path(__file__).with_name('test_nuisance_warm_profiles.py'))
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    f=fixtures.Fixture(tmp_path);root=f.runs['disabled'];pilot=load_pilot()
    if mutation in ('missing_datum','legacy_without_preinit_evidence'):
        for path in root.glob('qr.datum.*'):path.unlink()
        if mutation=='legacy_without_preinit_evidence':(root/'native-launch.json').unlink();(root/'launch-binding.json').unlink()
    elif mutation=='floor_limited':
        fixtures.change(root/'qr.profile.json',lambda v:v.update(nuisance_floor_limited=True))
    elif mutation=='missing_code_prior':
        path=root/'qr.3.rows.tsv';path.write_text(path.read_text().replace('code_bias_full_constraint','different_source'))
    result=pilot.extract(root,fixtures.check)
    assert result['passed'] is (mutation=='valid') and not result['release_authority'] and not result['covariance_authority']
    if mutation=='valid':
        assert set(result['native_prior_rows'])=={'code_bias_full_constraint','tec_bias_full_constraint'}
        assert all(r['rows']>0 and r['rhs_squared']>0 for r in result['native_prior_rows'].values())
        assert len(result['datum_evidence'])==2 and all(r['rows'] and r['columns'] for r in result['datum_evidence'])
