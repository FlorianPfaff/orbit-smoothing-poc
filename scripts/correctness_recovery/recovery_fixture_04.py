"""Fabricated tiny recovery records only, imported exclusively by tests."""
from pathlib import Path
import hashlib
import json
import shutil

HERE=Path(__file__).parent

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True))
    return path

def pin(path):
    path=Path(path);return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def install(root,pipeline):
    root=Path(root);control=root/'control';control.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(HERE/'recovery_evidence_04.py',control/'recovery_evidence_04.py')
    files={f'fixture-{i}':'a'*64 for i in range(758)}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    source={'files':files,'sha256':digest}
    inputs={}
    for role in ('prior_validation','initial_state','density_request','pulse_request','old_nuisance_replay','candidate1_nuisance_replay','flight_prepared','full_day_request','old_replay_variational','old_replay_reference','old_replay_density','new_replay_variational','new_replay_reference','new_replay_density'):
        path=root/'validation-02/pipeline.json' if role=='prior_validation' else root/'mock-inputs'/role
        if not path.exists():write(path,{'role':role})
        inputs[role]=pin(path)
    additional=['tests/test_numerics_geometry_precision.py','tests/test_numerics_synthetic_force_arithmetic.py']
    prior=write(control/'candidate03-pins.json',{'source_sha256':digest,'input_artifacts':inputs,'expected_native_test_count':106,'additional_native_tests':additional})
    freeze=write(control/'candidate03-source-freeze.json',{'source':source})
    interrupted=write(root/'validation-03/pipeline.json',{'status':'running','source':source,'steps':[{'name':'build','status':'running'}]})
    interruption=write(control/'interruption-03.json',{'status':'interrupted_by_host_restart','previous_boot_id':'old-local-boot','observed_boot_id':'new-local-boot','native_tests_produced':False,'native_binary_produced':False,'prior_pipeline':pin(interrupted)})
    execution=write(control/'candidate04-execution.json',{'schema':'orbit-poc-correctness-execution-v1','host':{'hostname':'remote-fixture','boot_id':'remote-boot'},'paths':{k:str(root/v) for k,v in {'root':'.','run':'validation-04','control':'control','source':'source-04','binaries':'binaries-04'}.items()},'read_only_bindings':[]})
    controls={}
    for name,key in (('validate_candidate_04.py','driver_sha256'),('with_correctness_namespace_04.py','wrapper_sha256')):
        path=control/name
        if not path.exists():path.write_text('# fabricated controller')
        controls[key]=pin(path)['sha256']
    pins={'schema':'orbit-poc-correctness-candidate04-pins-v1','source_sha256':digest,'source_file_count':758,'expected_native_test_count':106,'additional_native_tests':additional,'input_artifacts':inputs,'execution_sha256':pin(execution)['sha256'],'candidate03_pins':pin(prior),'source_freeze':pin(freeze),'interruption_record':pin(interruption),**controls}
    pinpath=write(control/'candidate04-pins.json',pins)
    pipeline.update(source=source,execution=pin(execution),interruption_record=pin(interruption),required_pins=pin(pinpath),
        helper_sha256=controls['driver_sha256'],wrapper={'sha256':controls['wrapper_sha256']},
        prior_failed_validation=inputs['prior_validation'],resume={'status':'not_applicable','reason':'no_campaign_running'},
        admission={'status':'admitted','hostname':'remote-fixture','boot_id':'remote-boot','observed_at':'2026-10-15T01:00:00Z','driver_identity':{'pid':123,'start_ticks':789},'conflicting_processes':[],'policy':'serial_owned_pid_namespace_no_external_native_orbit_workload_v1'})
    pipeline.pop('pause_receipt',None)
    write(root/'validation-04/pipeline.json',pipeline)
    for name in ('candidate04-control-validation.json','candidate04-independent-control-review.json'):write(control/name,{'passed':True})
    return pipeline,pins
