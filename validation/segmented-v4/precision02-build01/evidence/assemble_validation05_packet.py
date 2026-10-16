"""Fresh384-file validation snapshot for one measured native precision correction."""
from pathlib import Path
import copy,datetime,hashlib,json,shutil,sys,tarfile
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';OLD=B/'validation-04-packet';P=B/'validation-05-packet';R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-05');REMOTE=R.parent
HEADER='groops/extension/sixStateTangent.h';EXPECTED='1590e13ff3f69cb6841af8341737b8d52c4d618592070b61b4ae6516f2ea4c28'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def save(p,v):
 with p.open('x')as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n')
def main():
 base=json.loads((C/'validation05-base-readback01.json').read_text());runtime_rows=json.loads((C/'precision-runtime01-readback.json').read_text());runtime=runtime_rows['provenance.json']['value'];old=base['source_freeze']['value'];assert len(old['source']['files'])==384 and sha(B/'source'/HEADER)==EXPECTED
 assert not P.exists();pc=P/'control';pc.mkdir(parents=True);dest=P/'source';dest.mkdir()
 for n,h in old['source']['files'].items():
  p=OLD/'source'/n;assert sha(p)==h;out=dest/n;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
 shutil.copy2(B/'source'/HEADER,dest/HEADER);files={str(p.relative_to(dest)):sha(p)for p in sorted(dest.rglob('*'))if p.is_file()};assert {n for n in files if files[n]!=old['source']['files'][n]}=={HEADER}
 sys.path.insert(0,str(dest/'src'));from orbit_poc.comparison.protocol import source_snapshot
 prior={k:base['source_freeze'][k]for k in ('path','sha256')}
 freeze={'schema':'orbit-poc-v4-validation-source-freeze-v1','scope':'Fresh unchanged14gate validation of precision correction; no acceptance inheritance','source':{'files':files,'sha256':digest(files)},'comparison_source':source_snapshot(dest),'previous_source':prior,'allowed_changed_paths':[HEADER],'source_commit':'677c68c','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'capture_method':'Verified exact prior384file snapshot plus single committed native header','helper_sha256':sha(__file__)};save(pc/'source-freeze.json',freeze)
 helpers=('run_segmented_validation02.py','launch_segmented_validation02.py','validation05_startup_probe.py','smoke_segmented_validation05.py','stage_segmented_validation05.py','assemble_validation05_packet.py')
 for n in helpers:shutil.copy2(C/n,pc/n)
 for src,n in [('closure-owned-driver09.py','owned_driver09.py'),('closure-with-correctness-namespace09.py','with_correctness_namespace_09.py')]:shutil.copy2(C/src,pc/n)
 stages=['native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses']
 provenance={'schema':'orbit-poc-v4-native-rebuild-provenance-v1','status':'verified_actual_rebuild','previous_source':prior,'previous_config':{k:base['config'][k]for k in ('path','sha256')},'actual_build_result':runtime['actual_build_result'],'runtime_provenance':{k:runtime_rows['provenance.json'][k]for k in ('path','sha256')},'native_inputs':{k:h for k,h in files.items()if k.startswith('groops/')or k=='scripts/build_groops.py'},'fixed_stage_names':stages,'scope':'Only one native header differs; exact baseline relink and all27 dependent translation units verified from actual build. Complete runtime remains independently checked by startup and public validation. No claim of all70 unchanged.'};save(pc/'native-rebuild-provenance.json',provenance)
 e=copy.deepcopy(base['execution']['value']);e['paths'].update(root=str(R),source=str(R/'source'),control=str(R/'control'),wrapper=str(R/'control/with_correctness_namespace_09.py'),native_source=str(R/'preparation'),build=str(R/'cache'),binaries=str(R/'artifacts'),run=str(R/'run'),temporary=str(R/'temporary'))
 for root in (REMOTE/'validation-04',REMOTE/'runtime-precision-01',REMOTE/'tangent-precision-01'):
  bind={'source':str(root),'target':str(root)}
  if bind not in e['read_only_bindings']:e['read_only_bindings'].append(bind)
 e['reserved_cpu_note']='Fresh serial unchanged14gate validation05 onCPU24; one committed native precision header and fully dependency-rebuilt candidate. Dense reference, original150 and protected6000 unchanged; existing ownership/admission/global lock.'
 for n in (*helpers,'owned_driver09.py','with_correctness_namespace_09.py','native-rebuild-provenance.json'):e['runtime_artifacts']['validation05_'+n]={'path':str(R/'control'/n),'sha256':sha(pc/n)}
 for n,row in runtime_rows.items():e['runtime_artifacts']['precision_runtime_'+n]={k:row[k]for k in ('path','sha256')}
 for n in ('native','build_manifest','library_manifest','actual_build_result'):e['runtime_artifacts']['precision_'+n]=runtime[n]
 save(pc/'execution.json',e)
 cfg=copy.deepcopy(base['config']['value']);cfg['output_dir']=str(R/'run');cfg['preparation']['cache_dir']=str(R/'cache')
 for role in ('dense_runtime','segmented_runtime'):cfg[role].update(source_root=str(R/'source'),source_sha256=freeze['comparison_source']['sha256'])
 for n in ('native','build_manifest','library_manifest'):cfg['segmented_runtime'][n]=runtime[n]
 save(pc/'config-before-admission.json',cfg)
 inventory={str(p.relative_to(P)):sha(p)for p in sorted(P.rglob('*'))if p.is_file()};save(pc/'packet-files.json',inventory)
 archive=B/'validation-05-packet.tar.gz'
 with tarfile.open(archive,'x:gz')as t:
  for p in sorted(P.rglob('*')):
   if p.is_file():t.add(p,arcname=str(p.relative_to(P)),recursive=False)
 print(json.dumps({'archive':{'path':str(archive),'sha256':sha(archive)},'source_files':len(files),'source_sha256':freeze['source']['sha256'],'comparison_source_sha256':freeze['comparison_source']['sha256'],'changed_paths':[HEADER],'execution_sha256':sha(pc/'execution.json')},indent=2))
if __name__=='__main__':main()
