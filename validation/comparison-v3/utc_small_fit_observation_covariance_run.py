"""Small UTC flight pulse fit for independent covariance engineering validation."""
from pathlib import Path
from copy import deepcopy
import importlib.util, json, os, shutil, sys
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[-2:])
project=Path('outputs/orbit-smoothing-poc').resolve();sys.path.insert(0,str(project/'src'))
from orbit_poc.comparison import backend, data, groops_config
from orbit_poc.comparison.protocol import artifact_record, read_json, write_json, file_hash, source_snapshot

root=Path('/tmp/orbit-v3-small-utc-covariance').resolve();root.mkdir(exist_ok=True)
binary=root/'groops';shutil.copy2('/tmp/orbit-v3-utc-receiver-epoch-check/groops-final',binary)
assert file_hash(binary)=='74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453'
manifest_path=Path('work/v3/prepared-utc/2024-04-24/data_manifest.json').resolve()
raw=read_json(manifest_path)
source_arc=deepcopy(raw['arc']);arc=deepcopy(source_arc)
arc.update(utc_end='2024-04-24T01:00:00Z',duration_seconds=3600,
           end_gps_seconds_since_j2000=arc['start_gps_seconds_since_j2000']+3600)
start,end=arc['start_gps_seconds_since_j2000'],arc['end_gps_seconds_since_j2000']
selected=[];crop_records=[]
for item in raw['estimation_inputs']:
    product=item.get('product')
    if product not in ('GPS1B','SCA1B','THR1B','MAS1B'):
        selected.append(item);continue
    header,lines=data._gps1b_text(item['path']);rows=[]
    for line in lines:
        values=line.split();t=data._row_gps_seconds(values,product)
        overlap=product=='THR1B' and t<start and t+max(map(float,values[18:32]),default=0.)/1000>=start
        if start<=t<end or (product=='SCA1B' and t==end) or overlap:rows.append(line)
    path=data._write_l1b(root/'raw-one-hour'/Path(item['path']).name,header,rows,product)
    selected.append(data.artifact(path,item['role'],product=product,mission='GRACE-FO-1',arc=arc,
        records=len(rows),source_inputs=[{'path':item['path'],'sha256':item['sha256']}],reference_inputs_used=False))
    crop_records.append({'product':product,'source_sha256':item['sha256'],'cropped_sha256':file_hash(path),
                         'records':len(rows),'endpoint_retained':product=='SCA1B'})
cropped={'status':'observations_ready','date':'2024-04-24','mission':'GRACE-FO-1',
         'arc':arc,'estimation_inputs':selected,'evaluation_inputs':[],
         'diagnostic_crop':{'source_manifest_sha256':file_hash(manifest_path),'source_arc':source_arc,
                            'selection_arc':arc,'production_inputs_modified':False,'products':crop_records}}
write_json(root/'cropped_data_manifest.json',cropped)
configured=groops_config.build_day_configs(cropped,'work/v3/native-example/scenarioLeoReducedDynamicOrbit',
    'work/v3/groops-data',root/'prepared',duration_hours=1,
    mask={'intervals_seconds':[],'cadence_seconds':30,'time_scale':'UTC'})
previous=Path('/tmp/orbit-v3-utc-final/normal/data/2024-04-24')
for directory in ('orbit','attitude','clock','signalBias'):
    target=root/'prepared/data/2024-04-24'/directory
    target.symlink_to(previous/directory,target_is_directory=True)
execution=backend.run_native(binary,configured['configs']['convert_receiver'],root/'prepared','convert_receiver')
backend._verify_transmitters(configured)
blind=backend._blind_record(configured);blind_path=root/'native_preparation.json';write_json(blind_path,blind)
estimation=[*configured['estimation_inputs'],artifact_record('force_auxiliary',blind_path,metadata={'kind':'native_preparation'})]
job={'stage':'flight','split':'engineering','case':{'date':'2024-04-24','duration_hours':1.,'coverage':'normal',
     'mask':{'intervals_seconds':[],'cadence_seconds':30,'time_scale':'UTC'}},
     'backend':{'groops_executable':str(binary),'retain_native_diagnostics':True,'command_timeout_seconds':3600.},
     'expected_native_binary_sha256':file_hash(binary),'source_hash':source_snapshot()['sha256'],
     'method':'groops_pulses','parameters':{'interval_seconds':1200.,'sigma_velocity_m_s':1e-4},
     'estimation_inputs':estimation,
     **{key:configured[key] for key in ('force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash')}}
folder=root/'fit';write_json(folder/'request.json',job)
print('Prepared one-hour UTC diagnostic, no evaluation inputs',flush=True)
result=backend.fit_job(job,folder);write_json(folder/'result.json',result)
print('Fit status',result.get('status'),'converged',result.get('converged'),'covariance',result.get('covariance_valid'),flush=True)
if result.get('converged') and result.get('covariance_valid'):
    spec=importlib.util.spec_from_file_location('covariance_gate',project/'scripts/check_observation_covariance.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=module.check(binary,folder,root/'basis-check')
    print('Independent covariance check',report['passed'],report['maximum_normalized_covariance_error'],flush=True)
else:
    raise RuntimeError('Small diagnostic fit did not converge; preserve the actual failure and do not claim a covariance gate')
