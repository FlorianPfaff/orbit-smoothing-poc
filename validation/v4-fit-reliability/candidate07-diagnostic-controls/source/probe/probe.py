"""Source-only binding and one-call evaluator adapter; no executable entry point.

The eventual owned controller must verify runtime/source/namespace and an actual
local600 terminal boundary before constructing the unchanged NativeModel.
"""
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
BASE = Path('/mnt/d/orbit-v41-recovery02')
POINT = BASE/'candidate07-cold-density04/cold-density/fit/point-003-closure-refinement'
REQUEST = BASE/'candidate07-cold-density04/cold-density/request.json'

class Ineligible(ValueError): pass

def require(condition, message):
    if not condition: raise Ineligible(message)

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): value.update(block)
    return value.hexdigest()

def read(path): return json.loads(Path(path).read_text())

def save(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')

def matrix(text,rows,columns):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    require(len(lines)==rows+2 and lines[:2]==['groops matrix version=20200123',
            f'Matrix( {rows} x {columns} )'],'Exact native matrix envelope required')
    result=[[float(token) for token in line.split()] for line in lines[2:]]
    require(all(len(row)==columns and all(math.isfinite(v) for v in row) for row in result),
            'Matrix shape or finite-value mismatch')
    return result

def candidate(initial,design,proposal,reference,baseline_density):
    require(len(initial)==6 and len(design)==6 and all(len(row)==67 for row in design)
            and len(proposal)==len(reference)==67 and len(baseline_density)==61,'Physical mapping dimensions differ')
    values=[*initial,*proposal,*reference,*baseline_density,*(v for row in design for v in row)]
    require(all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values),
            'Nonfinite physical binding')
    delta=[a-b for a,b in zip(proposal,reference)]
    mapped=[sum(row[i]*delta[i] for i in range(67)) for row in design]
    result={'initial':[a+b for a,b in zip(initial,mapped)],
            'force':[baseline_density[i]+delta[i] for i in range(61)],
            'dynamic_delta':delta,'initial_delta_si':mapped}
    require(all(math.isfinite(v) for key in result for v in result[key]),'Nonfinite mapped proposal')
    return result

def chart(path):
    with Path(path).open(newline='') as stream:
        reader=csv.DictReader(stream,delimiter='\t'); fields=reader.fieldnames
        require(fields and len(fields)==len(set(fields)) and
                {'index','name','dynamic','unit','scale'}.issubset(fields),'Malformed parameter chart')
        rows=list(reader)
    require(all(None not in row and None not in row.values() for row in rows),'Malformed chart row')
    return [{k:v for k,v in row.items() if k!='scale'} for row in rows]

def bind_archived_proposal():
    pins=[]
    for line in (HERE/'archived-inputs.sha256').read_text().splitlines():
        sha,relative=line.split('  ',1);path=BASE/relative
        require(path.is_relative_to(BASE) and '..' not in path.parts and digest(path)==sha,'Archived input changed')
        pins.append({'path':str(path),'sha256':sha})
    vector=lambda name,n:[row[0] for row in matrix((POINT/name).read_text(),n,1)]
    density=[line.split() for line in (POINT/'native/log_density.txt').read_text().splitlines() if line.strip()]
    require(len(density)==61 and all(len(row)==2 for row in density),'Density file shape differs')
    epochs=[float(row[0]) for row in density];g=[float(row[1]) for row in density]
    require(all(math.isfinite(t) for t in epochs) and all(b>a for a,b in zip(epochs,epochs[1:])),
            'Density knot ordering differs')
    result=candidate(vector('physical_initial.txt',6),
        matrix((POINT/'closure-02/initial_design.txt').read_text(),6,67),
        vector('proposal-000/parameters.txt',67),vector('closure-02/reference.txt',67),g)
    names=chart(POINT/'qr.74.parameters.tsv');dynamic=[row for row in names if row['dynamic']=='1']
    factor=read(POINT/'qr.74.factor.json')
    require(len(dynamic)==67 and [int(row['index']) for row in dynamic]==list(range(240,307))
            and all(':logDensity::' in row['name'] and row['unit']=='1' for row in dynamic[:61])
            and all(row['unit']=='m' for row in dynamic[61:])
            and factor['dynamic']==[i<67 for i in range(146)]
            and factor['retained_global_indices']==list(range(240,386)), 'Archived physical chart differs')
    result.update(archived_inputs=pins,reference_orbit=str(POINT/'closure-02/orbit.dat'),
        density_epoch_tokens=[row[0] for row in density],baseline_density=g,expected_chart=names,
        preprocessing_audit_sha256=digest(POINT/'native/output/2024-04-24/preprocessing_audit.txt'),
        baseline_objective=read(POINT/'qr.74.profile.json')['direct_cost'],
        baseline_tighter=True,baseline_archived_floor=0.00123538076877594,
        physical_density_source=str(POINT/'native/log_density.txt'),fixed_force_is_density_state=False)
    return result

