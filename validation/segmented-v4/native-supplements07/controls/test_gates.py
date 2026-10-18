"""Pure acceptance/planning tests; no subprocess, compiler or native execution."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import pytest
import gates as g

SOURCE=Path('/mnt/d/orbit-segmented-v4/source')
PIN={'path':str(SOURCE/'src/orbit_poc/segmented/tangent_export.py'),
     'sha256':'54941e22a74e79b316961b77ba58d18666708355b586acabcd7ecc1e0785d4ed'}
D=g.load_decoder(PIN)


def xml():
    return b'''<groops><global><filename label="path">unchanged</filename></global><program><PreprocessingVariationalEquation>
    <inputfileOrbit>/old/seed.dat</inputfileOrbit><inputfileStarCamera>/old/attitude.txt</inputfileStarCamera>
    <outputfileVariational>/old/new.dat</outputfileVariational><orbitPocDerivativeDiagnostics>/old/derivatives.json</orbitPocDerivativeDiagnostics>
    <orbitPocDerivativeProfile>flight_gravity_drag_v1</orbitPocDerivativeProfile><forces><gravityfield><potentialCoefficients><maxDegree>120</maxDegree></potentialCoefficients></gravityfield><miscAccelerations><atmosphericDrag><atmosphere><jb2008/></atmosphere></atmosphericDrag></miscAccelerations></forces>
    </PreprocessingVariationalEquation></program><program><OrbitPocEvaluateVariational><inputfileVariational>/old/new.dat</inputfileVariational><inputfileInitialState>/old/physical_initial.txt</inputfileInitialState><outputfileOrbit>/old/orbit.txt</outputfileOrbit></OrbitPocEvaluateVariational></program></groops>'''


def mapping():
    return {p:'/new/'+Path(p).name for p in ('/old/new.dat','/old/derivatives.json','/old/orbit.txt')}


def test_output_only_adaptation_is_reversible():
    adapted,delta=g.flight_config(xml(),mapping(),'/new/tangent.jsonl','/new/stm.txt')
    old=ET.fromstring(xml());new=ET.fromstring(adapted)
    assert new.findtext('.//OrbitPocEvaluateVariational/inputfileVariational')=='/new/new.dat'
    assert new.findtext('.//OrbitPocEvaluateVariational/inputfileInitialState')=='/old/physical_initial.txt'
    assert ET.tostring(old.find('.//forces'))==ET.tostring(new.find('.//forces'))
    assert new[-1][0].tag=='OrbitPocStateDerivatives'
    assert len(delta)==4


@pytest.mark.parametrize('before,after',[('120','12'),('flight_gravity_drag_v1','legacy_v3'),
    ('atmosphericDrag','syntheticDrag'),('inputfileInitialState','inputfileUnknown')])
def test_reject_changed_physical_recipe(before,after):
    with pytest.raises(ValueError):g.flight_config(xml().replace(before.encode(),after.encode()),mapping(),'/new/t','/new/s')


def test_reject_measured_forces():
    x=xml().replace(b'<forces>',b'<inputfileAccelerometer>/bad</inputfileAccelerometer><forces>')
    with pytest.raises(ValueError):g.flight_config(x,mapping(),'/new/t','/new/s')


@pytest.mark.parametrize('change',[lambda m:m.pop('/old/orbit.txt'),lambda m:m.update({'/extra':'/new/extra'}),
    lambda m:m.update({'/old/orbit.txt':'/new/new.dat'}),lambda m:m.update({'/old/orbit.txt':'/old/new.dat'})])
def test_reject_incomplete_colliding_or_baseline_output_mapping(change):
    m=mapping();change(m)
    with pytest.raises(ValueError):g.flight_config(xml(),m,'/new/t','/new/s')


def test_no_native_or_compiler_calls_in_gate_module():
    import ast
    tree=ast.parse(Path(g.__file__).read_text())
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and any(a.name in ('subprocess','os') for a in n.names) for n in ast.walk(tree))


@pytest.mark.parametrize('status',['missing','failed','timeout','interrupted'])
def test_failed_missing_interrupted_phases_never_pass(status):
    r=g.report('x',['compile','run'],{'compile':{'status':'complete'},'run':{'status':status}}, {'passed':True})
    assert not r['passed'] and not r['release_ready'] and not r['frozen14_stage_credit']


def test_missing_acceptance_never_passes():
    assert not g.report('x',['run'],{'run':{'status':'complete'}})['passed']


def test_complete_acceptance_is_scoped():
    r=g.report('x',['run'],{'run':{'status':'complete'}},{'passed':True})
    assert r['passed'] and r['benchmark_fit_attempts']==0 and not r['covariance_authorized']


def test_unknown_phase_rejected():
    with pytest.raises(ValueError):g.report('x',['run'],{'surprise':{'status':'complete'}})


def test_pins_reject_changed_file(tmp_path):
    p=tmp_path/'data';p.write_text('one');pin={'path':str(p),'sha256':g.digest(p)};assert g.verify(pin)==p
    p.write_text('two')
    with pytest.raises(ValueError):g.verify(pin)


def test_evidence_not_overwritten(tmp_path):
    p=tmp_path/'result';g.write_fresh(p,{'first':True})
    with pytest.raises(FileExistsError):g.write_fresh(p,{'second':True})
    assert json.loads(p.read_text())=={'first':True}


def recipe():
    main='CMakeFiles/groopscore.dir/groops.cpp.o'
    objects=[main]+[f'CMakeFiles/groopscore.dir/file{i}.o' for i in range(610)]
    return {'candidate_roots':{'/source':'<SOURCE>','/build':'<BUILD>'},'normalized_commands':[
        ['/compiler','-I<SOURCE>','-O3','-DNDEBUG','-std=gnu++17','-MD','-MT',main,'-MF',main+'.d','-o',main,'-c','<SOURCE>/groops.cpp'],
        [':','&&','/compiler','-O3','-Wl,--dependency-file=CMakeFiles/groops.dir/link.d',*objects,'-o','groops','/libblas','&&',':']]}


def test_actual_recipe_substitution_only_replaces_main():
    p=g.fixture_commands(recipe(),'/fixture.cpp','/fresh')
    assert p['compile'][-1]=='/fixture.cpp' and '-I/source' in p['compile']
    assert p['link'].count('/fresh/fixture.o')==1
    assert len([x for x in p['link'] if x.startswith('/build/') and x.endswith('.o')])==610
    assert '/build/CMakeFiles/groopscore.dir/groops.cpp.o' not in p['link']
    assert '/fresh/link.d' in p['link'][2] and p['native_execution_performed'] is False


@pytest.mark.parametrize('change',[lambda r:r['normalized_commands'].pop(0),
    lambda r:r['normalized_commands'][-1].remove('CMakeFiles/groopscore.dir/file609.o'),
    lambda r:r['normalized_commands'][-1].__setitem__(2,'/wrong-compiler')])
def test_recipe_drift_rejected(change):
    r=recipe();change(r)
    with pytest.raises(ValueError):g.fixture_commands(r,'/fixture.cpp','/fresh')


def identity(i):return {'mode':'exact','derivative':0,'anchor':None,'terms':[[i,'0x1p+0','0x0p+0']]}


def flight_data():
    # A pure small-force manufactured linear operator; this fixture is not
    # actual flight or a native result. Generate independent forward recurrence
    # for the reference STM and use the real exact-dyadic decoder in the gate.
    n=361
    times=[[60424,float(Fraction(42318+5*i,86400))] for i in range(n)]
    span=(times[-1][1]-times[0][1])*86400;dt=span/(n-1);scale=1/span
    meta={'kind':'metadata','schema':D.V2,'profile':'flight_gravity_drag_v1','epochs':n,'dt':dt,
          'initial_velocity_scale':scale,'maximum_tangent_relative_residual':1e-13,
          'interpolation_semantics':D.SEMANTICS,'nominal_force_history':'unchanged_whole_arc',
          'new_process_priors':False,'forcing_design':'separate_native_variation_of_constants_export'}
    rows=[meta]
    z=[0.]*9
    for ch in ('main','drag'):
        for i in range(n):rows.append({'kind':'sample','channel':ch,'index':i,'time':times[i],'Ar':z[:],'Av':z[:],
                                     'position_stencil':identity(i),'velocity_stencil':identity(i)})
        if ch=='drag':
            st={'mode':'anchored_twofold','derivative':0,'anchor':0,'terms':[[0,'0x1p-1','0x0p+0'],[1,'0x1p-1','0x0p+0']]}
            av=z[:];av[0]=1e-8
            rows.append({'kind':'sample','channel':ch,'index':n,'time':[60424,float(Fraction(84641,172800))],
                         'Ar':z[:],'Av':av,'position_stencil':st,'velocity_stencil':deepcopy(st)})
        for k in range(n-1):rows.append({'kind':'quadrature','channel':ch,'interval':k,'terms':[[n,1.,0.]] if ch=='drag' and k==0 else []})
    rows.append({'kind':'complete'})
    # First velocity update v1 = v0 + a*(v0+v1)/2. First position
    # update x1=x0+5*v0+5*a*(v0+v1)/2. Thereafter free drift.
    stm=np.tile(np.eye(6),(n,1,1));a=1e-8;ratio=(1+a/2)/(1-a/2)
    for i in range(1,n):
        stm[i,:3,3:]=np.eye(3)*(dt*i)
        stm[i,3,3]=ratio;stm[i,0,3]=dt*ratio*i
    transition=np.zeros((n,43));transition[:,0]=[d+m for d,m in times];transition[:,7:]=stm.reshape(n,36)
    orbit=np.zeros((n,10));orbit[:,0]=transition[:,0]
    deriv={'profile':'flight_gravity_drag_v1','maximum_tangent_relative_residual':1e-13,
           'omitted_terms':['thermal_history_sensitivities','non_gravity_non_drag_force_gradients','atmospheric_event_time_derivatives']}
    result={'passed':True,'status':'complete','schema':'flight-staged-refinement-3.1','date':'2024-04-24',
            'start_utc_seconds':42300,'duration_seconds':1800,'code_threshold_m':.003,'carrier_threshold_m':3e-5}
    return rows,transition,orbit,orbit.copy(),deriv,result,D,deepcopy(times)


def test_flight_acceptance_uses_real_exact_decoder_and_manufactured_recurrence():
    result=g.check_flight(*flight_data())
    assert result['passed'] and result['effective_offgrid_drag_samples']==1 and result['epochs']==361
    assert result['residual_limit']==2e-12 and result['stm_rtol']==result['stm_atol']==2e-9


@pytest.mark.parametrize('change',[
    lambda d:d[0][0].update(schema=D.V1),
    lambda d:d[0][0].update(profile='synthetic_complete_v1'),
    lambda d:d[0].pop(),
    lambda d:d[4].update(maximum_tangent_relative_residual=2.001e-12),
    lambda d:d[4].update(omitted_terms=[]),
    lambda d:d[5].update(date='2024-04-25'),
    lambda d:d[5].update(passed=False),
    lambda d:d[5].update(code_threshold_m=.004),
    lambda d:d[3].__setitem__((0,1),1.),
    lambda d:d[1].__setitem__((0,7),1.01),
    lambda d:d[1].__setitem__((0,0),0.),
    lambda d:d[1].__setitem__((0,7),float('nan')),
])
def test_flight_missing_wrong_or_failed_output_rejected(change):
    d=list(flight_data());change(d)
    with pytest.raises((ValueError,KeyError)):g.check_flight(*d)


def test_no_zero_extra_sample_substitute():
    d=list(flight_data())
    # Keep a well-formed channel but remove actual off-grid use.
    for r in d[0]:
        if r.get('kind')=='quadrature' and r.get('channel')=='drag':r['terms']=[]
    with pytest.raises(ValueError,match='off-grid'):g.check_flight(*d)


def test_no_zero_force_extra_substitute():
    d=list(flight_data())
    for r in d[0]:
        if r.get('kind')=='sample' and r.get('channel')=='drag' and r['index']==361:r['Av']=[0.]*9
    with pytest.raises(ValueError,match='off-grid'):g.check_flight(*d)


def manufactured_batch():
    # Acceptance/parser fixture only. It intentionally does not certify the
    # native selector: later C++ output must carry actual native branch metadata.
    def h(x):return float(x).hex()
    eps=1e-9;low='0x1.000000000000001p+0'
    rows=[{'kind':'metadata','schema':'orbit-poc-native-batch-fixture-v1','time_epsilon':h(eps),'long_double_digits':64}]
    byname={'unsorted_repeated':[112,12,84,12,154,78,80,82], 'ordinary':[112,12,84,12,154,78,80,82],
            'singleton':[11.25], 'same_times':list(range(0,165,5)), 'near_epsilon':[50+1.2*eps,50+.4*eps],
            'near_epsilon_scalar_control':[50+.4*eps], 'pulse_position':[78,80,82], 'pulse_velocity':[78,80,82],
            'density_velocity':[78,80,82], 'density_position':[78,80,82]}
    for name in g.CASES:
        values=[1.25+i*.37+(i%3)*.012 for i in range(33)]
        if name=='pulse_position':values=[5*i+max(0,5*i-80)*7 for i in range(33)]
        if name=='pulse_velocity':values=[3+.01*5*i+(7 if i>=16 else 0) for i in range(33)]
        if name.startswith('density'):values=[3+.01*5*i for i in range(33)]
        grid=[[60000,h(Fraction(5*i,86400)),h(values[i])] for i in range(33)];out=[]
        for slot,q in enumerate(byname[name]):
            qt=float(Fraction(q)/86400);seconds=Fraction(qt)*86400
            if name=='same_times' or q==80:
                st=identity(round(q/5))
            else:
                first=min(31,int(q//5))
                if name=='pulse_velocity' and q<80:first=14
                if name=='near_epsilon_scalar_control':first=9
                qf=float((seconds-first*5)/5)
                mode='ordinary' if name=='ordinary' else 'anchored_twofold'
                st={'mode':mode,'derivative':0,'anchor':None if mode=='ordinary' else 0,
                    'terms':[[first,h(1-qf),'0x0p+0'],[first+1,h(qf),'0x0p+0']]}
            decoded=D.decode_stencil(st,D.V2,33);v=decoded.evaluate([Fraction(v) for v in values])
            out.append({'slot':slot,'time':[60000,h(qt)],'native':h(v),'wide':h(v),'stencil':st})
        rows.append({'kind':'case','name':name,'channel':'velocity' if name in ('pulse_velocity','density_velocity') else 'position',
                     'precise':name!='ordinary','grid':grid,'outputs':out})
    rows.insert(7,{'kind':'coverage','scalar_batch_distinction':True,'identity_low_hex':low})
    rows.append({'kind':'complete','cases':10});return rows


def test_batch_parser_manufactured_success_is_not_native_coverage():
    r=g.check_batch(manufactured_batch(),D)
    assert r['case_count']==10 and r['passed'] and not r['gnss_offset_path_exercised']


@pytest.mark.parametrize('change',[
    lambda r:r.pop(),lambda r:r.pop(1),lambda r:r[1]['outputs'][0].update(slot=6),
    lambda r:r[1]['outputs'][0].update(native='0x1p+80'),
    lambda r:r[1]['outputs'][0]['stencil'].update(anchor=50),
    lambda r:r[2].update(precise=True),lambda r:r[0].update(long_double_digits=53),
    lambda r:r[7].update(identity_low_hex='0x1p+0'),
])
def test_batch_rejects_missing_changed_or_misattributed_values(change):
    rows=manufactured_batch();change(rows)
    with pytest.raises((ValueError,KeyError)):g.check_batch(rows,D)


def test_batch_requires_actual_post_pulse_support():
    rows=manufactured_batch();row=next(r for r in rows if r.get('name')=='pulse_velocity')
    row['outputs'][0]['stencil']['terms'][1][0]=16
    with pytest.raises(ValueError):g.check_batch(rows,D)


def test_batch_requires_stateful_selection_distinction():
    rows=manufactured_batch();near=next(r for r in rows if r.get('name')=='near_epsilon')
    scalar=next(r for r in rows if r.get('name')=='near_epsilon_scalar_control')
    scalar['outputs'][0]=deepcopy(near['outputs'][1]);scalar['outputs'][0]['slot']=0
    with pytest.raises(ValueError,match='Stateful'):g.check_batch(rows,D)


def test_changed_low_coefficient_not_silently_dropped():
    rows=manufactured_batch();st=rows[1]['outputs'][0]['stencil'];st['terms'][1][2]='0x1p-5'
    with pytest.raises(ValueError):g.check_batch(rows,D)


def test_typed_sample_time_support_must_match_native_epochs():
    d=list(flight_data());d[0][1]['time'][0]+=1
    with pytest.raises(ValueError):g.check_flight(*d)


def test_actual_emitted_sample_order_is_preserved():
    d=list(flight_data());d[0][1],d[0][2]=d[0][2],d[0][1]
    with pytest.raises(ValueError,match='ordering'):g.check_flight(*d)


def ordinary(st):
    st['mode']='ordinary';st['anchor']=None


def test_inactive_anchored_extra_does_not_substitute_for_effective_ordinary_sample():
    d=list(flight_data());extra=next(r for r in d[0] if r.get('kind')=='sample' and r.get('channel')=='drag' and r['index']==361)
    unused=deepcopy(extra);unused['index']=362;unused['time'][1]+=1e-6;unused['Ar']=[0.]*9;unused['Av']=[0.]*9
    ordinary(extra['position_stencil']);ordinary(extra['velocity_stencil'])
    d[0].insert(d[0].index(extra)+1,unused)
    with pytest.raises(ValueError,match='matching anchored'):g.check_flight(*d)


def test_wrong_position_channel_anchor_does_not_certify_nonzero_velocity_force():
    d=list(flight_data());extra=next(r for r in d[0] if r.get('kind')=='sample' and r.get('channel')=='drag' and r['index']==361)
    ordinary(extra['velocity_stencil'])
    with pytest.raises(ValueError,match='matching anchored'):g.check_flight(*d)


def test_wrong_velocity_channel_anchor_does_not_certify_nonzero_position_force():
    d=list(flight_data());extra=next(r for r in d[0] if r.get('kind')=='sample' and r.get('channel')=='drag' and r['index']==361)
    extra['Ar'],extra['Av']=extra['Av'],extra['Ar'];ordinary(extra['position_stencil'])
    with pytest.raises(ValueError,match='matching anchored'):g.check_flight(*d)


def test_cancelled_quadrature_is_not_an_effective_anchored_sample():
    d=list(flight_data())
    for row in d[0]:
        if row.get('kind')=='quadrature' and row.get('channel')=='drag' and row['terms']:
            row['terms'].append([361,-1.,0.])
    with pytest.raises(ValueError,match='off-grid'):g.check_flight(*d)


def test_anchor_on_matching_velocity_channel_alone_is_sufficient():
    d=list(flight_data());extra=next(r for r in d[0] if r.get('kind')=='sample' and r.get('channel')=='drag' and r['index']==361)
    ordinary(extra['position_stencil']);result=g.check_flight(*d)
    assert result['effective_anchored_offgrid_drag_samples']==1
    assert result['effective_anchored_offgrid_drag_indices']==[361]
