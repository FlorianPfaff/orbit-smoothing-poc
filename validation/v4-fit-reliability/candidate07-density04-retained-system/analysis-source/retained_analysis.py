"""Saved qr.11 retained-system audit. No native execution or covariance authority."""
from pathlib import Path
import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
import sys
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
INPUTS_SHA = '9c20d0a7ef4395a84bb974b2e39c1276186e552f1a0ddf9874342389e0995714'
HISTORY_SHA = 'f6d798f502625b22ac9274259d3d0ddc44ab2cf8895209ebc3d81ddda0432877'
RETENTION_SHA = '47c96a7eb1aeca6074568e328bf10ba48c9b844737a1e62b4f100189e1c47a1e'
MAP_LIMIT_SD = 1e-7
SOURCE_ROOT = Path('/mnt/d/orbit-v41-recovery02/candidate07-cold-density04/cold-density/fit')
POINT = SOURCE_ROOT/'point-033-trial-030'
PREFIX = POINT/'qr.11'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def libraries():
    # Exact, unchanged import closure is frozen under vendor/production.
    for path in (HERE/'vendor', HERE/'vendor/production'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import selected_terminal_audit as reader
    from orbit_poc.numerics import optimizer
    need(Path(reader.__file__).resolve()==HERE/'vendor/selected_terminal_audit.py', 'wrong reader')
    need(Path(optimizer.__file__).resolve()==HERE/'vendor/production/orbit_poc/numerics/optimizer.py', 'wrong production optimizer')
    return reader, optimizer


def verified_inputs(root):
    need(digest(HERE/'inputs.json')==INPUTS_SHA, 'manifest identity differs')
    manifest=json.loads((HERE/'inputs.json').read_text())
    need(manifest['schema']=='density04-retained-analysis-inputs-v1' and manifest['owner']=='point-033-trial-030/qr.11', 'wrong input owner')
    paths={}; pins={}
    for pin in manifest['inputs']:
        role=pin['role']; relative=Path(pin['staged_relative']); path=root/relative
        need(role not in paths and relative.name==pin['sha256']+'.dat' and len(relative.parts)==1, 'invalid role/path')
        need(path.is_file() and not path.is_symlink() and path.resolve(strict=True)==path, 'missing or aliased input')
        need(path.stat().st_size==pin['bytes'] and digest(path)==pin['sha256'], 'input changed: '+role)
        paths[role]=path; pins[role]=pin
    need(len(paths)==31 and pins['history']['sha256']==HISTORY_SHA and pins['retention']['sha256']==RETENTION_SHA, 'incomplete ownership inputs')
    return paths, pins


def read_tsv(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def vector(reader, path, size):
    value=np.array(reader.matrix(path), dtype=float)
    need(value.shape==(size,1), 'native vector shape differs')
    return value[:,0]


def density_table(path):
    rows=[line.split() for line in path.read_text().splitlines() if line.strip()]
    need(len(rows)==61 and all(len(row)==2 for row in rows), 'density state shape differs')
    epochs=[Decimal(row[0]) for row in rows]
    need(all(x.is_finite() for x in epochs) and all(a<b for a,b in zip(epochs,epochs[1:])), 'density epochs differ')
    values=np.array([float(row[1]) for row in rows]); need(np.isfinite(values).all(),'nonfinite density state')
    return epochs,values


def verify_chart(info, parameters, R, b):
    need(info['schema']=='orbit-poc-qr-factor-v1' and info['rows']==info['columns']==146, 'not the full retained factor')
    need(info['retained_global_indices']==list(range(240,386)) and info['local_global_indices']==list(range(240)), 'global/local chart differs')
    need(info['dynamic']==[True]*67+[False]*79 and all(type(v) is bool for v in info['dynamic']), 'dynamic flags differ')
    need(R.shape==(146,146) and b.shape==(146,) and np.isfinite(R).all() and np.isfinite(b).all(), 'invalid retained matrix')
    need(np.array_equal(R,np.triu(R)), 'nonzero lower triangle')
    need(len(parameters)==386 and [p['index'] for p in parameters]==[str(i) for i in range(386)], 'parameter inventory differs')
    scales=np.array(info['scales']); need(scales.shape==(146,) and np.isfinite(scales).all() and np.all(scales>0), 'invalid native scales')
    selected=parameters[240:386]
    need(len({p['name'] for p in parameters})==386, 'duplicate parameter name')
    for i,p in enumerate(selected):
        need(float(p['scale'])==scales[i] and p['dynamic']==str(int(i<67)), 'scale/dynamic metadata differs')
    need(all(p['unit']=='1' and p['name'].startswith('GRACEC:logDensity::') and p['coordinate_convention']=='direct_native_coordinate' for p in selected[:61]), 'density units/order differ')
    for i,(kind,axis) in enumerate((kind,axis) for kind in ('position','velocity') for axis in 'xyz'):
        p=selected[61+i]
        need(p['name']==f'GRACEC:arc0.{kind}0.{axis}::' and p['unit']=='m', 'native initial-state chart differs')
        convention='direct_native_coordinate' if kind=='position' else 'initial_velocity_times_arc_scale;SI_map=initial_design_artifact'
        need(p['coordinate_convention']==convention, 'initial velocity convention differs')
    need(info['local_elimination']=='independent_epoch_clock_vtec_qr', 'different local elimination')
    return scales, np.array(info['dynamic'],dtype=bool)


def rank_certificate(R, effective_rows):
    values=np.linalg.svd(R,compute_uv=False)
    threshold=np.finfo(float).eps*max(effective_rows,len(values))*values[0]
    status='full_rank' if values[-1]>10*threshold else ('rank_deficient' if values[-1]<=threshold else 'unresolved_rank')
    need(status=='full_rank', 'undamped rank '+status)
    return {'status':status,'rank':int(np.count_nonzero(values>threshold)), 'effective_rows':effective_rows,
            'minimum_singular_value':float(values[-1]),'maximum_singular_value':float(values[0]),'threshold':float(threshold)}


def householder_solve(A, b, reader):
    q,r=np.linalg.qr(A,mode='reduced')
    return np.array(reader.triangular(r.tolist(),(q.T@b).tolist()))


def joint_solve(R,b,dynamic,lam,reader):
    need(math.isfinite(lam) and lam>=0, 'invalid damping')
    penalty=np.eye(R.shape[1])[dynamic]*math.sqrt(lam)
    return householder_solve(np.vstack((R,penalty)),np.r_[b,np.zeros(sum(dynamic))],reader)


def profiled_solve(R,b,dynamic,lam,reader):
    need(math.isfinite(lam) and lam>=0, 'invalid damping')
    di=np.flatnonzero(dynamic); ni=np.flatnonzero(~dynamic)
    need(len(di)>0 and len(ni)>0, 'both retained blocks required')
    q,r=np.linalg.qr(R[:,ni],mode='complete')
    target=q.T@b; design=q.T@R[:,di]; n=len(ni)
    # Exactly eliminate retained nuisance columns, retaining their conditional.
    a=design[n:]; y=target[n:]
    zd=householder_solve(np.vstack((a,math.sqrt(lam)*np.eye(len(di)))),np.r_[y,np.zeros(len(di))],reader)
    zn=np.array(reader.triangular(r[:n,:].tolist(),(target[:n]-design[:n]@zd).tolist()))
    z=np.empty(R.shape[1]); z[di]=zd; z[ni]=zn
    return z, {'profiled_dynamic_rows':len(a),'profiled_dynamic_columns':len(di),
               'retained_nuisance_columns':n,'conditional_coupling_frobenius':float(np.linalg.norm(design[:n])),
               'original_eliminated_local_recovery_attempted':False}


def step_diagnostics(R,b,z,dynamic,lam,objective,energy):
    residual=R@z-b
    undamped=R.T@residual
    damped=undamped+lam*dynamic.astype(float)*z
    change=R@z
    return {'undamped_predicted_reduction':float(b@change-.5*(change@change)),
            'retained_residual_cost_with_original_constant':float(.5*(residual@residual+energy)),
            'damped_stationarity_inf':float(np.max(np.abs(damped))),
            'undamped_residual_gradient_inf':float(np.max(np.abs(undamped))),
            'original_zero_step_normalized_gradient':float(np.max(np.abs(R.T@b))/max(1.,math.sqrt(2*objective))),
            'scaled_dynamic_norm':float(np.linalg.norm(z[dynamic])),
            'scaled_nuisance_norm':float(np.linalg.norm(z[~dynamic]))}


def sd_error(a,b,sd):
    need(a.shape==b.shape==sd.shape and all(np.isfinite(v).all() for v in (a,b,sd)) and np.all(sd>0), 'invalid comparison normalization')
    return float(np.max(np.abs(a-b)/sd))


def physical_mapping(native,design,initial,force):
    need(native.shape==(67,) and design.shape==(6,67) and initial.shape==(6,) and force.shape==(61,), 'physical mapping shape differs')
    need(all(np.isfinite(a).all() for a in (native,design,initial,force)), 'nonfinite physical mapping')
    return initial+design@native, force+native[:61]


def source_derived_lambda(history):
    need(history['accepted_iterations']==22 and history['trial_evaluations']==30 and len(history['history'])==30, 'wrong history snapshot')
    last=history['history'][-1]
    need(last['trial']==30 and last['accepted'] is True and last['objective_trial']==108511.68952280404, 'last accepted owner differs')
    need(last['damping']==0.014243095839601297 and last['gain_ratio']==0.9720673144802097, 'source-derived damping inputs differ')
    return last['damping']*max(1/3,1-(2*last['gain_ratio']-1)**3)


def analyze(root):
    paths,pins=verified_inputs(root); reader,production=libraries()
    read=lambda role:json.loads(paths[role].read_text())
    history=read('history'); retention=read('retention'); lam=source_derived_lambda(history)
    need(retention['events'][-1]['protected_paths']==[str(PREFIX)+'.R.bin'], 'accepted-factor retention owner differs')
    receipt=read('qr.profile.json'); execution=read('profile.execution.json'); confirmation=read('nuisance_confirmation.json')
    need(receipt['nuisance_converged'] is True and receipt['nuisance_floor_limited'] is False and receipt['fresh_full_nuisance_confirmed'] is True and receipt['iterations']==10, 'strict nuisance owner absent')
    need(execution['returncode']==0 and execution['timed_out'] is False and execution['command'][-1]==str(POINT/'profile.xml'), 'native profile ownership differs')
    need(confirmation['stationary_without_update'] is True and confirmation['nuisance_floor_limited'] is False, 'fresh full confirmation differs')
    info=read('factor.json'); diag=read('diagnostics.json'); cost=read('profile.json'); parameters=read_tsv(paths['parameters.tsv'])
    R=np.array(reader.binary_matrix(paths['R.bin'])); b=np.array(reader.binary_matrix(paths['rhs.bin']))
    need(b.shape==(146,1) and pins['rhs.bin']['sha256']==pins['z.bin']['sha256'], 'rhs/z transformed-target role differs'); b=b[:,0]
    scales,dynamic=verify_chart(info,parameters,R,b)
    need(diag['lambda']==0 and diag['rank_status']=='full' and diag['reduced_rows']==7885 and diag['retained_parameters']==146, 'wrong undamped rank metadata')
    objective=cost['direct_cost']; need(objective==history['history'][-1]['objective_trial'], 'objective/history owner differs')
    point=production.Linearization(R,b,scales,dynamic,7885,objective,info['orthogonal_energy'],'owned-qr11',None).validate()
    rank=rank_certificate(R,7885); native_rank=production.certify_rank(point)
    # Error normalization only: no covariance is emitted or accepted.
    inverse=np.column_stack([reader.triangular(R.tolist(),row.tolist()) for row in np.eye(146)])
    sd_z=np.linalg.norm(inverse,axis=1); sd_native=scales*sd_z
    delta=read_tsv(paths['delta.tsv']); need(len(delta)==386 and [p['index'] for p in delta]==[str(i) for i in range(386)], 'native delta global indices differ')
    native_undamped=np.array([float(p['undamped']) for p in delta[240:386]])
    need(np.isfinite(native_undamped).all(), 'nonfinite native correction')
    reference=vector(reader,paths['closure-02/reference.txt'],67)
    design=np.array(reader.matrix(paths['closure-02/initial_design.txt']))
    initial=vector(reader,paths['physical_initial.txt'],6)
    density_epochs,force=density_table(paths['density_state'])
    trial_epochs,trial_force=density_table(paths['trial031_density_state'])
    need(density_epochs==trial_epochs,'unaccepted trial density grid differs')
    # Density is baked into nominal propagation; these 67-vectors are native
    # correction references, not the accumulated 61-knot physical density state.
    need(np.array_equal(vector(reader,paths['fixed_force.txt'],67),np.zeros(67)) and
         np.array_equal(vector(reader,paths['trial031_force'],67),np.zeros(67)) and
         np.array_equal(reference[:61],np.zeros(61)), 'density native correction reference differs')
    mapping_sd=np.linalg.norm((design*scales[:67])@inverse[:67],axis=1)
    result={'schema':'density04-retained-factor-analysis-v1','status':'failed','owner':str(PREFIX),'rank':rank,'production_rank':native_rank,
            'original_orthogonal_residual_energy':info['orthogonal_energy'],'original_direct_objective':objective,
            'input_manifest_sha256':INPUTS_SHA,'source_derived_next_lambda':lam,'source_derived_lambda_directly_logged':False,
            'threshold_posterior_sd':MAP_LIMIT_SD,'steps':[],'gates':{},'original_row_assembly_verified':False,
            'missing_initial_factor_verified':False,'local_parameter_recovery_verified':False,'covariance_authority':False,
            'nonlinear_convergence':False,'state_installed':False,'native_runs':0,'release_authority':False}
    for index,value in enumerate((0.,lam)):
        z=joint_solve(R,b,dynamic,value,reader); profiled,coupling=profiled_solve(R,b,dynamic,value,reader)
        actual,prediction,gradient=production.proposal(point,value); native=scales*z
        archived=vector(reader,paths[f'proposal-00{index}/parameters.txt'],67)-reference
        metrics=read(f'proposal-00{index}/proposal-retention.json')['metrics']
        errors={'joint_vs_production':sd_error(native,actual,sd_native),
                'joint_vs_profiled':sd_error(z,profiled,sd_z),
                'dynamic_vs_archived_proposal':sd_error(native[:67],archived,sd_native[:67])}
        if index==0: errors['joint_vs_native_undamped_delta']=sd_error(native,native_undamped,sd_native)
        expected_initial,expected_force=physical_mapping(native[:67],design,initial,force)
        recorded_initial,recorded_force=physical_mapping(archived,design,initial,force)
        errors['mapped_initial_vs_archived_proposal']=sd_error(expected_initial,recorded_initial,mapping_sd)
        if index==1:
            # Only unaccepted trial31 input attribution; no partial factor is consumed.
            errors['mapped_initial_vs_unaccepted_trial031_input']=sd_error(expected_initial,vector(reader,paths['trial031_initial'],6),mapping_sd)
            errors['density_vs_unaccepted_trial031_input']=sd_error(expected_force,trial_force,sd_native[:61])
        for name,error in errors.items():result['gates'][f'lambda_index_{index}:{name}']=error<MAP_LIMIT_SD
        calculated=step_diagnostics(R,b,z,dynamic,value,objective,info['orthogonal_energy'])
        profiled_diagnostics=step_diagnostics(R,b,profiled,dynamic,value,objective,info['orthogonal_energy'])
        nuisance_errors={unit:float(max(abs(native[i]-actual[i]) for i,p in enumerate(parameters[240:386]) if i>=67 and p['unit']==unit)) for unit in sorted({p['unit'] for p in parameters[307:386]})}
        result['steps'].append({'lambda':value,'errors_posterior_sd':errors,'diagnostics':calculated,'profiled_diagnostics':profiled_diagnostics,'profiled_coupling':coupling,
              'production_undamped_prediction':prediction,'production_zero_step_normalized_gradient':gradient,
              'density_update_max':float(max(abs(native[:61]))),'density_update_norm_dimensionless':float(np.linalg.norm(native[:61])),
              'native_initial_coordinate_norm_m':float(np.linalg.norm(native[61:67])),
              'initial_delta_si':(expected_initial-initial).tolist(),
              'nuisance_difference_by_native_unit':nuisance_errors,'archived_native_trajectory_metrics':metrics,
              'native_trajectory_recomputed':False})
    result['scaled_dynamic_norm_decreased']=result['steps'][1]['diagnostics']['scaled_dynamic_norm']<=result['steps'][0]['diagnostics']['scaled_dynamic_norm']
    result['source_derived_lambda_confirmed_by_archived_proposal']=result['gates']['lambda_index_1:dynamic_vs_archived_proposal']
    # A numerical consistency result, never an orbital covariance/convergence grant.
    result['status']='retained_system_checks_passed' if all(result['gates'].values()) else 'retained_system_check_failed'
    verified_inputs(root)
    result['all_31_inputs_unchanged_after']=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();need(args.input_root.is_absolute() and args.input_root.resolve(strict=True)==args.input_root,'canonical input root required')
    need(not args.output.exists(),'fresh output required')
    result={'schema':'density04-retained-factor-analysis-v1','status':'failed','native_runs':0,'covariance_authority':False,'state_installed':False,'release_authority':False}
    try:result=analyze(args.input_root)
    except BaseException as error:result.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        try:verified_inputs(args.input_root);result['all_31_inputs_unchanged_after']=True
        except BaseException as error:
            result.update(status='failed',all_31_inputs_unchanged_after=False,post_input_identity_error=repr(error))
    with args.output.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    return 0 if result['status']=='retained_system_checks_passed' else 1

if __name__=='__main__':raise SystemExit(main())
