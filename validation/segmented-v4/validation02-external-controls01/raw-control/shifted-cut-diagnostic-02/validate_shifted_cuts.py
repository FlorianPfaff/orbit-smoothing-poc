#!/usr/bin/env python3
"""Separate post-suite QR diagnostic; never propagates or profiles a trajectory."""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, source_snapshot, write_json
from orbit_poc.numerics.backend import read_factor
from orbit_poc.numerics.optimizer import Linearization, certify_rank, proposal, selected_covariance
from orbit_poc.segmented.graph import build_graph
from orbit_poc.segmented.solver import SegmentedLinearSystem, linearization_digest

DAMPING=(0.,.001,1000.)
PERIODS=(3600,14400)
OFFSETS=(300.,1800.)
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')


def require(value,message):
    if not value:raise ValueError(message)


def checked(pin):
    require(isinstance(pin,dict) and 'path' in pin and 'sha256' in pin,'Missing artifact identity')
    path=Path(pin['path'])
    require(path.is_absolute() and path.is_file() and file_hash(path)==pin['sha256'],'Artifact changed: '+str(path))
    if 'bytes' in pin:require(path.stat().st_size==pin['bytes'],'Artifact size changed')
    return path


def hash_value(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def ledger_identity(graph):
    """Ownership groups alone may change; every actual coefficient stays fixed."""
    return {name:hash_value(value) for name,value in {
        'variables':[asdict(x) for x in graph.variables],
        'equalities':[asdict(x) for x in graph.equalities],
        'stochastic':[asdict(x) for x in graph.stochastic],
        'retained_ids':list(graph.retained_ids),
        'linearization':graph.linearization_sha256,'support':graph.support_hash}.items()}


def interior_movement(baseline,shifted,last_epoch,dt):
    def owners(graph):
        return {i:g.stage for g in graph.groups for i in (*g.deterministic,*g.stochastic)}
    before,after=owners(baseline),owners(shifted)
    moved=[{'identifier':i,'name':shifted.variables[i].name,'old_stage':before[i],
            'new_stage':after[i],'new_seconds':after[i]*dt}
           for i in shifted.retained_ids if before[i]!=after[i] and 0<after[i]<last_epoch]
    return {'changed_original_elimination_ids':sum(before[i]!=after[i] for i in shifted.retained_ids),
            'interior_movement_count':len(moved),'interior_movements':moved,
            'adequate':bool(moved),'definition':'An original retained parameter changes elimination owner to a strictly interior native-grid epoch; unchanged ownership cannot certify cut coverage.'}


def terminal_gate(controller_pin,pipeline_pin,validation_pin):
    controller=read_json(checked(controller_pin));pipeline=read_json(checked(pipeline_pin))
    require(controller.get('status')=='passed' and controller.get('final_cleanup',{}).get('verified') is True,
            'Original outer controller must be terminal passed and cleaned')
    link=controller.get('cli_validation',{}).get('pipeline',{})
    require(link.get('path')==pipeline_pin['path'] and link.get('sha256')==pipeline_pin['sha256'],
            'Controller attributes a different validation pipeline')
    require(pipeline.get('status')=='passed' and tuple(s.get('name') for s in pipeline.get('steps',[]))==STAGES,
            'Require the exact terminal passed14-stage pipeline')
    for step in pipeline['steps']:
        require(step.get('status')=='passed','Every original gate must pass first')
        execution=read_json(checked(step.get('execution')))
        require(execution.get('status')=='complete' and execution.get('returncode')==0
                and execution.get('harness_execution',{}).get('owned_process_group_cleaned') is True,
                'Original gate process/cleanup did not pass')
    validation=read_json(checked(validation_pin))
    require(validation.get('schema')=='orbit-poc-segmented-linearization-gate-v1'
            and validation.get('passed') is True and validation.get('physical_evaluations')==1,
            'Require the unchanged completed actual native linearization gate')
    # The pipeline result must name this receipt, not another one-hour problem.
    matches=[s for s in pipeline['steps'] if s['name'].startswith('linearization-')
             and s.get('evidence',{}).get('result',{}).get('path')==validation_pin['path']
             and s.get('evidence',{}).get('result',{}).get('sha256')==validation_pin['sha256']]
    require(len(matches)==1,'Selected linearization is not an exact planned pipeline result')
    return validation


def load_captured(validation,source,source_sha,solver,solver_sha):
    require(source_snapshot(source)['sha256']==source_sha==validation['source_sha256'],'Frozen source identity changed')
    require(file_hash(solver)==solver_sha==validation['solver']['sha256']
            and Path(validation['solver']['path'])==Path(solver),'Frozen solver identity changed')
    checked(validation['source']);checked(validation['native']);checked(validation['original_request']);checked(validation['request'])
    paths=[checked(x) for x in validation['captured_exports']]
    require([x['role'] for x in validation['captured_exports']]==[
        'native_variation_design','native_weighted_rows','native_local_observation_design'],'Export role/order changed')
    evidence={x['role']:checked(x) for x in validation['native_evidence']}
    factor_path=evidence['native_factor'];require(str(factor_path).endswith('.factor.json'),'Wrong native factor suffix')
    prefix=str(factor_path).removesuffix('.factor.json')
    info=read_json(factor_path);diagnostics=read_json(evidence['native_rank']);c=validation['comparison']
    dense_path=checked(c['dense_reference'])
    with np.load(dense_path,allow_pickle=False) as arrays:
        require(set(arrays.files)=={'covariance','posterior_sd','factor','rhs','scales','dynamic'},'Dense archive fields changed')
        values={k:arrays[k].copy() for k in arrays.files}
    require(np.array_equal(values['factor'],read_factor(prefix+'.R.bin'))
            and np.array_equal(values['rhs'],read_factor(prefix+'.rhs.bin').ravel())
            and np.array_equal(values['scales'],np.asarray(info['scales']))
            and np.array_equal(values['dynamic'],np.asarray(info['dynamic'],dtype=bool)),
            'Preserved dense reference differs from original native factor')
    require(info['orthogonal_energy']==c['dense_orthogonal_residual_energy']
            and diagnostics['reduced_rows']==c['effective_rows'],'Original residual energy/row count changed')
    point=Linearization(values['factor'],values['rhs'],values['scales'],values['dynamic'],
        int(c['effective_rows']),0.,float(info['orthogonal_energy']),c['support_hash'],None,
        metadata={'factor_prefix':prefix,'diagnostics':diagnostics}).validate()
    require(linearization_digest(point)==c['linearization_sha256'],'Captured linearization digest changed')
    require(len(point.scales)<=200,'Bounded diagnostic refuses more than200 original coordinates')
    covariance=selected_covariance(point,np.eye(len(point.scales)))
    require(np.array_equal(covariance,values['covariance'])
            and np.array_equal(np.sqrt(np.diag(covariance)),values['posterior_sd']),
            'Preserved undamped dense covariance does not reproduce')
    supplementary=[artifact_record(role,p) for role,p in (
        ('original_native_factor',prefix+'.R.bin'),('original_native_rhs',prefix+'.rhs.bin'),
        ('original_coordinate_metadata',prefix+'.parameters.tsv'))]
    return point,paths,supplementary


def compare(point,paths,solver,output,deadline=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    require(not any(output.iterdir()),'Comparison output must be fresh')
    covariance=selected_covariance(point,np.eye(len(point.scales)));sd=np.sqrt(np.diag(covariance))
    result={'rank':certify_rank(point),'profiles':[],'damping':list(DAMPING),
        'physical_evaluations':0,'nuisance_profile_evaluations':0,'linearization_sha256':linearization_digest(point),
        'map_tolerance_posterior_sd':1e-7,'relative_covariance_tolerance':1e-8,
        'residual_tolerance':2e-12,'objective_scope':'Only the unchanged linearized weighted residual and optimization damping; no nonlinear physical objective is evaluated.',
        'gradient_scope':'Diagnostic |R.T rhs| infinity norm with unit denominator (the reloaded point uses objective=0). This is not the original objective-normalized nonlinear gradient or a convergence criterion.'}
    for seconds in PERIODS:
        baseline,base_receipt=build_graph(point,*paths,segment_seconds=seconds)
        identity=ledger_identity(baseline)
        with Path(paths[0]).open() as stream:meta=json.loads(next(stream))
        for offset in OFFSETS:
            folder=output/f'period-{seconds}-offset-{int(offset)}';folder.mkdir()
            graph,receipt=build_graph(point,*paths,segment_seconds=seconds,segment_offset_seconds=offset)
            require(ledger_identity(graph)==identity,'Shift changed a variable, equality or stochastic coefficient ledger')
            coverage=interior_movement(baseline,graph,base_receipt['native_epochs']-1,float(meta['dt']))
            write_json(folder/'graph.json',receipt)
            system=SegmentedLinearSystem(graph,solver,folder/'solves',deadline=deadline)
            shifted=replace(point,linear_system=system).validate()
            profile={'segment_seconds':seconds,'segment_offset_seconds':offset,'ledger_identity':identity,
                     'coverage':coverage,'graph':artifact_record('shifted_graph',folder/'graph.json'),
                     'trials':[],'calls':system.calls,'numerically_equivalent':False}
            result['profiles'].append(profile);write_json(output/'progress.json',result)
            for damping in DAMPING:
                expected,predicted,gradient=proposal(point,damping);actual,pred,grad=proposal(shifted,damping)
                payload=read_json(system.calls[-1]['output']);z=expected/point.scales
                energy=float(np.linalg.norm(point.rhs-point.factor@z)**2+point.residual_energy
                    +damping*np.linalg.norm(z[point.dynamic])**2)
                trial={'damping':damping,'maximum_map_discrepancy_posterior_sd':float(np.max(abs(actual-expected)/sd)),
                    'normalized_residual_energy_difference':abs(payload['residual_energy']-energy)/max(1.,abs(energy)),
                    'normalized_orthogonal_residual_energy_difference':abs(payload['orthogonal_residual_energy']-energy)/max(1.,abs(energy)),
                    'maximum_equality_backward_error':payload['equality_max_backward_error'],
                    'equality_residual_normalization':'max_i |d_i-E_i*x| / (|d_i|+sum_j |E_ij*x_j|); zero denominator gives zero',
                    'dense_full_residual_energy':energy,'dense_predicted_reduction':predicted,
                    'segmented_predicted_reduction':pred,'dense_gradient_unit_denominator':gradient,'segmented_gradient_unit_denominator':grad,
                    'native_result':artifact_record('shifted_native_result',system.calls[-1]['output'])}
                profile['trials'].append(trial);write_json(output/'progress.json',result)
                require(np.isfinite(trial['maximum_map_discrepancy_posterior_sd']) and trial['maximum_map_discrepancy_posterior_sd']<1e-7,'Shifted MAP exceeds1e-7 posterior SD')
                for key in ('normalized_residual_energy_difference','normalized_orthogonal_residual_energy_difference','maximum_equality_backward_error'):
                    require(np.isfinite(trial[key]) and 0<=trial[key]<2e-12,'Shifted residual/equality exceeds fixed2e-12: '+key)
                require(grad==gradient,'Diagnostic unit-denominator gradient definition changed')
            actual_cov=selected_covariance(shifted,np.eye(len(point.scales)))
            relative=float(np.linalg.norm(actual_cov-covariance)/np.linalg.norm(covariance))
            profile['covariance_relative_error']=relative;profile['covariance_optimization_damping']=0.
            np.savez_compressed(folder/'covariance.npz',covariance=actual_cov)
            profile['covariance']=artifact_record('shifted_covariance',folder/'covariance.npz')
            write_json(output/'progress.json',result)
            require(np.isfinite(relative) and relative<1e-8,'Shifted undamped covariance exceeds1e-8 relative error')
            profile['numerically_equivalent']=True
            profile['status']='equivalent_with_interior_movement' if coverage['adequate'] else 'equivalent_without_interior_coverage'
            write_json(output/'progress.json',result)
    result['numerically_equivalent']=True
    result['interior_coverage_by_period']={str(p):any(x['coverage']['adequate'] for x in result['profiles'] if x['segment_seconds']==p) for p in PERIODS}
    result['coverage_adequate']=all(result['interior_coverage_by_period'].values())
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('controller','pipeline','validation','source','solver','output'):ap.add_argument('--'+n,type=Path,required=True)
    for n in ('controller','pipeline','validation','source','solver'):ap.add_argument('--'+n+'-sha256',required=True)
    a=ap.parse_args(argv);require(not a.output.exists() and not a.output.is_symlink(),'Choose a new diagnostic output; preserve prior outcomes')
    a.output.mkdir(parents=True)
    receipt={'schema':'orbit-poc-shifted-native-cuts-diagnostic-v1','status':'failed','passed':False,
        'scope':'Separate post-suite identical captured-linearization cut diagnostic; not a benchmark attempt or extra physical evaluation',
        'physical_evaluations':0,'nuisance_profile_evaluations':0,'fit_covariance_authorized':False,'source_sha256':a.source_sha256}
    pins={n:{'path':str(getattr(a,n)),'sha256':getattr(a,n+'_sha256')} for n in ('controller','pipeline','validation','solver')}
    receipt['inputs']=pins;before=[]
    try:
        validation=terminal_gate(pins['controller'],pins['pipeline'],pins['validation'])
        point,paths,supplementary=load_captured(validation,a.source,a.source_sha256,a.solver,a.solver_sha256)
        before=[*pins.values(),*supplementary,*validation['captured_exports'],*validation['native_evidence'],validation['comparison']['dense_reference'],validation['source'],validation['native'],validation['request'],validation['original_request']]
        for pin in before:checked(pin)
        receipt['supplementary_input_pins']=supplementary
        receipt['comparison']=compare(point,paths,a.solver,a.output/'comparison',deadline=time.monotonic()+1800.)
        for pin in before:checked(pin)
        require(source_snapshot(a.source)['sha256']==a.source_sha256,'Source changed during diagnostic')
        receipt['status']='passed' if receipt['comparison']['coverage_adequate'] else 'coverage_inadequate'
        receipt['passed']=receipt['status']=='passed'
    except Exception as error:receipt.update(error=repr(error),traceback=traceback.format_exc())
    write_json(a.output/'validation.json',receipt)
    print(json.dumps({'status':receipt['status'],'passed':receipt['passed']}),flush=True)
    return 0 if receipt['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
