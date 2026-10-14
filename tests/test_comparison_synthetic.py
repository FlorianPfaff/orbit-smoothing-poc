from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.synthetic import (SIGNALS, read_receiver_ascii,
    receiver_to_gps1b, simulation_configs, write_truth_instruments)
from orbit_poc.comparison.data import read_gps1b_code, split_gps1b


def receiver_file(path, rows=5):
    with path.open('w') as out:
        out.write('groops instrument version=20200123\n-11 1\n'+str(rows)+'\n')
        for i in range(rows):
            time = np.longdouble(60440)+np.longdouble(i*30)/86400
            out.write(np.format_float_positional(time,precision=18)+'\n6\n'+'\n'.join(SIGNALS)+'\n1\n***G03\n6\n')
            out.write('\n'.join(str(20000000+j) for j in range(6))+'\n0.00001\n')
    return path


def test_receiver_export_preserves_code_and_metre_phase(tmp_path):
    source = receiver_file(tmp_path/'receiver.txt')
    epochs = read_receiver_ascii(source)
    assert len(epochs) == 5 and epochs[0]['observations'].shape == (1, 6)
    target = tmp_path/'GPS1B.txt'
    result = receiver_to_gps1b(source,target,seed=17,mjd_start=60440,slips=False)
    assert result['records'] == 5 and not result['receiver_clock_exported']
    assert target.read_text().splitlines()[1] == '    num_records: 5'  # native FileInGrace fixed indentation
    rows = target.read_text().split('# End of YAML header\n')[1].splitlines()
    assert list(map(float, rows[0].split()[7:])) == list(range(20000000,20000006))
    assert len(read_gps1b_code(target)) == 5


def test_slips_are_reproducible_and_do_not_modify_code(tmp_path):
    source = receiver_file(tmp_path/'receiver.txt')
    targets = [tmp_path/f'GPS1B-{i}.txt' for i in range(3)]
    outputs = [receiver_to_gps1b(source,path,seed=15 if i<2 else 16,mjd_start=60440) for i,path in enumerate(targets)]
    assert targets[0].read_bytes() == targets[1].read_bytes()
    assert targets[0].read_bytes() != targets[2].read_bytes()
    assert read_gps1b_code(targets[0]) == read_gps1b_code(targets[2])
    assert outputs[0]['slips'] == outputs[1]['slips']


def test_masking_is_after_generation_and_before_bootstrap(tmp_path):
    source = receiver_file(tmp_path/'receiver.txt')
    target = tmp_path/'GPS1B.txt'
    receiver_to_gps1b(source,target,seed=17,mjd_start=60440)
    normal = split_gps1b(target,'2024-05-10',tmp_path/'normal',{'time_scale':'elapsed'})
    masked = split_gps1b(target,'2024-05-10',tmp_path/'masked',{'time_scale':'elapsed','intervals_seconds':[[30,90]]})
    a,b = read_gps1b_code(normal['retained']['path']),read_gps1b_code(masked['retained']['path'])
    assert len(a)==5 and len(b)==3
    assert all(a[k]==v for k,v in b.items())


def test_invalid_native_receiver_rejected(tmp_path):
    source = receiver_file(tmp_path/'receiver.txt')
    source.write_text(source.read_text().replace('***G03','***R03'))
    with pytest.raises(ValueError,match='GPS only'):
        read_receiver_ascii(source)


def test_native_truth_export_attitude_is_unit_and_nadir(tmp_path):
    times = np.arange(0.,121.,10.)
    angle = times*.001
    radius = 6878137.
    states = np.c_[radius*np.cos(angle),radius*np.sin(angle),np.zeros(len(times)),
                   -.001*radius*np.sin(angle),.001*radius*np.cos(angle),np.zeros(len(times))]
    np.savez(tmp_path/'truth.npz',times=times,states=states)
    out=write_truth_instruments(tmp_path/'truth.npz',tmp_path/'native','2024-05-10T00:00:00')
    rows=np.loadtxt(out['attitude'],skiprows=3)
    assert np.allclose(np.linalg.norm(rows[:,1:],axis=1),1)
    from scipy.spatial.transform import Rotation
    frames=Rotation.from_quat(rows[:,1:],scalar_first=True).as_matrix()
    assert np.allclose(frames[:,:,2],-states[:,:3]/radius)
    orbit=np.loadtxt(out['orbit'],skiprows=3)
    assert np.allclose(orbit[:,1:7],states)


