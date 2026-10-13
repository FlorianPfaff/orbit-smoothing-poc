"""Native UTC heldout receiver geometry/support smoke, without accuracy claims."""
from pathlib import Path
import json, os, sys, time
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
from orbit_poc.comparison.groops_config import build_prediction_config
from orbit_poc.comparison.backend import run_native, read_native_table
from orbit_poc.comparison.protocol import read_json, write_json, file_hash
root=Path('/tmp/orbit-v3-utc-receiver-epoch-check')
binary=root/'groops-final';out=root/'blackout'
deadline=time.monotonic()+1800
while not (out/'one_iteration_covariance.execution.json').exists():
    if time.monotonic()>deadline:raise TimeoutError('covariance execution incomplete')
    time.sleep(5)
assert read_json(out/'one_iteration_covariance.execution.json')['returncode']==0
config=read_json(out/'configured.json')
configured=build_prediction_config(out/'one_iteration_covariance.xml',config['result_paths']['orbit_native'],
    config['calibration_inputs'],out/'heldout-geometry-check')
execution=[]
for key in ('convert_holdout','predict'):
    execution.append(run_native(binary,configured['configs'][key],out/'heldout-geometry-check',key))
values=read_native_table(configured['predictions'],8)
support=Path(configured['predictive_support']).read_text().splitlines()
rows=[s for s in support if s and not s.startswith('#')]
covariance=read_native_table(out/'output/2024-04-24/state_covariance_observations.txt',37)
import numpy as np
offsets=[]
for mjd in np.unique(values[:,0]):offsets.append(float(np.min(abs(covariance[:,0]-mjd))*86400))
report={'scope':'Functional UTC heldout geometry/support check after one estimate iteration; no accuracy or calibration claim',
    'native_binary_sha256':file_hash(binary),'predictions':len(values),'prediction_epochs':len(np.unique(values[:,0])),
    'support_rows':len(rows),'prediction_support_sha256':file_hash(configured['predictive_support']),
    'maximum_nearest_covariance_epoch_error_seconds':max(offsets),
    'all_measurement_variances_positive':bool(np.all(values[:,3]>0)),
    'reference_or_slr_evaluation':False,'native_execution':execution}
report['passed']=len(values)>0 and len(values)==len(rows) and max(offsets)<.001 and report['all_measurement_variances_positive']
write_json(root/'prediction_geometry_validation.json',report)
print(json.dumps(report,sort_keys=True),flush=True)
