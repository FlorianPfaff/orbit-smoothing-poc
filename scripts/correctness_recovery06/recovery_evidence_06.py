"""Pure provenance checks for recovery06; no process signalling or estimator work."""
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
    """Prove a bounded, explicitly pinned numerical correction, never new data."""
    lineage=read_pin(mapped_pin(pins.get('correction_lineage'),execution),'correction_lineage')
    require(lineage.get('schema')=='orbit-poc-correctness-correction-lineage-v1','Unknown correction lineage')
    require(lineage.get('original_source_freeze')==pins.get('source_freeze')
            and lineage.get('new_source_freeze')==pins.get('new_source_freeze'),
            'Correction lineage does not bind both source freezes')
    newfreeze=read_pin(mapped_pin(pins.get('new_source_freeze'),execution),'new_source_freeze')
    require(newfreeze.get('source')==current and current.get('sha256')==pins.get('source_sha256')
            and isinstance(current.get('files'),dict) and len(current['files'])==pins.get('source_file_count')
            and digest(current['files'])==current['sha256'],'Corrected source inventory differs from its freeze')
    old=original.get('files');new=current['files']
    require(isinstance(old,dict) and len(old)==758 and digest(old)==original.get('sha256'),
            'Original 758-file inventory is inconsistent')
    require(set(old)<=set(new),'Numerical correction cannot delete frozen source files')
    changes={name:{'before':old.get(name),'after':value} for name,value in new.items() if old.get(name)!=value}
    allowed=pins.get('allowed_correction_paths')
    require(isinstance(allowed,list) and allowed and len(allowed)==len(set(allowed))
            and all(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts for name in allowed)
            and set(changes)==set(allowed) and changes==lineage.get('changes'),
            'Numerical correction differs from the exact reviewed path/hash inventory')
    protected=[name for name in old if name.startswith('tests/') or name.startswith('scripts/validate_numerics_')]
    protected.append('src/orbit_poc/numerics/backend.py')
    require(all(old.get(name)==new.get(name) for name in protected),'Original tests or numerical gate implementation changed')
    require(lineage.get('original_source_sha256')==original['sha256']
            and lineage.get('new_source_sha256')==current['sha256'],'Correction lineage source digests differ')
    failures={}
    for number in ('04','05'):
        pin=artifact(lineage.get('failed_pipeline'+number),'failed pipeline'+number)
        record=read_pin(mapped_pin(pin,execution),'failed_pipeline'+number)
        require(record.get('status')=='failed' and record.get('finished_at')
                and record.get('final_cleanup',{}).get('verified') is True and record.get('source')==original,
                'Preserved failed attempt does not bind the original source and terminal cleanup')
        require(record.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'},
                'Prior recovery cannot invent campaign resumption')
        failures[number]={'pin':pin,'record':record}
    require(not failures['04']['record'].get('native') and failures['05']['record'].get('native'),
            'Prior infrastructure and scientific failures were conflated')
    require(failures['04']['pin']['sha256']!=failures['05']['pin']['sha256'],
            'Distinct prior failures share an execution identity')
    regression=pins.get('regression_suite')
    require(isinstance(regression,dict) and set(regression)=={'files','expected_count'}
            and isinstance(regression['files'],list) and regression['files']
            and type(regression['expected_count']) is int and regression['expected_count']>0
            and len(regression['files'])==len(set(regression['files']))
            and all(name.startswith('tests/test_') and name.endswith('.py') and name in new and name not in old for name in regression['files']),
            'Separate correction regression suite must use new frozen test files')
    return {'classification':'separately_versioned_numerical_correction','lineage':lineage,
            'new_source_freeze':newfreeze,'changed_paths':sorted(changes),'preserved_failed_attempts':failures,
            'regression_suite':regression,'scientific_gate_acceptance':False}


def validate_recovery(pipeline, pins, read_pin):
    """Read pins through callback; return classifications, never live-host claims.

    read_pin(pin, role) must verify exact bytes before decoding a JSON object.
    Historical canonical paths are resolved only through pinned execution aliases.
    A remote host's boot must match its admission; it need not equal the local
    post-restart boot in the interruption record.
    """
    require(pins.get('schema')=='orbit-poc-correctness-candidate06-pins-v1','Unknown recovery pins schema')
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
