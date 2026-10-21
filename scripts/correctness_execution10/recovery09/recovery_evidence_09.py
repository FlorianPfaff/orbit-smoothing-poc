"""Pure provenance checks for recovery09; no process signalling or estimator work."""
from pathlib import Path
import hashlib
import json
import re

ADDITIONAL_TESTS=['tests/test_numerics_geometry_precision.py',
                  'tests/test_numerics_synthetic_force_arithmetic.py']


def require(value, message):
    if not value: raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def artifact(value, label):
    require(isinstance(value,dict) and isinstance(value.get('path'),str)
            and Path(value['path']).is_absolute() and '..' not in Path(value['path']).parts
            and isinstance(value.get('sha256'),str) and re.fullmatch('[0-9a-f]{64}',value['sha256']),
            'Missing or invalid artifact pin: '+label)
    return value


def host_path(path, execution):
    path=Path(path)
    matches=[];targets=set()
    for row in execution.get('read_only_bindings',[]):
        require(isinstance(row,dict) and set(row)=={'source','target'},'Invalid execution alias')
        source,target=Path(row['source']),Path(row['target'])
        require(source.is_absolute() and target.is_absolute() and '..' not in source.parts
                and '..' not in target.parts and target not in targets,'Ambiguous execution alias')
        targets.add(target)
        if path==target or target in path.parents:
            matches.append((len(target.parts),source/path.relative_to(target)))
    return max(matches,key=lambda item:item[0])[1] if matches else path


def mapped_pin(pin, execution):
    pin=artifact(pin,'mapped artifact')
    return {'path':str(host_path(pin['path'],execution)),'sha256':pin['sha256']}


