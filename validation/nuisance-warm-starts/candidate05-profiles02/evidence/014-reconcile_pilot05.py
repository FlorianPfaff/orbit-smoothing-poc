#!/usr/bin/env python3
"""Read-only reconciliation of the narrowly audited pilot05 bookkeeping case.

Never runs the native binary or alters the original result. A separate outcome
audit is mandatory before the preparation adapter can use this record.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys

SCHEMA='orbit-poc-native-prior-fixture-reconciliation-v1'
AUDIT_SCHEMA='independent-pilot05-reconciliation-outcome-review-v1'
NATIVE_AUDIT_SCHEMA='independent-prior-pilot05-native-outcome-and-bookkeeping-review-v1'

def require(value,message):
    if not value:raise ValueError(message)

def read(path):
    def pairs(items):
        out={}
        for key,value in items:
            require(key not in out,'Duplicate JSON key');out[key]=value
        return out
    def invalid(value):raise ValueError('Nonfinite JSON '+value)
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=invalid)

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
def pin(path):
    path=Path(path).absolute();before=path.stat();resolved=path.resolve(strict=True);digest=sha(path);after=path.stat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after) and path.resolve(strict=True)==resolved,'File changed while hashing')
    return {'path':str(path),'sha256':digest,'bytes':before.st_size}
def verify(record):
    require(type(record.get('bytes')) is int and record['bytes']>=0,'Invalid pinned byte count')
    require(pin(record['path'])==record,'Pinned file changed: '+record['path']);return Path(record['path'])
def save(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def complete_v1(value):
    require(value.get('schema')=='orbit-poc-segmented-supervision-v1','Unknown supervisor schema')
    require(value.get('status')=='complete' and type(value.get('returncode')) is int and value['returncode']==0,
            'Supervisor did not complete successfully')
    require('timed_out' not in value or value['timed_out'] is False,'Contradictory timeout field')
    require('error' not in value and value.get('signals_received')==[],'Supervisor error/interruption evidence')
    cleanup=value.get('cleanup',{})
    require(value.get('owned_process_group_cleaned') is True and cleanup.get('verified') is True
            and cleanup.get('remaining')==[] and cleanup.get('empty_tree_certificate')=='kernel_ECHILD'
            and cleanup.get('hard_kill') is False and cleanup.get('signals')==[] and 'error' not in cleanup,
            'Supervisor lacks clean unsignalled owned closure')
    require(type(value.get('elapsed_seconds')) in (int,float) and math.isfinite(value['elapsed_seconds'])
            and value['elapsed_seconds']>0,'Invalid completed elapsed time')
    require(type(value.get('peak_process_tree_rss_bytes')) is int and value['peak_process_tree_rss_bytes']>=0,
            'Invalid supervisor memory evidence')
    require(isinstance(value.get('worker'),dict) and type(value['worker'].get('pid')) is int and value['worker']['pid']>0,
            'Missing native worker identity')

def narrow_bookkeeping_case(original,supervisor,repeated):
    require(original.get('passed') is False,'Only original aggregate false may be reconciled')
    require(original.get('inputs_unchanged') is True and 'identity_error' in original and original['identity_error'] is None
            and original.get('release_authority') is False,'Original pilot identity/authority differs')
    require(canonical(original['execution'])==canonical(supervisor),'Embedded and actual supervisor differ')
    complete_v1(supervisor)
    require('timed_out' not in supervisor,'Not the known absent-field bookkeeping case')
    old=original['extraction']
    require(old.get('passed') is True and repeated.get('passed') is True and
            old.get('release_authority') is False and old.get('covariance_authority') is False and old.get('issues')==[],
            'Original/re-extracted strict feasibility did not pass')
    require(canonical(old)==canonical(repeated),'Independent read-only extraction differs')
    priors=repeated['native_prior_rows']
    require(set(priors)=={'code_bias_full_constraint','tec_bias_full_constraint'},'Missing/extraneous native prior source')
    require(all(type(v['rows']) is int and v['rows']>0 and type(v['rhs_squared']) in (int,float)
                and math.isfinite(v['rhs_squared']) and v['rhs_squared']>0 for v in priors.values()),
            'Positive actual native prior evidence required')
    require(repeated.get('datum_evidence'),'Actual native datum evidence required')

def output_inventory(root):
    records=[]
    for path in sorted(Path(root).rglob('*')):
        require(not path.is_symlink(),'Pilot output alias forbidden')
        if path.is_file():records.append(pin(path))
        else:require(path.is_dir(),'Nonregular pilot output')
    return records

def build_reconciliation(original_path,pilot_control,native_audit_path):
    original_record=pin(original_path);control_record=pin(pilot_control);audit_record=pin(native_audit_path)
    original=read(original_path);root=Path(original_path).resolve().parent
    require(Path(original_path).absolute()==root/'result.json','Original result must retain its attempt identity')
    before=output_inventory(root)
    plan=read(verify(original['plan']));require(original['plan']['path']==str(root/'freeze.json'),'Pilot freeze root differs')
    require(plan['schema']=='orbit-poc-native-prior-fixture-pilot-v1' and plan['release_authority'] is False,'Unknown pilot plan')
    require(control_record in plan['protected'],'Original pilot control is not protected')
    for record in plan['protected']:verify(record)
    for path,digest in plan['patched_source'].items():require(sha(path)==digest,'Patched native source changed')
    for record in original['thin_output_inventory']:verify(record)
    verify(plan['config']);require(plan['config']['path']==str(root/'config.xml'),'Pilot config root differs')
    module=load_module(pilot_control,'preserved_pilot05_extractor')
    require(Path(module.OUT)==root and module.JOB==plan['original_job']['id'],'Not the preserved pilot05 controller/point')
    oldroot=Path(plan['original_job']['root']);oldconfig=oldroot/'config.xml'
    require(sha(oldconfig)==plan['original_job']['profile_sha256'],'Original profile configuration changed')
    require((root/'config.xml').read_text()==module.transform(oldconfig.read_text(),oldroot,root),'Pilot scientific XML variant differs')
    checker_record=pin(module.CHECKER);guard_record=pin(module.launch.__file__)
    require(checker_record in plan['protected'] and guard_record==plan['launch_guard'] and guard_record in plan['protected'],
            'Extractor/launch code is not the protected implementation')
    require(original['native_launch_mode']==plan['native_launch_mode']==module.launch.MODE,'Prelaunch mode differs')
    launch=read(verify(original['native_launch']));verify(original['launch_binding'])
    binding=module.launch.checked_launch(original['launch_binding'],launch,expected_environment=plan['environment'])
    require(binding['freeze']==original['plan'] and binding['config']==plan['config'] and binding['guard']==plan['launch_guard']
            and binding['job_id']==module.JOB and binding['root']==str(root),'Launch binding attribution differs')
    require(binding['native'] in plan['protected'],'Native executable is not protected')
    require(plan['environment']['ORBIT_POC_NUISANCE_WARM_STARTS']=='0'
            and {k for k in plan['environment'] if k.startswith('ORBIT_POC_NUISANCE_WARM')}=={'ORBIT_POC_NUISANCE_WARM_STARTS'},
            'Pilot must remain warm-disabled')
    supervisor_record=pin(root/'supervisor.json');supervisor=read(supervisor_record['path'])
    supervisor_plan_record=pin(root/'supervisor.plan.json');supervisor_plan=read(supervisor_plan_record['path'])
    command=module.launch.launch_command(str(module.sys.executable),binding['guard']['path'],original['launch_binding'])
    # The frozen command names its protected interpreter; current Python aliases
    # must have the same exact executable identity, as in the original controller.
    require(pin(module.sys.executable) in plan['protected'],'Reconciliation interpreter differs from protected pilot interpreter')
    require(original['command']==supervisor['argv']==supervisor_plan['argv']==command,'Supervisor/launch command differs')
    require(supervisor_plan['schema']=='orbit-poc-segmented-supervision-plan-v1' and supervisor['plan_sha256']==supervisor_plan_record['sha256']
            and supervisor['boot_id']==supervisor_plan['boot_id'] and supervisor['helper_sha256']==supervisor_plan['helper_sha256'],
            'Supervisor plan/helper identity differs')
    supervisor_sources=[r for r in plan['protected'] if r['path'].endswith('/src/orbit_poc/segmented/supervisor.py') and r['sha256']==supervisor['helper_sha256']]
    require(supervisor_sources,'Protected supervisor implementation missing')
    require(supervisor_plan['cwd']==supervisor_plan['working_directory']==str(root)
            and supervisor_plan['receipt_path']==str(root/'supervisor.json') and supervisor_plan['log_path']==str(root/'profile.log'),
            'Supervisor paths differ')
    require(plan['limits']=={'cpu':0,'threads':1,'timeout_seconds':900,'max_process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3}
            and all(supervisor_plan[k]==plan['limits'][k] for k in ('timeout_seconds','max_process_tree_rss_bytes','min_free_disk_bytes')),
            'Pilot resource limits changed')
    complete_v1(supervisor);require(launch['pid']==supervisor['worker']['pid'],'Launch PID differs from owned worker')
    checker=load_module(module.CHECKER,'preserved_pilot05_checker');repeated=module.extract(root,checker)
    require(module.launch.datum_evidence(root)==repeated.get('datum_evidence'),'Native datum evidence differs')
    narrow_bookkeeping_case(original,supervisor,repeated)
    audit=read(native_audit_path)
    require(audit['schema']==NATIVE_AUDIT_SCHEMA and audit['status']=='native_prior_feasibility_passed_aggregate_false_from_supervisor_schema_mismatch'
            and audit['independent_native_prior_feasibility_passed'] is True and audit['reported_aggregate_passed'] is False
            and audit['wholefit_admission'] is False and audit['profile_campaign_admission'] is False and audit['release_authority'] is False,
            'Independent actual native outcome audit is not the narrow accepted case')
    expected={'original_result':original_record,'freeze':original['plan'],'launch_binding':original['launch_binding'],
              'native_launch':original['native_launch'],'supervisor_receipt':supervisor_record,'supervisor_plan':supervisor_plan_record,'native':binding['native']}
    require(all(audit.get(k)==v for k,v in expected.items()),'Independent native outcome audit pins differ')
    for value in audit.values():
        if isinstance(value,dict) and {'path','sha256','bytes'}<=value.keys():verify(value)
    require(canonical(before)==canonical(output_inventory(root)),'Pilot output changed during reconciliation')
    verify(original_record);verify(control_record);verify(audit_record)
    return {'schema':SCHEMA,'status':'native_prior_feasibility_reconciled_pending_independent_preparation_audit',
            'controller':pin(__file__),'original_result':original_record,'pilot_control':control_record,
            'original_native_outcome_audit':audit_record,**{k:v for k,v in expected.items() if k!='original_result'},
            'checker':checker_record,'guard':guard_record,'output_inventory':before,'extraction':repeated,
            'reported_original_aggregate_passed':False,'reconciled_native_prior_feasibility_passed':True,
            'supervisor_completion_basis':{'schema':supervisor['schema'],'status':supervisor['status'],'returncode':supervisor['returncode'],
                'timed_out_field_present':False,'owned_process_group_cleaned':True,'empty_tree_certificate':'kernel_ECHILD',
                'reason':'Supervisor v1 reports timeout through status; the original controller required an absent timed_out key to be false.'},
            'profile_preparation_authority':False,'wholefit_admission':False,'release_authority':False,'native_reruns':0,
            'scope':'Native prior-fixture feasibility only. Original aggregate false and all native artifacts remain unchanged.'}

def verify_for_preparation(reconciliation_path,audit_path,pilot_control):
    record=pin(reconciliation_path);value=read(reconciliation_path);audit_record=pin(audit_path);audit=read(audit_path)
    require(value['schema']==SCHEMA and value['profile_preparation_authority'] is False and value['wholefit_admission'] is False
            and value['release_authority'] is False and value['reconciled_native_prior_feasibility_passed'] is True,
            'Invalid reconciliation scope/decision')
    require(audit['schema']==AUDIT_SCHEMA and audit['accepted_for_profile_preparation'] is True
            and audit['wholefit_admission'] is False and audit['release_authority'] is False,'Independent reconciliation admission missing')
    expected={'reconciliation_result':record,'original_result':value['original_result'],'pilot_control':pin(pilot_control),
              'original_native_outcome_audit':value['original_native_outcome_audit']}
    require(all(audit.get(k)==v for k,v in expected.items()),'Independent reconciliation audit pins differ')
    for r in expected.values():verify(r)
    fresh=build_reconciliation(value['original_result']['path'],pilot_control,value['original_native_outcome_audit']['path'])
    require(canonical(fresh)==canonical(value),'Reconciliation no longer reproduces exact original evidence')
    verify(record);verify(audit_record)
    return value,load_module(pilot_control,'admitted_pilot05_fixture_transform')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('original-result','pilot-control','native-outcome-audit','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();require(not a.output.absolute().is_relative_to(a.original_result.resolve().parent),'Reconciliation output must be outside preserved attempt')
    value=build_reconciliation(a.original_result,a.pilot_control,a.native_outcome_audit)
    save(a.output,value);print(json.dumps({'reconciliation':pin(a.output),'original_reported_passed':False,'native_reruns':0,'preparation_audit_required':True}))

if __name__=='__main__':main()
