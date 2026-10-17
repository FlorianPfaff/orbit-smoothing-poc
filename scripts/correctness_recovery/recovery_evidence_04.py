"""Pure provenance checks for recovery04; no process signalling or estimator work."""
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


def validate_recovery(pipeline, pins, read_pin):
    """Read pins through callback; return classifications, never live-host claims.

    read_pin(pin, role) must verify exact bytes before decoding a JSON object.
    Historical canonical paths are resolved only through pinned execution aliases.
    A remote host's boot must match its admission; it need not equal the local
    post-restart boot in the interruption record.
    """
    require(pins.get('schema')=='orbit-poc-correctness-candidate04-pins-v1','Unknown recovery pins schema')
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
    require(pins.get('expected_native_test_count')==106 and pins.get('additional_native_tests')==ADDITIONAL_TESTS
            and pins.get('source_file_count')==758,'Recovery changed frozen test or source inventory')
    require(priorpins.get('source_sha256')==pins.get('source_sha256')
            and priorpins.get('expected_native_test_count')==106 and priorpins.get('additional_native_tests')==ADDITIONAL_TESTS
            and isinstance(pins.get('input_artifacts'),dict) and len(pins['input_artifacts'])==14
            and priorpins.get('input_artifacts')==pins['input_artifacts'],'Scientific inputs differ from interrupted candidate03')
    inventory=pipeline.get('source') or {};frozen=sourcefreeze.get('source') or {}
    require(isinstance(inventory.get('files'),dict) and len(inventory['files'])==758
            and digest(inventory['files'])==inventory.get('sha256')==pins.get('source_sha256')
            and inventory==frozen,'Fresh executed source differs from the preserved 758-file candidate')
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
    require(interrupted.get('source')==frozen,'Interrupted source differs from recovery snapshot')
    return {'status':'verified','execution':execution,'admission':admission,
            'interrupted_previous':{'classification':'interrupted_before_native_validation',
                'record':restart,'pipeline':interrupted,'pipeline_pin':interrupted_pin},
            'campaign_resume':'not_applicable','strict_convergence_or_covariance_approved':False}
