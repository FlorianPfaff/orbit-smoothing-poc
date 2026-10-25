"""Freeze reviewed composition controls and unchanged scientific identities."""
from pathlib import Path
import datetime, importlib.util, json
B=Path('/mnt/d/orbit-v41-recovery02');C=B/'validation-controls07'
spec=importlib.util.spec_from_file_location('controls07_freeze',C/'reference_gates09.py');g=importlib.util.module_from_spec(spec)
exec(compile((C/'reference_gates09.py').read_bytes(),str(C/'reference_gates09.py'),'exec'),g.__dict__)
pin,read,save=g.pin,g.read,g.save
old_path=B/'reference-gates12-run01/plan.json';old=read(old_path);previous_path=B/'reference-gates13-run01/plan.json';previous=read(previous_path)
probe=read(C/'namespace-probe01/result.json');plan=read(C/'namespace-probe01/plan.json')
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert probe['passed'] and probe['sources_unchanged'] and probe['old_plan_unchanged'] and probe['boot_unchanged'] and probe['boot_id']==boot
checks=[]
for row in old['pins']:
 expected={k:row[k] for k in ('path','sha256','bytes') if k in row};actual=pin(row['path'])
 checks.append({'expected':expected,'actual':actual,'passed':all(actual[k]==v for k,v in expected.items())})
assert len(checks)==110 and all(r['passed'] for r in checks)
overlays=[]
for prior,row in zip(previous['directory_overlays'],plan['directory_overlays']):
 current=g.overlay_mount_identity(row['target'])
 stable=current==row['mount_identity']
 same={k:v for k,v in prior.items() if k!='mount_identity'}=={k:v for k,v in row.items() if k!='mount_identity'}
 overlays.append({'target':row['target'],'initial':row['mount_identity'],'current':current,'stable':stable,'source_target_inventory_unchanged':same})
assert len(overlays)==3 and all(r['stable'] and r['source_target_inventory_unchanged'] for r in overlays)
semantic=lambda rows:[(r['target'],r['source']['sha256'],r['source']['bytes']) for r in rows]
assert semantic(old['aliases'])==semantic(plan['aliases'])==semantic(previous['aliases'])
changed=sum(a['source']['path']!=b['source']['path'] for a,b in zip(old['aliases'],plan['aliases']))
assert len(plan['aliases'])==367 and changed==90
o=g.objective_output_api();o.verify(plan,g.overlay_mount_identity);absent=not(o.TARGET/'output').exists();assert absent
roles=read(B/'validation-controls05/post-move-role-audit01.json');artifacts=[]
for row in roles['input_artifacts']:
 expected=row['expected'];actual=pin(expected['path']);raw=Path(expected['path']).read_bytes()
 artifacts.append({'expected':expected,'actual':actual,'passed':all(actual[k]==v for k,v in expected.items()),'embedded_dropbox':b'dropbox' in raw.lower()})
assert len(artifacts)==14 and all(r['passed'] and not r['embedded_dropbox'] for r in artifacts)
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
post={'schema':'orbit-reference-composition07-post-probe-v1','created_at':now,'passed':True,'boot_id':boot,
 'previous110pins':checks,'overlay_identity_checks':overlays,'objective_parent_verified':True,'host_original_output_absent':absent,
 'old_plan':pin(old_path),'immediate_preparation_plan':pin(previous_path),'probe':pin(C/'namespace-probe01/result.json'),
 'probe_plan':pin(C/'namespace-probe01/plan.json'),'aliases_count':367,'alias_source_canonical_paths_changed':90,
 'alias_target_hash_size_semantics_unchanged':True,'input_artifacts':artifacts,'embedded_dropbox_artifacts':0,
 'original_scientific_argv_byte_identity':False,'argv_path_only_proof':pin(B/'validation-controls05/post-move-role-audit01.json'),
 'runtime_cache_metadata_disclosure':pin(B/'validation-review04/runtime13-loader-metadata-review01.json'),'native_launched':False}
save(C/'post-probe-identity01.json',post)
controls=['reference_gates09.py','reference_recovery.py','reference_runtime09.py','reference_storage09.py','reference_objective_output.py']
tests=['test_reference_gates09.py','test_reference_recovery.py','test_reference_storage09.py','test_reference_objective_output.py','test_reference_composed_parent.py','run_tests04.py','namespace_composition_probe.py','stdio-probe/probe.py','finalize_controls.py']
freeze={'schema':'orbit-reference-composition-controls07-freeze-v1','created_at':now,'boot_id':boot,
 'active_change':'Separate composed namespace identity from original host identity. Preserve complete host tree+data identity; require exact mirror backing, all pinned data members and all unchanged non-data members in composed namespaces. Objective mode checks stage-specific output backing. New private mapping/plan schemas and fresh stdio receipt path only; numerical source/binary/models/settings/limits unchanged.',
 'controls':[pin(C/n) for n in controls],'test_and_probe_sources':[pin(C/n) for n in tests],
 'pure_test_receipt':pin(C/'tests04-result.json'),'independent_test_receipt':pin(B/'validation-review04/controls07-independent-tests01.json'),
 'namespace_smoke_receipt':pin(C/'namespace-probe01/result.json'),'stdio_probe_receipt':pin(C/'stdio-probe/result.json'),
 'post_probe_identity':pin(C/'post-probe-identity01.json'),'restored_roles':pin(B/'validation-controls05/post-move-role-audit01.json'),
 'parent_control_freeze':pin(B/'validation-controls06/controls-freeze01.json'),
 'independent_failure_review':pin(B/'validation-review04/recovery13-preflight-failure-review01.json'),
 'runtime_cache_disclosure':pin(B/'validation-review04/runtime13-loader-metadata-review01.json'),
 'native_loader_review':pin(B/'validation-review04/runtime13-groops-loader-review01.json'),
 'preserved_preparation_failure':[pin(B/p) for p in ['preparation04/result.json','preparation04/step01.log','preparation04/step02.log','reference-gates13-run01/plan.json','reference-gates13-run01/prepared/preflight-execution.json','reference-gates13-run01/prepared/preflight.log']],
 'preserved_local_probe_attempts':[pin(C/p) for p in ['diagnosis00-launch-failure.json','diagnosis01/failure.json','diagnose_parent_overlay.py','diagnosis02/result.json','diagnosis02/command.json','diagnosis02/prepared/child-result.json','diagnose_parent_overlay02.py','test-creation01-failure.json','tests02-result.json','tests03-result.json','tests03-source-preservation.json','tests03-source/test_reference_composed_parent.py']],
 'preceding_native_attempt':[pin(B/'reference-gates12-run01'/p) for p in ['freeze.json','result.json','detached-result.json','objective-log_drag_ou/strict-result.json','objective-pulses/strict-result.json']],
 'boot_transition':pin(B/'boot-transition03/record.json'),'original_interrupted_source_anchor':'/mnt/d/orbit-v41-recovery01/reference-gates10-run01',
 'all_eight_fresh_required':True,'old_results_reused':False,'native_launched':False,'launch_authority':False,'release_authority':False,
 'validation_scope':'147 pure control tests include tiny checked_plan fixtures. Four actual namespace modes check readonly flags and data composition. Complete real-runtime preflight remains required for fresh run14.'}
save(C/'controls-freeze01.json',freeze)
print(json.dumps({'freeze':pin(C/'controls-freeze01.json'),'preparation_driver':pin(B/'preparation05/prepare_recovery.py')}))