def strict_profile(profile,confirmation):
    """Qualification uses the unchanged strict gate; floor progress stays distinct."""
    require(profile.get('nuisance_converged') is True and profile.get('nuisance_floor_limited') is False,
            'Strict profile unavailable (floor-limited progress is not strict convergence)')
    require(profile.get('conditional_nuisance_qr') is True and profile.get('fresh_full_nuisance_confirmed') is True
            and profile.get('threshold_m')==1e-8 and profile.get('required_consecutive_small_updates')==2
            and profile.get('fixed_weights') is True and profile.get('dynamic_updates') is False,
            'Unchanged strict profile contract missing')
    history=profile.get('history',[]);fresh=profile.get('fresh_full_nuisance_update_m')
    small=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<1e-8
    require(len(history)>=2 and all(small(row.get('maximum_update_m')) for row in history[-2:]) and small(fresh),
            'Two strict updates plus fresh full confirmation required')
    zero=confirmation.get('zero_update_replay',{});trials=confirmation.get('trials',[])
    require(confirmation.get('stationary_without_update') is True and confirmation.get('accepted') is False
            and confirmation.get('alpha')==0 and confirmation.get('undamped_maximum_update_m')==fresh
            and zero.get('status')==0 and zero.get('actual_reduction')==0 and zero.get('maximum_update_m')==0
            and zero.get('error')=='' and len(trials)==1 and trials[0].get('alpha')==1
            and trials[0].get('status')==0 and trials[0].get('error')==''
            and trials[0].get('maximum_update_m')==fresh,'Fresh unchanged full confirmation does not bind the profile')

def evaluate_once(model,state):
    # One ordinary physical trial. No optimizer, installation or covariance API.
    return model.evaluate(state,'archived-undamped',tighter=False,covariance=False)

