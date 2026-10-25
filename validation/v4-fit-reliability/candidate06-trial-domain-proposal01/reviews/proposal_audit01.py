"""Independent, bounded archive-only linear algebra; no native calls or refits."""
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import numpy as np

ROOT = Path('/mnt/d/orbit-v41-recovery02/one-hour-run01/cold-density/fit')
POINT = ROOT / 'point-003-closure-refinement'
OUT = Path(__file__).parent / 'proposal-audit01.json'
evidence = []

def read(path, binary=False):
    data = path.read_bytes()
    evidence.append({'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    return data if binary else data.decode()

def matrix(path):
    return np.loadtxt(io.StringIO(read(path)), skiprows=2)

def native(path):
    data = read(path, True)
    shape = struct.unpack('<QQ', data[:16])
    return np.frombuffer(data[16:], dtype='<f8').reshape(shape).copy()

info = json.loads(read(POINT/'qr.74.factor.json'))
cost = json.loads(read(POINT/'qr.74.profile.json'))
diag = json.loads(read(POINT/'qr.74.diagnostics.json'))
R = native(POINT/'qr.74.R.bin')
b = native(POINT/'qr.74.rhs.bin').ravel()
scales = np.array(info['scales'])
dynamic = np.array(info['dynamic'], dtype=bool)
reference = matrix(POINT/'closure-02/reference.txt').ravel()
initial_design = matrix(POINT/'closure-02/initial_design.txt')
physical_initial = matrix(POINT/'physical_initial.txt').ravel()
trial_initial = matrix(ROOT/'point-004-trial-001/physical_initial.txt').ravel()
saved_density = np.loadtxt(io.StringIO(read(ROOT/'point-004-trial-001/native/log_density.txt')))[:,1]
params = list(csv.DictReader(io.StringIO(read(POINT/'qr.74.parameters.tsv')), delimiter='\t'))
retained = [params[i] for i in info['retained_global_indices']]
names = [p['name'] for p in retained]
density_indices = [i for i,p in enumerate(retained) if ':logDensity:' in p['name']]
assert len(density_indices)==61 and sum(dynamic)==67
assert density_indices == list(np.flatnonzero(dynamic)[:61])
row_bytes = read(POINT/'qr.74.rows.tsv.gz', True)
rows = list(csv.DictReader(io.StringIO(gzip.decompress(row_bytes).decode()), delimiter='\t'))
prior_rows = [row for row in rows if row['source']=='constraint.logDensityOu']
assert len(prior_rows)==61 and all(float(row['rhs'])==0 for row in prior_rows)
global_density = [info['retained_global_indices'][i] for i in density_indices]
assert prior_rows[0]['columns'] == str(global_density[0])
assert all(row['columns']==f'{global_density[i-1]},{global_density[i]}' for i,row in enumerate(prior_rows[1:],1))

tau,sigma,dt=7200.,0.3,60.
phi=math.exp(-dt/tau)
innovation_sigma=sigma*math.sqrt(-math.expm1(-2*dt/tau))
J=np.zeros((61,len(b)))
J[0,density_indices[0]]=1/sigma
for i in range(1,61):
    J[i,density_indices[i-1]]=-phi/innovation_sigma
    J[i,density_indices[i]]=1/innovation_sigma
Jscaled=J*scales[None,:]
# This is a diagnostic Gram-matrix check of a tiny archived factor, never a production solve.
prior_subtraction_eigenvalues=np.linalg.eigvalsh(R.T@R-Jscaled.T@Jscaled)
solutions=[]
for damping,folder in [(0.,'proposal-000'),(.001,'proposal-001')]:
    penalty=np.eye(len(b))[dynamic]*math.sqrt(damping)
    A=np.vstack((R,penalty))
    y=np.r_[b,np.zeros(sum(dynamic))]
    z,_,rank,singular=np.linalg.lstsq(A,y,rcond=None)  # independent SVD path
    step=scales*z
    delta=step[dynamic]
    saved=matrix(POINT/folder/'parameters.txt').ravel()-reference
    g=delta[:61]
    prior=.5*((g[0]/sigma)**2+np.sum(((g[1:]-phi*g[:-1])/innovation_sigma)**2))
    prior_matrix=.5*np.linalg.norm(J@step)**2
    predicted=float(b@(R@z)-.5*np.linalg.norm(R@z)**2)
    linear_cost=.5*(np.linalg.norm(R@z-b)**2+info['orthogonal_energy'])
    solutions.append({'damping':damping,'augmented_rank':int(rank),
        'maximum_native_step_discrepancy':float(np.max(np.abs(delta-saved))),
        'relative_native_step_discrepancy':float(np.linalg.norm(delta-saved)/np.linalg.norm(saved)),
        'density_min':float(g.min()),'density_max':float(g.max()),
        'density_update_max':float(np.abs(g).max()),
        'prior_cost_direct':float(prior),'prior_cost_matrix':float(prior_matrix),
        'predicted_reduction':predicted,'predicted_full_linear_cost':float(linear_cost),
        'lm_dynamic_penalty_cost':float(.5*damping*np.linalg.norm(z[dynamic])**2),
        'scaled_dynamic_step_norm':float(np.linalg.norm(z[dynamic])),
        'scaled_least_squares_relative_stationarity':float(np.linalg.norm(A.T@(A@z-y))/max(1.,np.linalg.norm(A.T@y)))})
    if damping:
        density_match=float(np.max(np.abs(g-saved_density)))
        initial_match=float(np.max(np.abs(physical_initial+initial_design@delta-trial_initial)))

checks={
    'same_density_parameter_order':True,
    'one_initial_and_sixty_transition_prior_rows':True,
    'zero_prior_targets_at_zero_initial_density':True,
    'independent_augmented_svd_matches_saved_steps':all(v['relative_native_step_discrepancy']<1e-10 for v in solutions),
    'full_augmented_rank':all(v['augmented_rank']==146 for v in solutions),
    'trial_density_matches_damped_proposal':density_match<1e-10,
    'trial_physical_initial_matches_native_design':initial_match<1e-8,
    'ou_analytic_and_matrix_cost_agree':all(abs(v['prior_cost_direct']-v['prior_cost_matrix'])<1e-8 for v in solutions),
    'ou_scaled_precision_not_greater_than_full_factor':float(prior_subtraction_eigenvalues.min())>-1e-10,
}
result={'schema':'independent-density-proposal-audit-v1','scope':'Archived 146-column linearization only; no nonlinear or native execution',
 'approved':all(checks.values()),'checks':checks,'solutions':solutions,
 'accepted_point_objective':cost['direct_cost'],'rank_diagnostics':diag,
 'ou':{'tau_seconds':tau,'sigma':sigma,'dt_seconds':dt,'phi':phi,'innovation_sigma':innovation_sigma},
 'trial_density_max_discrepancy':density_match,'trial_initial_max_discrepancy':initial_match,
 'small_gram_prior_subtraction_minimum_eigenvalue':float(prior_subtraction_eigenvalues.min()),
 'density_column_scales_min_max':[float(scales[density_indices].min()),float(scales[density_indices].max())],
 'evidence':evidence,
 'limitations':['Row provenance names and source equations checked; full observation row coefficient spool is not reconstructed.',
 'A correct damped linear solution does not establish a valid nonlinear trial or explain the exact fitted nonfinite element.',
 'No scientific parameter, clipping, damping setting, threshold, source or archived output changed.']}
OUT.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='evidence'},indent=2))
