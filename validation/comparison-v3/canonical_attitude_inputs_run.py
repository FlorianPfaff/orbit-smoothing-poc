from pathlib import Path
import sys,os,json,subprocess
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
from orbit_poc.comparison.groops_config import build_day_configs
from orbit_poc.comparison.data import sha256_file,write_json
root=Path('/tmp/orbit-v3-canonical-attitude');root.mkdir(exist_ok=True)
raw=json.loads(Path('work/v3/prepared-utc/2024-04-24/data_manifest.json').read_text())
configured=build_day_configs(raw,'work/v3/native-example/scenarioLeoReducedDynamicOrbit','work/v3/groops-data',root,
 integration_step_seconds=2.5,mask={'intervals_seconds':[],'cadence_seconds':30,'time_scale':'UTC'})
binary=Path('/tmp/orbit-v3-common-preprocessing/groops')
with (root/'convert_receiver.log').open('w') as log:subprocess.run([str(binary),configured['configs']['convert_receiver']],stdout=log,stderr=subprocess.STDOUT,check=True)
coarse=json.loads(Path('/tmp/orbit-v3-utc-final/normal/preparation_manifest.json').read_text())
hashes=[sha256_file(x['native_paths']['attitude']) for x in [coarse,configured]]
report={'passed':hashes[0]==hashes[1], 'scope':'Flight input conversion only; no force integration or orbit fit',
 'date':'2024-04-24','state_grid_steps_seconds':[5,2.5],
 'canonical_attitude_sha256':hashes,'canonical_file_identical_across_state_grids':hashes[0]==hashes[1],
 'synchronized_attitude_sha256':sha256_file(configured['native_paths']['attitude_integration']),
 'native_binary_sha256':sha256_file(binary),'reference_inputs_used':False,
 'physical_attitude_model':'canonical5s samples and native degree7 interpolation; finer-grid dynamics use a synchronized interpolation of those same samples; GNSS/SLR use canonical file',
 'raw_sca_retained':True}
write_json('outputs/orbit-smoothing-poc/validation/comparison-v3/canonical_attitude_inputs.json',report)
print(json.dumps(report,indent=2))
