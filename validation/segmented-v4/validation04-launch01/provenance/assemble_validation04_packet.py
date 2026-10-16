"""Seal a fresh validation source with only the independently reviewed V4 adapter patch."""
from pathlib import Path
import argparse,copy,datetime,hashlib,json,shutil,sys,tarfile
B=Path('/mnt/d/orbit-segmented-v4');OLD=B/'validation-02-packet';P=B/'validation-04-packet';C=P/'control';R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-04');REMOTE=R.parent;OLDREMOTE=REMOTE/'validation-03';PREP=REMOTE/'preparation-02'
ALLOWED={'src/orbit_poc/segmented/multiday.py','tests/test_segmented_multiday.py','tests/test_comparison_initialization.py'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n')
def main():
 a=argparse.ArgumentParser();a.add_argument('--review',type=Path,required=True);a.add_argument('--review-sha256',required=True);a.add_argument('--patch-manifest',type=Path,required=True);a.add_argument('--patch-manifest-sha256',required=True);q=a.parse_args()
 assert sha(q.review)==q.review_sha256 and sha(q.patch_manifest)==q.patch_manifest_sha256
 rows=json.loads(q.patch_manifest.read_text());assert isinstance(rows,list) and len(rows)==3 and all(set(x)=={'relative','path','sha256','bytes'} for x in rows)
 patch={x['relative']:{'path':x['path'],'sha256':x['sha256']} for x in rows};assert set(patch)==ALLOWED
 for x in rows:assert Path(x['path']).stat().st_size==x['bytes']
 review=json.loads(q.review.read_text());assert review.get('passed') is True and review.get('patched_files')==patch
 assert review['candidate_files']['path']==str(q.patch_manifest) and review['candidate_files']['sha256']==q.patch_manifest_sha256
 original=json.loads((OLD/'control/source-freeze.json').read_text());assert original['source']['sha256']=='5f85c630c89be7e0a7654b31764186d8a4f914e2f4b74fec1535339658e42dd2'
 assert not P.exists();C.mkdir(parents=True);dest=P/'source';dest.mkdir()
 for name,h in original['source']['files'].items():
  src=OLD/'source'/name;assert sha(src)==h
  out=dest/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,out)
 for name,p in patch.items():
  assert set(p)=={'path','sha256'} and sha(p['path'])==p['sha256'] and Path(p['path']).resolve()==(B/'source'/name).resolve()
  shutil.copy2(p['path'],dest/name);assert sha(dest/name)==p['sha256'] and sha(p['path'])==p['sha256']
 files={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()};changed={n for n in set(files)|set(original['source']['files']) if files.get(n)!=original['source']['files'].get(n)};assert changed==ALLOWED
 sys.path.insert(0,str(dest/'src'));from orbit_poc.comparison.protocol import source_snapshot
 freeze={'schema':'orbit-poc-v4-validation-source-freeze-v1','scope':'Fresh unchanged14gate validation after reviewed V4-only synthetic nominal profile wiring; no numerical-native changes or acceptance inheritance','source':{'files':files,'sha256':digest(files)},'comparison_source':source_snapshot(dest),'previous_source':{'path':str(OLDREMOTE/'control/source-freeze.json'),'sha256':'efbef2b87ce78aad025e259d82203e1c6ec76502eca2e7e15d966f3dac866a01'},'allowed_changed_paths':sorted(ALLOWED),'patch_review':{'path':str(R/'control/profile-fix-independent-review.json'),'sha256':q.review_sha256},'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'capture_method':'Verified archived snapshot plus exact three reviewed adapter/test files; no unrelated working-tree content','helper_sha256':sha(__file__)}
 # Relocated audit bytes are attribution only; their internal local paths remain original.
 shutil.copy2(q.review,C/'profile-fix-independent-review.json');shutil.copy2(q.patch_manifest,C/'profile-fix-pins.json');save(C/'source-freeze.json',freeze)
 native={k:h for k,h in files.items() if k.startswith('groops/') or k=='scripts/build_groops.py'};prior={k:h for k,h in original['source']['files'].items() if k.startswith('groops/') or k=='scripts/build_groops.py'};assert native==prior and len(native)==70
 equivalence={'schema':'orbit-poc-v4-native-build-input-equivalence-v1','status':'passed','all_native_inputs_byte_identical':True,'native_input_count':70,'files':native,'current_source':{'path':str(R/'control/source-freeze.json'),'sha256':sha(C/'source-freeze.json')},'engineering02_source':{'path':str(REMOTE/'engineering-02/control/source-freeze.json'),'sha256':'4e05b392e81f7d45e3433327f468f0087500036be10dfb428d92a3d5a66be762'},'native_sha256':'a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22','solver_sha256':'2c8481050806ce9d4c89d4c605fd9036bed3cdfb97010efeb359213aa0dbc223','source_identity_scope':'Only one V4 adapter and two Python tests differ; all70 native compilation inputs are exactly the archived engineering02 build inputs; native is reused without rebuilding.'};save(C/'native-input-equivalence.json',equivalence)
 for name in ('run_segmented_validation01.py','launch_segmented_validation01.py','validation03_startup_probe.py','smoke_segmented_validation04.py','stage_segmented_validation04.py','assemble_validation04_packet.py'):shutil.copy2(B/'control'/name,C/name)
 for src,name in [('closure-owned-driver09.py','owned_driver09.py'),('closure-with-correctness-namespace09.py','with_correctness_namespace_09.py')]:shutil.copy2(B/'control'/src,C/name)
 e=json.loads((B/'control/closure-base-execution05.json').read_text());old=e['paths'].copy()
 e['paths'].update(root=str(R),source=str(R/'source'),control=str(R/'control'),wrapper=str(R/'control/with_correctness_namespace_09.py'),native_source=str(R/'preparation'),build=str(R/'cache'),binaries=str(R/'artifacts'),run=str(R/'run'),temporary=str(R/'temporary'))
 e['read_only_bindings'].append({'source':str(OLDREMOTE),'target':str(OLDREMOTE)})
 for key in ('native_source','build','binaries','run','temporary'):e['read_only_bindings'].append({'source':str(PREP/'backings'/key),'target':old[key]})
 e['read_only_bindings'].append({'source':str(OLDREMOTE/'run/validation'),'target':str(OLDREMOTE/'run/validation')})
 e['reserved_cpu_note']='Fresh serial unchanged14gate validation onCPU24; original150 separately onWSLCPU30, production6000 protected. Only reviewed V4 synthetic preparation adapter/test source differs; native/solver reused byte-identically. Global existing orbit lock and owned namespace admission retained.'
 for name in ('run_segmented_validation01.py','launch_segmented_validation01.py','validation03_startup_probe.py','smoke_segmented_validation04.py','stage_segmented_validation04.py','assemble_validation04_packet.py','owned_driver09.py','with_correctness_namespace_09.py','profile-fix-independent-review.json','profile-fix-pins.json','native-input-equivalence.json'):e['runtime_artifacts']['validation04_'+name]={'path':str(R/'control'/name),'sha256':sha(C/name)}
 save(C/'execution.json',e)
 cfg=json.loads((B/'control/validation04-base-config.json').read_text());cfg['output_dir']=str(R/'run');cfg['preparation']['cache_dir']=str(R/'cache')
 for k in ('dense_runtime','segmented_runtime'):cfg[k].update(source_root=str(R/'source'),source_sha256=freeze['comparison_source']['sha256'])
 save(C/'config-before-admission.json',cfg)
 inventory={str(p.relative_to(P)):sha(p) for p in sorted(P.rglob('*')) if p.is_file()};save(C/'packet-files.json',inventory)
 archive=B/'validation-04-packet.tar.gz'
 with tarfile.open(archive,'x:gz') as t:
  for p in sorted(P.rglob('*')):
   if p.is_file():t.add(p,arcname=str(p.relative_to(P)),recursive=False)
 print(json.dumps({'archive':pin(archive),'source_files':len(files),'source_sha256':freeze['source']['sha256'],'comparison_source_sha256':freeze['comparison_source']['sha256'],'changed_paths':sorted(changed),'execution_sha256':sha(C/'execution.json')},indent=2))
if __name__=='__main__':main()
