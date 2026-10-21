"""Supplemental gate draft; no compiler/native launcher. Plan/check explicit artifacts.

Execution belongs to reviewed host controls. This module never mutates source,
launches a subprocess, changes tolerances, or treats missing output as a pass.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

RESIDUAL = 2e-12
STM_RTOL = STM_ATOL = 2e-9
CASES = ('unsorted_repeated','ordinary','singleton','same_times','near_epsilon',
         'near_epsilon_scalar_control','pulse_position','pulse_velocity',
         'density_velocity','density_position')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(pin):
    require(set(pin) == {'path','sha256'}, 'Expected exact path/hash pin')
    p = Path(pin['path'])
    require(p.is_file() and digest(p) == pin['sha256'], 'Missing or changed pinned file')
    return p


def load_decoder(pin):
    path = verify(pin)
    spec = importlib.util.spec_from_file_location('supplemental_pinned_tangent_decoder',path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def jsonl(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    require(rows, 'Missing output records')
    return rows


def write_fresh(path, value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,allow_nan=False)
        stream.write('\n')


def check_batch(rows, decoder):
    require(rows[0].get('schema') == 'orbit-poc-native-batch-fixture-v1', 'Wrong fixture schema')
    require(rows[-1] == {'kind':'complete','cases':10}, 'Missing/incorrect terminal fixture record')
    require(rows[0]['long_double_digits'] >= 64, 'Insufficient native arithmetic precision')
    eps = decoder.hexadecimal(rows[0]['time_epsilon'])
    require(0 < eps < Fraction(1,10000), 'Invalid actual Time epsilon')
    cases = [r for r in rows if r.get('kind') == 'case']
    require(tuple(r['name'] for r in cases) == CASES, 'Missing/reordered/repeated case')
    coverage = [r for r in rows if r.get('kind') == 'coverage']
    require(len(rows) == 13 and len(coverage) == 1 and coverage[0]['scalar_batch_distinction'] is True,
            'Missing coverage record or unexpected output')
    low = decoder.hexadecimal(coverage[0]['identity_low_hex'])
    require(low == 1+Fraction(1,2**60), 'Identity low bits lost')
    normalized = {}
    bounds = []
    for case in cases:
        grid = case['grid']; outputs = case['outputs'];n=len(grid)
        require(n==33, 'Changed fixture grid')
        values = [decoder.hexadecimal(r[2]) for r in grid]
        times = [Fraction(r[0])+decoder.hexadecimal(r[1]) for r in grid]
        require(times == [Fraction(60000)+Fraction(5*i,86400) for i in range(n)] or
                all(abs((t-Fraction(60000))*86400-5*i) < Fraction(1,10**11) for i,t in enumerate(times)),
                'Changed native grid times')
        require([r['slot'] for r in outputs] == list(range(len(outputs))), 'Lost original output slots')
        decoded=[];qseconds=[]
        for row in outputs:
            stencil=decoder.decode_stencil(row['stencil'],decoder.V2,n);decoded.append(stencil)
            native=decoder.hexadecimal(row['native']);wide=decoder.hexadecimal(row['wide'])
            exact=stencil.evaluate(values)
            # Bounded comparison to exact dyadic branch algebra. The ordinary
            # BLAS path and twofold->long-double->double path need not be bit equal.
            norm=sum((abs(w*values[i]) for i,w in stencil.coefficients()),Fraction(0))
            bound=Fraction(64,2**52)*max(Fraction(1),norm)
            require(abs(native-exact)<=bound and abs(wide-exact)<=bound,
                    'Native/batch-metadata values disagree with exact branch algebra')
            bounds.append(float(bound))
            qseconds.append((Fraction(row['time'][0])+decoder.hexadecimal(row['time'][1])-60000)*86400)
        normalized[case['name']]=(case,decoded,qseconds)
    expected_queries={'unsorted_repeated':[112,12,84,12,154,78,80,82],
                      'ordinary':[112,12,84,12,154,78,80,82], 'singleton':[11.25],
                      'same_times':list(range(0,165,5)), 'pulse_position':[78,80,82],
                      'pulse_velocity':[78,80,82], 'density_velocity':[78,80,82], 'density_position':[78,80,82]}
    for name, expected in expected_queries.items():
        case,stencils,times=normalized[name]
        require(len(times)==len(expected) and all(abs(t-Fraction(q))<Fraction(1,10**10) for t,q in zip(times,expected)),
                'Queries not preserved in requested original order')
    for name,(case,stencils,_) in normalized.items():
        require(case['precise'] == (name!='ordinary'), 'Wrong arithmetic branch')
        expected_channel='velocity' if name in ('pulse_velocity','density_velocity') else 'position'
        require(case['channel']==expected_channel, 'Wrong boundary value channel')
        if name=='ordinary':require(any(s.mode=='ordinary' for s in stencils), 'Ordinary native path unexercised')
        elif name!='same_times':require(any(s.mode=='anchored_twofold' for s in stencils), 'Anchored path unexercised')
    same=normalized['same_times'][1]
    require(all(s.mode=='exact' and s.indices==(i,) and s.evaluate([low]*33)==low for i,s in enumerate(same)),
            'sameTimes identity not captured')
    _,pair,qt=normalized['near_epsilon'];_,scalar,qs=normalized['near_epsilon_scalar_control']
    require(len(pair)==2 and len(scalar)==1 and qt[1]==qs[0] and pair[1]!=scalar[0], 'Stateful batch distinction not demonstrated')
    require(abs((qt[0]-50)/eps-Fraction(6,5)) < Fraction(1,100) and
            abs((qt[1]-50)/eps-Fraction(2,5)) < Fraction(1,100), 'Wrong near-epsilon time pair')
    pv=normalized['pulse_velocity'][1]
    require(max(pv[0].indices)<16 and pv[1].mode=='exact' and pv[1].indices==(16,) and min(pv[2].indices)>=16,
            'Pulse one-sided/post-pulse support violated')
    for name in ('pulse_position','density_position','density_velocity'):
        stencils=normalized[name][1]
        require(max(stencils[0].indices)<=16 and min(stencils[1].indices)>=16 and min(stencils[2].indices)>=16,
                'Stencil crosses physical boundary')
    expected_values={'pulse_velocity':[3.78,10.8,10.82], 'pulse_position':[78,80,96],
                     'density_velocity':[3.78,3.8,3.82], 'density_position':[3.78,3.8,3.82]}
    for name,want in expected_values.items():
        got=[float(decoder.hexadecimal(r['native'])) for r in normalized[name][0]['outputs']]
        require(all(abs(a-b)<=2e-12 for a,b in zip(got,want)), 'Boundary jump/continuity mismatch')
    return {'passed':True,'case_count':10,'actual_native_batch_selection':True,
            'scalar_selection_used_for_acceptance':False,'ordinary_value_error_bound':'64*binary64_epsilon*max(1,sum(abs(exact_coefficient*value)))',
            'maximum_absolute_value_bound':max(bounds),'gnss_offset_path_exercised':False}


def fixture_commands(normalized, fixture, output):
    """Plan only: replace actual main object with fixture; preserve 610 objects.

    The pinned native groops.cpp has only static groopsHelp and main definitions.
    Actual linkage is still a pending acceptance gate; no compile is invoked.
    """
    roots=normalized['candidate_roots']
    require(set(roots.values())=={'<SOURCE>','<BUILD>'},'Unknown candidate roots')
    source=next(k for k,v in roots.items() if v=='<SOURCE>')
    build=next(k for k,v in roots.items() if v=='<BUILD>')
    commands=normalized['normalized_commands']
    main='CMakeFiles/groopscore.dir/groops.cpp.o'
    compile_rows=[r for r in commands if '-c' in r and '<SOURCE>/groops.cpp' in r]
    require(len(compile_rows)==1, 'Missing unique actual main compile recipe')
    compile_=list(compile_rows[0]);out=Path(output)
    replacements={main:str(out/'fixture.o'), main+'.d':str(out/'fixture.o.d'), '<SOURCE>/groops.cpp':str(fixture)}
    compile_=[replacements.get(x,x.replace('<SOURCE>',source)) for x in compile_]
    links=[r for r in commands if r[:2]==[':','&&'] and main in r and '-o' in r]
    require(len(links)==1 and links[0][-2:]==['&&',':'], 'Unknown actual native link wrapper')
    link=links[0][2:-2]
    require(sum(x.endswith('.o') for x in link)==611 and link.count(main)==1,'Changed native object inventory')
    linked=[]
    for x in link:
        if x==main:linked.append(str(out/'fixture.o'))
        elif x.endswith('.o'):linked.append(str(Path(build)/x))
        elif x.startswith('-Wl,--dependency-file='):linked.append('-Wl,--dependency-file='+str(out/'link.d'))
        else:linked.append(x.replace('<SOURCE>',source).replace('<BUILD>',build))
    require(linked[linked.index('-o')+1]=='groops','Unknown native output target')
    linked[linked.index('-o')+1]=str(out/'native-batch-fixture')
    require(compile_[0]==linked[0], 'Changed compiler between compile and link')
    return {'compile':compile_,'link':linked,'run':[str(out/'native-batch-fixture')],
            'cwd':str(out),'read_only_existing_objects':610,'native_execution_performed':False}


def semantic_xml(root):
    return (root.tag,tuple(sorted(root.attrib.items())),(root.text or '').strip(),tuple(semantic_xml(c) for c in root))


def flight_config(original_xml, output_map, export_path=None, stm_path=None):
    """Output-only adaptation of exact saved final coarse closure XML.

    Preserve original program order/evaluation and every physical input. Append
    the existing STM exporter. No force/clock/GNSS/preprocessing code is added.
    """
    old=ET.fromstring(original_xml);new=deepcopy(old)
    require(old.tag=='groops', 'Unexpected original XML')
    props=old.findall('./program/PreprocessingVariationalEquation')
    require(len(props)==1,'Expected one original propagation')
    p=props[0]
    require(p.findtext('orbitPocDerivativeProfile')=='flight_gravity_drag_v1','Wrong flight derivative profile')
    require(p.find('inputfileAccelerometer') is None and p.find('forces/miscAccelerations/syntheticDrag') is None,
            'Unsupported measured/synthetic force')
    require(p.findtext('forces/gravityfield/potentialCoefficients/maxDegree')=='120' and
            p.find('forces/miscAccelerations/atmosphericDrag') is not None,'Expected actual degree120 atmospheric flight force')
    require(p.find('orbitPocSegmentedTangentExport') is None, 'Baseline already contains diagnostic export')
    require(old.find('.//GnssProcessing') is None,'Flight diagnostic must not run estimation')
    require(old.find('.//OrbitPocEvaluateVariational/inputfileInitialState') is not None,
            'Missing original fixed physical initial state')
    outputs={n.text.strip() for n in old.iter() if n.tag.startswith('outputfile') and n.text and n.text.strip()}
    # Derivative diagnostics uses a historical non-outputfile field name.
    for n in old.iter('orbitPocDerivativeDiagnostics'):
        if n.text:outputs.add(n.text.strip())
    require(set(output_map)==outputs and len(set(output_map.values()))==len(output_map), 'Incomplete or colliding output mapping')
    require(not(set(output_map.values()) & outputs),'Output overwrites baseline')
    changed=[]
    for n in new.iter():
        if n.text and n.text.strip() in output_map:
            before=n.text.strip();n.text=output_map[before];changed.append({'tag':n.tag,'before':before,'after':n.text})
    np_=new.find('./program/PreprocessingVariationalEquation')
    require((export_path is None)==(stm_path is None),'Incomplete diagnostic export')
    if export_path is not None:
        ET.SubElement(np_,'orbitPocSegmentedTangentExport').text=str(export_path)
        variational=np_.findtext('outputfileVariational');require(variational is not None,'Missing original variational output')
        exporter=ET.SubElement(ET.SubElement(new,'program'),'OrbitPocStateDerivatives')
        ET.SubElement(exporter,'inputfileVariational').text=variational
        ET.SubElement(exporter,'outputfileStateTransition').text=str(stm_path)
    # Prove reversibility of the complete adapted recipe, not only forces.
    restored=deepcopy(new)
    if export_path is not None:
        restored.remove(restored[-1])
        rp=restored.find('./program/PreprocessingVariationalEquation');rp.remove(rp.find('orbitPocSegmentedTangentExport'))
    inverse={v:k for k,v in output_map.items()}
    for n in restored.iter():
        if n.text and n.text.strip() in inverse:n.text=inverse[n.text.strip()]
    require(semantic_xml(restored)==semantic_xml(old),'Non-output physical XML change')
    return ET.tostring(new,encoding='utf-8',xml_declaration=True),changed


def retained_orbit_times(content):
    """Read only the exact pinned native single-arc ORBIT binary schema.

    GROOPS ArchiveBinary writes a magic byte, length-prefixed strings, its
    compatibility padding, Int64 type, UInt64 arc/epoch counts, then each
    Time as Int64 day + Double fraction followed by nine Doubles. This is
    intentionally not a general instrument reader or a native converter.
    """
    header=(b'B'+struct.pack('<Q',10)+b'instrument'+struct.pack('<Q',8)+
            b'20200123'+b'   '+struct.pack('<qQQ',-6,1,361))
    require(content.startswith(header) and len(content)==len(header)+361*88,
            'Unsupported retained binary orbit schema, count or length')
    times=[]
    for values in struct.iter_unpack('<q10d',content[len(header):]):
        day,fraction=values[:2]
        require(day==60424 and math.isfinite(fraction) and 0<=fraction<1 and
                all(math.isfinite(x) for x in values[2:]),'Invalid retained orbit epoch')
        times.append([day,fraction])
    return times


def check_flight_time_grid(meta, main, drag, retained_times):
    """Bind exact native Time components; do not replace T/360 with literal 5.

    The inherited crop_instrument checks separately identify the intended
    30-minute/5-second window. They do not govern the tangent/STM accuracy.
    """
    n=meta['epochs']
    require(n==361 and len(main)==n and len(retained_times)==n and len(drag)>=n,
            'Not original coarse 30-minute 361-epoch window')
    require([r['time'] for r in main]==retained_times,
            'Typed main Time components differ from retained input grid')
    require([r['time'] for r in drag[:n]]==retained_times,
            'Native drag grid Time components differ from retained input grid')
    require(all(type(d) is int and type(f) is float and d==60424 and
                math.isfinite(f) and 0<=f<1 for d,f in retained_times),
            'Invalid retained precise Time components')
    seconds=[(Fraction(d-60424)+Fraction(f))*86400-42318 for d,f in retained_times]
    # These are the original crop_instrument window/support limits, unchanged.
    require(abs(seconds[0])<=Fraction(1,100000) and
            abs(seconds[-1]-1800)<=Fraction(1,100000) and
            all(abs(t-5*i)<=Fraction(1,100000) for i,t in enumerate(seconds)) and
            all(abs(b-a-5)<=Fraction(2,1000000) for a,b in zip(seconds,seconds[1:])),
            'Retained grid is not the prescribed April24 11:45-12:15 UTC/5s window')
    # Match Time::operator-= normalization and Time::seconds operation order.
    day=retained_times[-1][0]-retained_times[0][0]
    fraction=retained_times[-1][1]-retained_times[0][1]
    carry=math.floor(fraction);day+=carry;fraction-=carry
    span=(day+fraction)*86400
    require(meta.get('dt')==span/(n-1),'Export dt differs from native endpoint-span arithmetic')
    require(meta.get('initial_velocity_scale')==1/span,
            'Export initial velocity scale differs from native endpoint span')
    return {'all_retained_time_components_identical':True,'checked_epochs':n,
            'endpoint_span_seconds':span,'native_dt_seconds':meta['dt'],
            'native_initial_velocity_scale':meta['initial_velocity_scale'],
            'nominal_interval_seconds':5,'nominal_duration_seconds':1800,
            'inherited_window_limit_seconds':1e-5,'inherited_interval_limit_seconds':2e-6,
            'maximum_nominal_epoch_offset_seconds':float(max(abs(t-5*i) for i,t in enumerate(seconds)))}


def check_flight(records, transition, baseline_orbit, replay_orbit, derivatives, baseline_result, decoder, retained_times):
    import numpy as np
    from scipy.sparse import lil_matrix
    from scipy.sparse.linalg import spsolve
    require(baseline_result.get('passed') is True and baseline_result.get('status')=='complete' and
            baseline_result.get('schema')=='flight-staged-refinement-3.1', 'Missing passed original flight refinement')
    require(baseline_result.get('date')=='2024-04-24' and baseline_result.get('start_utc_seconds')==42300 and
            baseline_result.get('duration_seconds')==1800,'Wrong predeclared flight window')
    require(baseline_result.get('code_threshold_m')==.003 and baseline_result.get('carrier_threshold_m')==3e-5,
            'Changed measurement refinement limits')
    meta=records[0]
    require(meta.get('schema')==decoder.V2 and meta.get('profile')=='flight_gravity_drag_v1','Not actual typed flight export')
    n=meta.get('epochs');require(n==361,'Not original coarse 30-minute 361-epoch window')
    require(derivatives.get('profile')=='flight_gravity_drag_v1' and
            derivatives.get('maximum_tangent_relative_residual',math.inf)<=RESIDUAL,'Missing native residual guard')
    require(derivatives.get('omitted_terms')==['thermal_history_sensitivities','non_gravity_non_drag_force_gradients','atmospheric_event_time_derivatives'],
            'Changed physical derivative approximation')
    require(meta.get('maximum_tangent_relative_residual')==derivatives['maximum_tangent_relative_residual'], 'Export/native residual attribution mismatch')
    require(transition.shape==(n,43) and baseline_orbit.shape==replay_orbit.shape and baseline_orbit.shape[0]==n,
            'Missing physical STM/orbit rows')
    require(np.isfinite(transition).all() and np.isfinite(baseline_orbit).all() and np.isfinite(replay_orbit).all(), 'Nonfinite saved output')
    require(np.array_equal(baseline_orbit,replay_orbit),'Matched QR export changed saved fixed-state orbit')
    require(np.array_equal(transition[:,0],baseline_orbit[:,0]),'Native STM epoch support changed')
    lifted=decoder.lift_tangent_export(records,maximum_epochs=1000)
    main=[r for r in records if r.get('kind')=='sample' and r.get('channel')=='main']
    drag=[r for r in records if r.get('kind')=='sample' and r.get('channel')=='drag']
    require(len(drag)>n and len(main)==n,'Actual atmospheric extras absent')
    require([r['index'] for r in main]==list(range(n)) and [r['index'] for r in drag]==list(range(len(drag))),
            'Native emitted sample ordering changed')
    time_grid=check_flight_time_grid(meta,main,drag,retained_times)
    require(np.array_equal(np.asarray([r['time'][0]+r['time'][1] for r in main]),transition[:,0]),
            'Typed main sample times disagree with saved native epochs')
    require(all(r['time']==main[i]['time'] for i,r in enumerate(drag[:n])),
            'Native drag grid time support differs from main grid')
    main_times={tuple(r['time']) for r in main}
    extra={r['index']:r for r in drag if r['index']>=n and tuple(r['time']) not in main_times}
    contributions={}
    for row in records:
        if row.get('kind')=='quadrature' and row.get('channel')=='drag':
            for index,integral,moment in row['terms']:
                key=(row['interval'],index);a,b=contributions.get(key,(Fraction(0),Fraction(0)))
                contributions[key]=(a+Fraction(integral),b+Fraction(moment))
    used={index for (_,index),(integral,moment) in contributions.items() if integral!=0 or moment!=0}
    effective=[i for i,r in extra.items() if i in used and any(x!=0 for x in r['Ar']+r['Av'])]
    require(effective,'No off-grid drag sample has nonzero quadrature and force Jacobian')
    # A different unused or zero-force anchored sample cannot certify the
    # arithmetic of an effective atmospheric contribution. Match the stencil
    # channel to the actual nonzero force Jacobian as well as quadrature use.
    anchored_effective=[i for i in effective if
        (extra[i]['position_stencil']['mode']=='anchored_twofold' and any(v!=0 for v in extra[i]['Ar'])) or
        (extra[i]['velocity_stencil']['mode']=='anchored_twofold' and any(v!=0 for v in extra[i]['Av']))]
    require(anchored_effective,'No effective off-grid drag sample uses matching anchored operator channel')
    entries,rhs,rounding=lifted.binary64()
    require(rounding['nonzero_coefficients_discarded']==0,'Typed lifting discarded nonzero data')
    e=lil_matrix((6*n,6*n))
    for row,col,value in entries:e[row,col]=value
    solution=spsolve(e.tocsc(),np.asarray(rhs))
    require(np.isfinite(solution).all(),'Lifted tangent solve failed')
    stm=solution.reshape(n,6,6)@np.linalg.inv(solution[:6])
    native=transition[:,7:].reshape(n,6,6)
    delta=np.abs(stm-native);bound=STM_ATOL+STM_RTOL*np.abs(native)
    require(np.all(delta<=bound),'Actual-flight lifted/native physical STM mismatch')
    return {'passed':True,'epochs':n,'drag_samples':len(drag),'offgrid_drag_samples':len(extra),
            'effective_offgrid_drag_samples':len(effective),'effective_anchored_offgrid_drag_samples':len(anchored_effective),
            'effective_anchored_offgrid_drag_indices':anchored_effective,'native_relative_residual':meta['maximum_tangent_relative_residual'],
            'residual_limit':RESIDUAL,'stm_rtol':STM_RTOL,'stm_atol':STM_ATOL,
            'maximum_stm_absolute_error':float(delta.max()),'maximum_stm_tolerance_fraction':float((delta/bound).max()),
            'rounding':rounding,'time_grid':time_grid,'physical_orbit_unchanged':True,'benchmark_fit_attempts':0,
            'scope':'Bounded implemented flight tangent approximation only; no covariance, density recovery, full flight derivatives or release claim.'}


def report(gate, planned_phases, phase_records, acceptance=None):
    require(len(planned_phases)==len(set(planned_phases)),'Duplicate planned phases')
    require(set(phase_records)<=set(planned_phases),'Unexpected phase')
    phases=[]
    for name in planned_phases:
        r=phase_records.get(name,{'status':'missing'})
        require(r.get('status') in ('complete','failed','missing','interrupted','timeout'),'Invalid phase status')
        phases.append({'phase':name,**r})
    passed=all(x['status']=='complete' for x in phases) and bool(acceptance and acceptance.get('passed') is True)
    return {'schema':'orbit-poc-wide-supplemental-gate-v1','gate':gate,'passed':passed,'phases':phases,
            'acceptance':acceptance,'source_changed':False,'frozen14_stage_credit':False,'benchmark_fit_attempts':0,
            'covariance_authorized':False,'release_ready':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('check-batch');p.add_argument('--records',required=True);p.add_argument('--decoder-pin',required=True);p.add_argument('--output',required=True)
    args=parser.parse_args()
    decoder=load_decoder(json.loads(Path(args.decoder_pin).read_text()))
    result=check_batch(jsonl(args.records),decoder)
    write_fresh(args.output,result)

if __name__=='__main__':main()