def validate_correction(pins, original, current, execution, read_pin):
    """Verify candidate09 against candidate07 and retain the complete04–08 history."""
    def read(value, role):
        return read_pin(mapped_pin(artifact(value, role), execution), role)
    lineage=read(pins.get('correction_lineage'),'correction_lineage')
    require(lineage.get('schema')=='orbit-poc-correctness-correction-lineage-v3','Unknown correction lineage')
    require(all(lineage.get(key)==pins.get(pin) for key,pin in (
            ('original_source_freeze','source_freeze'),('previous_source_freeze','previous_source_freeze'),
            ('new_source_freeze','new_source_freeze'),('previous_correction_lineage','previous_correction_lineage'))),
            'Correction lineage does not bind source freezes and previous lineage')
    priorfreeze=read(pins.get('previous_source_freeze'),'previous_source_freeze')
    previous=priorfreeze.get('source') or {}
    previous_regression={'files':['tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py',
            'tests/test_numerics_precise_residual.py','tests/test_numerics_precise_objective.py'],'expected_count':40}
    require(priorfreeze.get('schema')=='orbit-poc-candidate07-source-freeze-v1'
            and isinstance(priorfreeze.get('commit'),str) and re.fullmatch('[0-9a-f]{40}',priorfreeze['commit'])
            and priorfreeze.get('original_native_test_count')==106
            and isinstance(previous.get('files'),dict) and len(previous['files'])==771
            and digest(previous['files'])==previous.get('sha256')
            and priorfreeze.get('regression_suite')==previous_regression,
            'Previous07 source freeze is inconsistent')
    past=read(pins.get('previous_correction_lineage'),'previous_correction_lineage')
    require(past.get('schema')=='orbit-poc-correctness-correction-lineage-v2'
            and past.get('original_source_freeze')==pins['source_freeze']
            and artifact(past.get('new_source_freeze'),'historical new freeze')['sha256']==pins['previous_source_freeze']['sha256']
            and read(past['new_source_freeze'],'historical_new_source_freeze')==priorfreeze,
            'Previous correction lineage does not bind the immediate source')
    historicalfreeze=read(past.get('previous_source_freeze'),'historical_source_freeze')
    historical=historicalfreeze.get('source') or {}
    require(historicalfreeze.get('schema')=='orbit-poc-candidate06-source-freeze-v1'
            and isinstance(historicalfreeze.get('commit'),str) and re.fullmatch('[0-9a-f]{40}',historicalfreeze['commit'])
            and historicalfreeze['commit']!=priorfreeze['commit']
            and isinstance(historical.get('files'),dict) and len(historical['files'])==764
            and digest(historical['files'])==historical.get('sha256')
            and historicalfreeze.get('regression_suite')=={
                'files':['tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py'],
                'expected_count':18},'Historical06 source freeze is inconsistent')
    old=original.get('files');history=historical['files'];before=previous['files']
    require(isinstance(old,dict) and len(old)==758 and digest(old)==original.get('sha256'),
            'Original758-file inventory is inconsistent')
    require(set(old)<=set(history) and set(history)<=set(before),
            'Previous lineage deleted original source files')
    pastchanges={name:{'before':history.get(name),'after':value} for name,value in before.items() if history.get(name)!=value}
    require(past.get('changes')==pastchanges and past.get('original_source_sha256')==original['sha256']
            and past.get('previous_source_sha256')==historical['sha256']
            and past.get('new_source_sha256')==previous['sha256'],
            'Previous correction lineage path/hash inventory changed')
    def protected(names):
        return [name for name in names if name.startswith('tests/') or name.startswith('scripts/validate_numerics_')] + ['src/orbit_poc/numerics/backend.py']
    require(all(old.get(name)==history.get(name) for name in protected(old))
            and all(history.get(name)==before.get(name) for name in protected(history)),
            'Original tests or numerical gate implementation changed in historical source')
    require(all(name in before and name not in history for name in previous_regression['files'][2:]),
            'Previous07 correction regression inventory is inconsistent')
    newfreeze=read(pins.get('new_source_freeze'),'new_source_freeze')
    require(newfreeze.get('schema')=='orbit-poc-candidate09-source-freeze-v1'
            and isinstance(newfreeze.get('commit'),str) and re.fullmatch('[0-9a-f]{40}',newfreeze['commit'])
            and newfreeze.get('commit')!=priorfreeze['commit']
            and newfreeze.get('original_native_test_count')==106
            and newfreeze.get('source')==current and current.get('sha256')==pins.get('source_sha256')
            and isinstance(current.get('files'),dict) and len(current['files'])==pins.get('source_file_count')
            and digest(current['files'])==current['sha256'],'Corrected source inventory differs from its freeze')
    new=current['files']
    require(set(before)<=set(new),'Numerical correction cannot delete frozen source files')
    changes={name:{'before':before.get(name),'after':value} for name,value in new.items() if before.get(name)!=value}
    allowed=pins.get('allowed_correction_paths')
    require(isinstance(allowed,list) and allowed and len(allowed)==len(set(allowed))
            and all(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts for name in allowed)
            and set(changes)==set(allowed) and changes==lineage.get('changes'),
            'Numerical correction differs from the exact reviewed incremental path/hash inventory')
    require(all(before.get(name)==new.get(name) for name in protected(before)),
            'Original tests or numerical gate implementation changed')
    require(lineage.get('original_source_sha256')==original['sha256']
            and lineage.get('previous_source_sha256')==previous['sha256']
            and lineage.get('new_source_sha256')==current['sha256'],'Correction lineage source digests differ')
    failures={}
    for number in ('04','05','06','07','08'):
        pin=artifact(lineage.get('failed_pipeline'+number),'failed pipeline'+number)
        if number in ('04','05','06'):
            require(pin==past.get('failed_pipeline'+number),'Earlier failed attempt pin changed from preserved lineage')
        record=read(pin,'failed_pipeline'+number)
        expected=original if number in ('04','05') else historical if number=='06' else previous
        require(record.get('status')=='failed' and record.get('finished_at')
                and record.get('final_cleanup',{}).get('verified') is True and record.get('source')==expected,
                'Preserved failed attempt does not bind its source and terminal cleanup')
        require(record.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'},
                'Prior recovery cannot invent campaign resumption')
        require(bool(record.get('native'))==(number in ('05','06','08')),
                'Prior infrastructure and scientific failures were conflated')
        failures[number]={'pin':pin,'record':record}
    require(len({item['pin']['sha256'] for item in failures.values()})==5,
            'Distinct prior failures share an execution identity')
    regression=pins.get('regression_suite')
    require(isinstance(regression,dict) and set(regression)=={'files','expected_count'}
            and regression==newfreeze.get('regression_suite')
            and isinstance(regression['files'],list) and regression['files']
            and type(regression['expected_count']) is int and regression['expected_count']>40
            and len(regression['files'])==len(set(regression['files']))
            and set(previous_regression['files'])<set(regression['files'])
            and all(name.startswith('tests/test_') and name.endswith('.py') and name in new and name not in old for name in regression['files'])
            and all(name not in before for name in set(regression['files'])-set(previous_regression['files'])),
            'Separate correction regression suite must preserve40 and add new frozen test files')
    return {'classification':'separately_versioned_numerical_correction','lineage':lineage,
            'previous_source_freeze':priorfreeze,'new_source_freeze':newfreeze,
            'previous_correction_lineage':past,'historical_source_freeze':historicalfreeze,
            'changed_paths':sorted(changes),'preserved_failed_attempts':failures,
            'regression_suite':regression,'scientific_gate_acceptance':False}


