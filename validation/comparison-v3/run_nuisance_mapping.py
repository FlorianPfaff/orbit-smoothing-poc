"""Noiseless native-model nuisance mapping; not the independent truth benchmark.

Use an existing diagnostic pulse fit as a force/template source and its synthetic
observation-generation manifest. Generates a fresh canonical native trajectory,
full-cycle ambiguities, injected slips and random clocks; fits both models with
finite fixed weights and independently reprocesses normal/masked observations.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,xml.etree.ElementTree as ET,shutil,subprocess,os
from orbit_poc.comparison.data import artifact,write_json,sha256_file
from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import source_snapshot
from orbit_poc.comparison.groops_config import build_day_configs
from orbit_poc.comparison.synthetic import configure_synthetic_forces,receiver_to_gps1b


def run(args):
    root=args.output.resolve()
    if root.exists():raise ValueError('Choose a new immutable output directory')
    root.mkdir(parents=True)
    binary=root/'groops';shutil.copy2(args.groops,binary)
    source=args.template_native_fit.resolve();old_manifest=args.generation_manifest.resolve()
    manifest=json.loads(old_manifest.read_text());date=manifest['date'];case=manifest['case']
    duration=float(case['duration_hours'])*3600;epoch=int(__import__('datetime').datetime.fromisoformat(date).toordinal()-678576)
    generation=root/'generation';generation.mkdir()
    def native(config,label,env=None):
        path=generation/f'{label}.xml';config.write(path)
        with (generation/f'{label}.log').open('w') as log:
            subprocess.run([str(binary),str(path)],stdout=log,stderr=subprocess.STDOUT,check=True,
                env={**os.environ,'OPENBLAS_NUM_THREADS':'1',**(env or {})})
    var=ET.parse(source/'variational.xml');initial=var.find('.//PreprocessingVariationalEquation')
    if initial.find('forces/miscAccelerations/syntheticDrag') is None or initial.find('.//logDensity') is not None:
        raise ValueError('Requires controlled nominal synthetic pulse force template')
    def resolved(tag):return initial.find(tag).text.replace('{loopTime:%D}',date)
    canonical=ET.Element('groops')
    for kind,original,degree in [('orbit',resolved('inputfileOrbit'),7),('attitude',resolved('inputfileStarCamera'),1)]:
        p=ET.SubElement(ET.SubElement(canonical,'program'),'InstrumentResample')
        ET.SubElement(p,'outputfileInstrument').text=str(generation/f'known_{kind}.dat')
        ET.SubElement(p,'inputfileInstrument').text=original
        method=ET.SubElement(ET.SubElement(p,'method'),'polynomial')
        for tag,value in [('polynomialDegree',degree),('maxDataPointRange',300),('maxExtrapolationDistance',1)]:ET.SubElement(method,tag).text=str(value)
        grid=ET.SubElement(ET.SubElement(p,'timeSeries'),'uniformSampling')
        for tag,value in [('timeStart',epoch),('timeEnd',f'{epoch}+({duration}-2.5)/86400'),('sampling','5/86400')]:ET.SubElement(grid,tag).text=str(value)
    native(ET.ElementTree(canonical),'canonical_truth_inputs')
    for parent in var.iter():
        for child in list(parent):
            if child.tag=='program' and (child.find('PreprocessingVariationalEquationOrbitFit') is not None or child.find('FileCreateDirectories') is not None):parent.remove(child)
    initial.find('inputfileOrbit').text=str(generation/'known_orbit.dat')
    initial.find('inputfileStarCamera').text=str(generation/'known_attitude.dat')
    initial.find('outputfileVariational').text=str(generation/'truth_variational.dat')
    ET.SubElement(initial,'outputfileOrbit').text=str(generation/'simulation_orbit.dat')
    native(var,'nominal_truth')
    old=old_manifest.parent/'generation';tree=ET.parse(old/'simulate_receiver.xml')
    for node in tree.iter():
        if node.text and str(old) in node.text and '/data/' not in node.text:
            node.text=node.text.replace(str(old),str(generation))
    shutil.copy2(old/'synthetic_accuracy.xml',generation/'synthetic_accuracy.xml')
    recv=tree.find('.//receiver/lowEarthOrbiter')
    recv.find('inputfileOrbit').text=str(generation/'simulation_orbit.dat')
    recv.find('inputfileStarCamera').text=str(generation/'known_attitude.dat')
    recv.find('wavelengthFactor').text='1'
    tree.find('.//noiseObservation/white/sigma').text='0'
    (generation/'output'/date).mkdir(parents=True)
    native(tree,'simulate_receiver',{'ORBIT_POC_SIMULATION_SEED':str(case['seed']),
           'ORBIT_POC_SIMULATION_AMBIGUITIES':str(generation/'ambiguity_truth.txt')})
    if not (generation/'receiver_unmasked.txt').is_file():raise RuntimeError('Native simulator produced no observations')
    gps=generation/'GPS1B_mapping.txt';export=receiver_to_gps1b(generation/'receiver_unmasked.txt',gps,seed=case['seed'],mjd_start=epoch,slips=True)
    manifest['estimation_inputs']=[r for r in manifest['estimation_inputs'] if r['role'] not in ['gnss_observations','attitude']]
    manifest['estimation_inputs'] += [artifact(gps,'gnss_observations'),artifact(generation/'known_attitude.dat','attitude',format='groops_instrument')]
    manifest['evaluation_inputs']=[]
    manifest['native_simulation']['export']=export
    manifest['diagnostic_purpose']='Native matched-model/noiseless nuisance mapping only'
    manifest['diagnostic_noise']={'observation_multiplier':0,'fit_code_sigma_m':.3,'fit_phase_sigma_m':.003,'ambiguity_cycles':'full integer','fit_wavelength_factor':.5}
    write_json(root/'data_manifest.json',manifest)
    native_config={'groops_executable':str(binary),'example_directory':str(args.example_directory.resolve()),
                  'auxiliary_dir':str(args.auxiliary_dir.resolve()),'cache_dir':str(root/'cache'),
                  'retain_native_diagnostics':True}
    results=[]
    for label,intervals in [('normal',[]),('masked',[[duration/3,duration/2]])]:
        current={**case,'mask':{'intervals_seconds':intervals,'cadence_seconds':30,'time_scale':'elapsed'},'coverage':'blackout' if intervals else 'normal'}
        prep=build_day_configs(manifest,args.example_directory,args.auxiliary_dir,root/label/'prepared',mask=current['mask'],duration_hours=case['duration_hours'])
        prep=configure_synthetic_forces(prep,current,native_config)
        if label=='normal':backend.run_native(str(binary),prep['configs']['convert_gnss'],prep['output_dir'],'convert_gnss')
        else:
            for name in ['orbit','clock','attitude','signalBias']:
                target=Path(prep['output_dir'])/'data'/date/name
                if not target.exists():target.symlink_to(root/'normal/prepared/data'/date/name,target_is_directory=True)
        backend.run_native(str(binary),prep['configs']['convert_receiver'],prep['output_dir'],'convert_receiver')
        backend._verify_transmitters(prep)
        blind=root/label/'native_preparation.json';write_json(blind,backend._blind_record(prep))
        methods={'groops_pulses':{'interval_seconds':1200.,'sigma_velocity_m_s':1e-4},'groops_log_drag_ou':{'knot_seconds':60.,'tau_seconds':7200.,'sigma_log_density':.3,'interpolation':'linear_log_density','initial_prior':'stationary_ou','empirical_acceleration':False}}
        for method,parameters in methods.items():
            record=artifact(blind,'force_auxiliary');record['metadata']={'kind':'native_preparation'}
            job={'source_hash':source_snapshot()['sha256'],'stage':'synthetic','case':current,'backend':native_config,'method':method,'parameters':parameters,
                 'estimation_inputs':[*prep['estimation_inputs'],record],**{k:prep[k] for k in ['force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash']}}
            fitdir=root/label/method;write_json(fitdir/'request.json',job)
            result=backend.fit_job(job,fitdir);write_json(fitdir/'result.json',result)
            results.append({'case':label,'method':method,'status':result['status'],'converged':result.get('converged'),'error':result.get('error')})
            write_json(root/'results.json',{'results':results,'binary_sha256':sha256_file(binary)});print(results[-1],flush=True)
    if not all(r['converged'] for r in results):raise RuntimeError('One or more nuisance mapping fits failed')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ['template-native-fit','generation-manifest','groops','example-directory','auxiliary-dir','output']:
        parser.add_argument('--'+flag,type=Path,required=True)
    run(parser.parse_args())
