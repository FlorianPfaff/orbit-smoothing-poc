from pathlib import Path
import json,hashlib,datetime,xml.etree.ElementTree as ET,re,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');V=B/'validation-04';R=V/'run';K='753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769';D=R/'preparation/prefixes'/K;I=D/'nominal-initialization'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
x=read(I/'initialization.json');assert pin(I/'initialization.json')['sha256']=='3a60d773639c1ba263acbe3736becc623198e24e3e9f7e10f814107e47b7b3f8'
assert x['status']=='failed' and not x['converged'] and x['iterations']==[] and x['maximum_iterations']==10 and x['position_tolerance_m']==2e-6 and x['velocity_tolerance_m_s']==3e-9
assert len(x['executions'])==2 and [a['returncode'] for a in x['executions']]==[0,1]
for a in x['executions']:
 assert a['native_binary_sha256']==x['native_binary_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22' and a['timed_out'] is False and a['blas_openmp_threads']==1
 assert pin(a['command'][1])['sha256']==a['config_sha256']
assert pin(I/'input_bootstrap.dat')['sha256']==x['initial_bootstrap_orbit_sha256']==x['bootstrap_snapshot']['sha256']
paths={'receiver':'gnssReceiver','attitude':'starCamera','receiver_orbit':'receiverOrbit','receiver_attitude':'receiverStarCamera','preprocessing_orbit':'receiverOrbit'}
immutable={}
for k,n in paths.items():
 p=D/'native-prepared/data/2024-05-10/gracefo'/f'gracefo1_{n}_2024-05-10.dat';a=pin(p);assert a['sha256']==x['immutable_input_sha256'][k];immutable[k]=a
orbit=D/'native-prepared/data/2024-05-10/gracefo/gracefo1_orbit_2024-05-10.dat';assert pin(orbit)['sha256']==x['initial_bootstrap_orbit_sha256']
initial_values=[float(line) for line in (I/'initial_state.txt').read_text().splitlines()[2:] if line.strip()];assert initial_values==x['fixed_initial_state_si']
first=None;last=None;count=0
with (I/'initial/nominal.txt').open() as f:
 for line in f:
  try:values=[float(t.replace('D','E').replace('d','e')) for t in line.split('#',1)[0].split()]
  except ValueError:continue
  if len(values) not in (7,10):continue
  if first is None:first=values
  if last is not None:assert values[0]>last[0]
  last=values;count+=1
assert first[1:7]==initial_values and count==x['state_epochs']==51840
assert pin(I/'initial/nominal.txt')['sha256']=='2461bb399213603b9d4ac8fef142fe301925566435e9f8a1c1ed2c650c70efe0'
trees=[ET.parse(I/'initial/initialize.xml'),ET.parse(I/'iteration-01/propagate.xml')]
profiles=[]
for t in trees:
 node=t.find('.//PreprocessingVariationalEquation');assert node.findtext('orbitPocDerivativeProfile')=='synthetic_complete_v1';profiles.append(node.findtext('orbitPocDerivativeProfile'))
 assert node.find('forces/miscAccelerations/logDensity') is None
 assert node.find('forces/miscAccelerations/syntheticGravity') is not None and node.find('forces/miscAccelerations/syntheticDrag') is not None
initial_fit=trees[0].find('.//PreprocessingVariationalEquationOrbitFit');assert initial_fit.find('parametrizationAcceleration') is None and initial_fit.find('stochasticPulse') is None
assert trees[1].findtext('.//OrbitPocEvaluateVariational/inputfileInitialState')==str(I/'initial_state.txt')
assert trees[1].findtext('.//PreprocessingVariationalEquation/inputfileOrbit')==str(I/'initial/nominal.dat')
assert not (I/'iteration-01/nominal.dat').exists() and not (I/'iteration-01/nominal.txt').exists()
log=(I/'iteration-01/propagate.log').read_text();pattern=r'relative_residual=([0-9.e+-]+), tolerance=([0-9.e+-]+), iterations=(\d+), rhs_norm=([0-9.e+-]+), solution_norm=([0-9.e+-]+), epochs=(\d+), solve_role=(\w+), column=(\d+), duration_seconds=([0-9.e+-]+)';m=re.search(pattern,log);assert m
res,tol,it,rhs,sol,epochs,role,col,duration=m.groups();values=dict(relative_residual=float(res),tolerance=float(tol),iterations=int(it),rhs_norm=float(rhs),solution_norm=float(sol),epochs=int(epochs),solve_role=role,column=int(col),duration_seconds=float(duration));assert values['relative_residual']>values['tolerance']==2e-12 and values['iterations']==120 and role=='physical_correction' and int(col)==0
# The exact frozen source supplies the algorithm meaning; source-byte audit is independent of any new native execution.
f=read(V/'control/source-freeze.json');source=V/'source';actual={str(p.relative_to(source)):pin(p)['sha256'] for p in source.rglob('*') if p.is_file()};assert actual==f['source']['files'] and len(actual)==384
native=B/'validation-03/control/native-binaries/groops-a66949456ad67b81';assert pin(native)['sha256']==x['native_binary_sha256']
source_pins=[pin(source/'groops/extension/sixStateTangent.h'),pin(source/'groops/extension/stagedVariationalBody.h'),pin(source/'src/orbit_poc/comparison/initialization.py'),pin(source/'src/orbit_poc/segmented/multiday.py')]
components=[]
for p in sorted((R/'preparation-jobs').glob('*/request.json')):
 q=read(p)
 if q['component']!='prefix':continue
 output=Path(q['output']);record=read(output/'nominal-initialization/initialization.json')
 components.append(dict(case_id=q['case']['case_id'],request=pin(p),initialization=pin(output/'nominal-initialization/initialization.json'),status=record['status'],iteration_count=len(record['iterations']),last_iteration=record['iterations'][-1] if record['iterations'] else None))
print(json.dumps(dict(schema='orbit-poc-preparation03-failure-numerical-evidence-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),initialization=pin(I/'initialization.json'),failure_log=pin(I/'iteration-01/propagate.log'),source_pins=source_pins,source_full_file_membership_verified=384,native_binary=pin(native),initial_state=pin(I/'initial_state.txt'),fixed_state_exactly_matches_first_initializer_epoch=True,bootstrap_unchanged=pin(orbit),immutable_inputs_verified=immutable,selected_profiles=profiles,first_closure_export_absent=True,numerical_guard=values,excess_over_guard=values['relative_residual']/values['tolerance'],prefix_records=components,classification='Native right-preconditioned restarted GMRES true-residual guard failed during physical_correction before the first outer nominal-closure trajectory export. This is neither an outer-closure iteration-limit result nor a fit/QR/LM or covariance outcome.',unresolved='The saved terminal residual alone does not distinguish slow restarted-GMRES convergence, inaccurate preconditioning or finite-precision stagnation. No numerical-floor, correction efficacy or relaxed acceptance claim is warranted without a controlled diagnostic preserving this input and operator.',scope='Read-only exact source/native/bootstrap/fixed-state/immutable-input checks and saved-log interpretation; no replay, source change or native process launched.'),indent=2))