def validate_recovery(pipeline, pins, read_pin):
    """Read pins through callback; return classifications, never live-host claims.

    read_pin(pin, role) must verify exact bytes before decoding a JSON object.
    Historical canonical paths are resolved only through pinned execution aliases.
    A remote host's boot must match its admission; it need not equal the local
    post-restart boot in the interruption record.
    """
    require(pins.get('schema')=='orbit-poc-correctness-candidate09-pins-v1','Unknown recovery pins schema')
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==pins.get('recovery_verifier_sha256'),
            'Recovery verifier differs from the frozen correction controls')
    execution_pin=artifact(pipeline.get('execution'),'execution')
    require(execution_pin['sha256']==pins.get('execution_sha256'),'Execution pin differs from frozen controls')
    execution=read_pin(execution_pin,'execution')
    require(execution.get('schema')=='orbit-poc-correctness-execution-v1','Unknown execution schema')
    host=execution.get('host') or {}
    require(set(host)=={'hostname','boot_id'} and all(isinstance(v,str) and v for v in host.values()),'Missing execution host identity')
    paths=execution.get('paths') or {}
    require(all(isinstance(paths.get(k),str) and Path(paths[k]).is_absolute() for k in ('root','run','control','source','binaries')),'Missing execution layout')
    admission=pipeline.get('admission') or {}
    require(admission.get('status')=='admitted' and all(admission.get(k)==v for k,v in host.items())
            and admission.get('conflicting_processes')==[] and admission.get('observed_at')
            and isinstance(admission.get('driver_identity'),dict) and admission['driver_identity'].get('pid')
            and admission['driver_identity'].get('start_ticks') is not None,
            'Missing or mismatched current-host admission')
    require(admission.get('policy')=='serial_owned_pid_namespace_no_external_native_orbit_workload_v1',
            'Unexpected workload admission policy')
    require(pipeline.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'}
            and not any(pipeline.get(k) for k in ('pause_receipt','resume_error','resume_withheld')),
            'Recovery must not fabricate a campaign resume')
    priorpins=read_pin(mapped_pin(pins.get('candidate03_pins'),execution),'candidate03_pins')
    sourcefreeze=read_pin(mapped_pin(pins.get('source_freeze'),execution),'source_freeze')
    require(pins.get('expected_native_test_count')==106 and pins.get('additional_native_tests')==ADDITIONAL_TESTS,
            'Recovery changed the original 106-test inventory')
    require(priorpins.get('source_sha256')==(sourcefreeze.get('source') or {}).get('sha256')
            and priorpins.get('expected_native_test_count')==106 and priorpins.get('additional_native_tests')==ADDITIONAL_TESTS
            and isinstance(pins.get('input_artifacts'),dict) and len(pins['input_artifacts'])==14
            and priorpins.get('input_artifacts')==pins['input_artifacts'],'Scientific inputs differ from interrupted candidate03')
    inventory=pipeline.get('source') or {};frozen=sourcefreeze.get('source') or {}
    correction=validate_correction(pins,frozen,inventory,execution,read_pin)
    lineage_pin=artifact(pipeline.get('correction_lineage'),'executed correction lineage')
    require(lineage_pin['sha256']==pins['correction_lineage']['sha256']
            and host_path(lineage_pin['path'],execution).resolve()==host_path(pins['correction_lineage']['path'],execution).resolve(),
            'Executed correction lineage differs from frozen pin')
    interruption_pin=artifact(pipeline.get('interruption_record'),'interruption')
    frozen_interruption=artifact(pins.get('interruption_record'),'frozen interruption')
    require(interruption_pin['sha256']==frozen_interruption['sha256']
            and host_path(interruption_pin['path'],execution).resolve()==host_path(frozen_interruption['path'],execution).resolve(),
            'Interruption record differs from frozen pin')
    restart=read_pin(mapped_pin(interruption_pin,execution),'interruption_record')
    require(restart.get('status')=='interrupted_by_host_restart'
            and isinstance(restart.get('previous_boot_id'),str) and restart['previous_boot_id']
            and isinstance(restart.get('observed_boot_id'),str) and restart['observed_boot_id']
            and restart['previous_boot_id']!=restart['observed_boot_id']
            and restart.get('native_tests_produced') is False and restart.get('native_binary_produced') is False,
            'Interrupted-build record does not establish a changed boot before native validation')
    interrupted_pin=artifact(restart.get('prior_pipeline'),'interrupted pipeline')
    interrupted=read_pin(mapped_pin(interrupted_pin,execution),'interrupted_pipeline03')
    steps=interrupted.get('steps') or []
    require(interrupted.get('status')=='running' and not interrupted.get('native')
            and isinstance(steps,list) and not any(s.get('name')=='native-tests' for s in steps),
            'Interruption claim disagrees with preserved unfinished pipeline')
    require(not any(s.get('name')=='build' and s.get('status')=='passed' for s in steps),
            'Interrupted attempt unexpectedly contains a successful build')
    require(interrupted.get('source')==frozen,'Interrupted source differs from the original source freeze')
    return {'status':'verified','execution':execution,'admission':admission,
            'interrupted_previous':{'classification':'interrupted_before_native_validation',
                'record':restart,'pipeline':interrupted,'pipeline_pin':interrupted_pin},
            'correction':correction,
            'campaign_resume':'not_applicable','strict_convergence_or_covariance_approved':False}