def test_native_simulation_uses_shared_corrections_and_seeded_noise(tmp_path):
    project=Path(__file__).resolve().parents[1]
    case={'epoch':'2024-05-10T00:00:00','duration_hours':1,'cadence':30,'seed':300001}
    instruments={'mjd_start':60440,'orbit':'/simulation/orbit.txt','attitude':'/known/attitude.txt'}
    products=[{'role':role,'path':'/'+role} for role in ('gnss_orbits','gnss_clocks','gnss_biases','gnss_attitudes')]
    out=simulation_configs(case,instruments,products,tmp_path,{'example_directory':str(project/'groops/templates'),'auxiliary_dir':str(tmp_path/'aux')})
    node=ET.parse(out['simulate']).find('.//GnssSimulateReceiver')
    assert node is not None and not node.findall('processingStep')
    assert node.find('parametrization/leoDynamicOrbits') is None
    assert node.find('parametrization/signalBiases') is not None
    assert node.find('receiver/lowEarthOrbiter/inputfileObservations') is None
    assert node.findtext('receiver/lowEarthOrbiter/inputfileOrbit') == instruments['orbit']
    assert node.findtext('receiver/lowEarthOrbiter/wavelengthFactor') == '1'
    assert node.findtext('noiseObservation/white/initRandom') == str(case['seed']+17011)
    assert [x.text for x in node.findall('observationType')] == list(SIGNALS)
    accuracy=ET.parse(node.findtext('receiver/lowEarthOrbiter/inputfileAccuracyDefinition'))
    for cell in accuracy.findall('.//antenna/pattern/cell'):
        sigma=.3 if cell.findtext('type').startswith('C') else .003
        assert {float(value.text) for value in cell.findall('pattern/cell')}=={sigma}


def test_generation_compaction_preserves_scientific_inputs_and_audits_duplicates(tmp_path):
    from orbit_poc.comparison.synthetic import compact_generation
    retained = tmp_path/'evaluation.npz'; retained.write_bytes(b'evaluation')
    duplicate = tmp_path/'duplicate.npz'; duplicate.write_bytes(b'duplicate')
    link = tmp_path/'cached-link'; link.symlink_to(retained)
    audit = compact_generation(tmp_path, [duplicate, link], [retained])
    assert len(audit) == 1 and audit[0]['bytes'] == 9 and len(audit[0]['sha256']) == 64
    assert retained.read_bytes() == b'evaluation' and link.is_symlink() and not duplicate.exists()
    with pytest.raises(ValueError, match='cannot be pruned'):
        compact_generation(tmp_path, [retained], [retained])
    with pytest.raises(ValueError, match='must precede'):
        compact_generation(tmp_path, [], [tmp_path/'missing'])


def test_controlled_force_override_is_common_across_methods(tmp_path):
    from orbit_poc.comparison.synthetic import configure_synthetic_forces
    def configured(method):
        directory=tmp_path/method;directory.mkdir()
        variational=directory/'variational.xml';estimate=directory/'estimate.xml'
        density = '<logDensity><nominalDrag><atmosphericDrag/></nominalDrag><inputfileLogDensity>g.txt</inputfileLogDensity><orbitPocAtmosphereEvents>1</orbitPocAtmosphereEvents></logDensity>'
        drag=density if method=='density' else '<atmosphericDrag/>'
        variational.write_text('<groops><PreprocessingVariationalEquation><forces><gravityfield/><miscAccelerations>'+drag+'</miscAccelerations><tides/></forces><orbitPocAtmosphericForce>'+drag+'</orbitPocAtmosphericForce><orbitPocAtmosphericHasDensityKnots>1</orbitPocAtmosphericHasDensityKnots><orbitPocAtmosphericQuadratureStep>1</orbitPocAtmosphericQuadratureStep><gradientfield><potentialCoefficients><maxDegree>10</maxDegree></potentialCoefficients></gradientfield></PreprocessingVariationalEquation></groops>')
        estimate.write_text('<groops><parametrizationAcceleration>'+ (density if method=='density' else '')+'</parametrizationAcceleration></groops>')
        return {'output_dir':str(directory),'configs':{'variational':str(variational),'estimate':str(estimate)}}
    pulse=configure_synthetic_forces(configured('pulse'),{})
    density=configure_synthetic_forces(configured('density'),{})
    assert pulse['force_model_hash']==density['force_model_hash']
    p=ET.parse(pulse['configs']['variational'])
    d=ET.parse(density['configs']['variational'])
    assert p.find('.//forces/gravityfield') is None and p.find('.//forces/tides') is None
    assert p.find('.//forces/miscAccelerations/syntheticGravity') is not None
    assert d.find('.//forces/miscAccelerations/logDensity/nominalDrag/syntheticDrag') is not None
    assert ET.parse(density['configs']['estimate']).find('.//nominalDrag/syntheticDrag') is not None
    for configured in (pulse,density):
        for path in configured['configs'].values():
            tree=ET.parse(path)
            assert tree.find('.//orbitPocAtmosphericForce') is None
            assert tree.find('.//orbitPocAtmosphereEvents') is None
            assert tree.find('.//orbitPocAtmosphericHasDensityKnots') is None
            assert tree.find('.//orbitPocAtmosphericQuadratureStep') is None


def test_secondary_force_specification_is_seeded_and_predeclared():
    from orbit_poc.comparison.synthetic import mixed_force_specification
    first=mixed_force_specification(500001)
    assert first==mixed_force_specification(500001)
    assert first['radial_phase']!=mixed_force_specification(500002)['radial_phase']
    assert first['radial_amplitude_m_s2']==first['normal_amplitude_m_s2']==2e-8
    assert first['radial_period_seconds']==7200 and first['normal_period_seconds']==5400
