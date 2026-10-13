from pathlib import Path
from copy import deepcopy
import importlib.util,json,sys,os,shutil
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
project=Path('outputs/orbit-smoothing-poc').resolve();sys.path.insert(0,str(project/'src'))
from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import read_json,write_json,file_hash,source_snapshot
spec=importlib.util.spec_from_file_location('harness',project/'scripts/validate_comparison_native.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)
root=Path('/tmp/orbit-v3-common-preprocessing').resolve();root.mkdir(exist_ok=True)
binary=root/'groops';shutil.copy2('/tmp/orbit-v3-runtime/groops-build/groops',binary)
expected='274bd986bb55a1ac358f4c5fcf789683ac4084b157159ea4380059bd95b45554'
assert file_hash(binary)==expected
source=source_snapshot()['sha256'];records=[]
raw_source=Path('/tmp/orbit-v3-coherent-functional-v2/normal/prepare/observations/data_manifest.json')
raw=read_json(raw_source);raw['native_simulation'].pop('transmitter_cache',None)
raw['diagnostic_reuse']={'original_manifest':str(raw_source),'sha256':file_hash(raw_source),'change':'remove obsolete native transmitter-conversion cache; regenerate all native inputs with the current frozen binary; observation bytes unchanged'}
raw_manifest=root/'verified_observation_reuse.json';write_json(raw_manifest,raw)
for label in ['normal','masked']:
    prior=Path('/tmp/orbit-v3-coherent-functional-v2')/label
    request=read_json(prior/'preparation_request.json')
    request['backend'].update(groops_executable=str(binary),retain_native_diagnostics=True)
    request['expected_native_binary_sha256']=expected
    out=root/label;write_json(out/'preparation_request.json',request)
    prepared=harness.prepare_existing_observations(raw_manifest,request,out/'prepare')
    write_json(out/'preparation_result.json',prepared)
    print(label,'fresh prepared',flush=True)
    for setting in ['default','alternate']:
        for method,base_parameters in harness.METHODS.items():
            parameters=deepcopy(base_parameters)
            if setting=='alternate':
                if method=='groops_pulses':parameters['sigma_velocity_m_s']=2e-4
                else:parameters.update(tau_seconds=3600.,sigma_log_density=.6)
            folder=out/setting/method
            job={**request,'method':method,'parameters':parameters,'source_hash':source,
                 'estimation_inputs':prepared['estimation_inputs'],
                 **{k:prepared[k] for k in ['force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash']}}
            write_json(folder/'request.json',job)
            result=backend.fit_job(job,folder);write_json(folder/'result.json',result)
            iterations=read_json(folder/'outer_iterations.json')['iterations'] if (folder/'outer_iterations.json').exists() else []
            audits=[x.get('preprocessing_audit_sha256') for x in iterations]
            record={'mask':label,'setting':setting,'method':method,'parameters':parameters,
                    'status':result.get('status'),'converged':result.get('converged'),'covariance_valid':result.get('covariance_valid'),
                    'error':result.get('error'),'iterations':len(iterations),'audit_sha256':audits[-1] if audits else None,
                    'audit_stable_across_outer_iterations':bool(audits) and None not in audits and len(set(audits))==1,
                    'result_sha256':file_hash(folder/'result.json')}
            records.append(record)
            report={'scope':'Engineering check of common native preprocessing; no calibration or scientific comparison',
                    'complete':len(records)==8,'records':records,'native_binary_sha256':expected,'source_sha256_at_start':source,
                    'original_observation_manifest_sha256':file_hash(raw_source),'observations_regenerated':False,
                    'bootstrap_recomputed_after_each_mask':True,'reference_or_truth_used_in_fitting':False}
            if len(records)==8:
                groups={mask:{r['audit_sha256'] for r in records if r['mask']==mask} for mask in ['normal','masked']}
                report['same_audit_across_methods_and_hyperparameters']={mask:len(group)==1 and None not in group for mask,group in groups.items()}
                report['passed']=all(r['converged'] and r['covariance_valid'] and r['audit_stable_across_outer_iterations'] for r in records) and all(report['same_audit_across_methods_and_hyperparameters'].values())
            write_json(root/'common_preprocessing.json',report)
            print(label,setting,method,record,flush=True)
            if result.get('status') in ['failed','blocked']:raise RuntimeError(record)