def evaluate_bound_probe(model,binding):
    """Called only by the future reviewed owned worker; no standalone launcher."""
    from orbit_poc.numerics import backend
    import numpy as np
    require(digest(backend.__file__)=='c3687ca9df0f45c77bc0141c1a006859a97065e7adce894c1711ac70dd1f5249',
            'Unchanged corrected evaluator required')
    require(type(model) is backend.NativeModel and model.job==read(REQUEST)
            and model.sequence==0 and not model.executions and model.propagations==0,
            'Fresh exact-request model required')
    require(binding==bind_archived_proposal(),'Physical binding changed')
    root=Path(model.root)
    require(root.is_dir() and not any(root.iterdir()),'Exclusive empty probe root required')
    save(root/'physical-binding.json',binding)
    report={'status':'failed','objective_qualified':False,'physical_evaluations_requested':1,
        'tighter':False,'covariance_requested':False,'accepted_physical_update':False,
        'covariance_authority':False,'convergence_authority':False,'release_authority':False,
        'baseline_objective':binding['baseline_objective'],'baseline_tighter':True,
        'baseline_archived_floor':binding['baseline_archived_floor'],'new_candidate_floor_measured':False}
    try:
        state=backend.PhysicalState(np.asarray(binding['initial']),np.asarray(binding['force']),Path(binding['reference_orbit']))
        point=evaluate_once(model,state)
        folder=Path(point.metadata['folder']);profile=read(folder/'qr.profile.json')
        report.update(nuisance_profile=profile,observed_direct_cost=point.objective,
            observed_direct_cost_scope='Actual evaluator output; not a qualified strictly profiled objective until all gates below pass')
        if profile.get('nuisance_floor_limited') is True: report['status']='ineligible_floor_limited'
        require([row[0] for row in matrix((folder/'physical_initial.txt').read_text(),6,1)]==binding['initial'],
                'Actual physical initial state differs from bound proposal')
        physical_density=[line.split() for line in (folder/'native/log_density.txt').read_text().splitlines() if line.strip()]
        require(all(len(row)==2 for row in physical_density)
                and [row[0] for row in physical_density]==binding['density_epoch_tokens']
                and [float(row[1]) for row in physical_density]==binding['force'],
                'Actual density knot values or epochs differ from bound proposal')
        # Use the unchanged native ASCII reader, not a new orbit parser. This
        # expansion is a preserved derivative of a hash-bound archive member.
        reference_text=root/'archived-reference-orbit.txt'
        with gzip.open(POINT/'closure-02/orbit.txt.gz','rb') as source, reference_text.open('xb') as target:
            shutil.copyfileobj(source,target)
        expected_epochs,_=backend.native._orbit(reference_text)
        require(np.array_equal(point.metadata['epochs'],expected_epochs),'Full trajectory epoch support changed')
        report.update(physical_inputs_match=True,trajectory_epoch_count=len(expected_epochs),
                      trajectory_epochs_match=True,expanded_reference_sha256=digest(reference_text))
        confirmations=list(folder.glob('qr.*.nuisance_confirmation.json'))
        require(len(confirmations)==1,'Unique actual full-profile confirmation required; maximum suffix is insufficient')
        prefix=str(confirmations[0]).removesuffix('.nuisance_confirmation.json')
        require(point.metadata['factor_prefix']==prefix,'Selected factor is not the independently identified confirmed factor')
        confirmation=read(confirmations[0]);strict_profile(profile,confirmation)
        info=read(prefix+'.factor.json');diagnostics=read(prefix+'.diagnostics.json');cost=read(prefix+'.profile.json')
        backend.require_full_native_factor(info,diagnostics)
        require(chart(prefix+'.parameters.tsv')==binding['expected_chart'],'Nuisance/physical chart support changed')
        audit=Path(point.metadata['config']['result_paths']['preprocessing_audit'])
        require(digest(audit)==binding['preprocessing_audit_sha256'],'Observation preprocessing support changed')
        expected=backend.canonical_hash({'input':model.input_support,'audit':binding['preprocessing_audit_sha256'],
                                        'parameters':binding['expected_chart']})
        require(point.support_hash==expected and point.metadata['nuisance_floor_limited'] is False,
                'Support or strict objective eligibility changed')
        require(math.isfinite(point.objective) and point.objective==cost['direct_cost']
                and confirmation['objective_before']==point.objective
                and confirmation['zero_update_replay']['cost']==point.objective,
                'Fresh confirmed direct objective does not match selected factor')
        closure=read(folder/'closure.json')
        require(closure.get('converged') is True and closure.get('tighter') is False,'Ordinary physical closure did not complete')
        report.update(status='strict_fixed_point_evaluated',objective_qualified=True,
            objective=point.objective,archived_baseline_minus_candidate=binding['baseline_objective']-point.objective,
            closure=closure,factor_prefix=prefix,confirmation_sha256=digest(confirmations[0]),
            support_hash=point.support_hash,interpretation='One fixed physical point; no step accepted or objective floor newly measured')
    except Ineligible as error:
        if report['status']=='failed': report['status']='ineligible'
        report['error']=str(error)
    except BaseException as error:
        report.update(status='failed',error=repr(error),failure_reason=getattr(error,'reason',type(error).__name__))
        raise
    finally:
        report.update(propagation_count=model.propagations,native_executions=model.executions,
                      physical_evaluations_started=model.sequence)
        save(root/'probe-result.json',report)
    return report
