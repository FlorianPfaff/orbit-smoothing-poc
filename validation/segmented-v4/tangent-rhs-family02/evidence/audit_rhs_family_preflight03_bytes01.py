from pathlib import Path
import array,datetime,hashlib,json,math,struct,sys
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
F=B/'tangent-rhs-family-preflight-03';C=F/'control';R=F/'run/preflight'
def digest(raw):return hashlib.sha256(raw).hexdigest()
def pin(p):p=Path(p);return {'path':str(p),'sha256':digest(p.read_bytes())}
def checked(v):
 p=Path(v['path']);assert p.is_file() and not p.is_symlink() and pin(p)==v;return p
plan=json.loads((C/'plan.json').read_text());assert pin(C/'plan.json')['sha256']=='a70bb8bb7a5fd9f5fc5e4ac722209b1d23d31653c88533ff6525f165b0a9636e'
result=json.loads((R/'result.json').read_text());assert pin(R/'result.json')['sha256']=='20bee18a6ab3ff4fca06c9758b5aa8d62ca46f3f9c4ab3908b046ad0a74beb36'
assert result['status']=='prepared_family_no_planned_solves' and result['planned_family_calls_executed']==0
pipeline=json.loads((C/'pipeline.json').read_text());assert pipeline['status']=='passed_diagnostic' and pipeline['returncode']==0 and pipeline['final_cleanup']['verified'] and not pipeline['final_cleanup']['errors']
assert result['source_bundle']==plan['inputs']['source_bundle']
bundle=json.loads(checked(result['source_bundle']).read_text());gen=json.loads(checked(bundle['source_manifest']).read_text())
assert bundle['source_manifest']['sha256']=='378d430e946fca89e01e56d67467c33a5e7005f1b1744b85abf0f0d4f7e0eada'
for item in gen['source_files']:
 raw=checked(bundle['files'][item['path']]).read_bytes();assert digest(raw)==item['sha256'] and len(raw)==item['bytes']
 assert (R/'compiled-source'/item['path']).read_bytes()==raw
binary=checked(result['binary']);assert result['binary']['sha256']=='b86bf7bfc327f4808bd100865049658e5bd0590b602f5910501e31434a4aa7d8'
manifest=checked(result['family_manifest']);assert result['family_manifest']['sha256']=='32955e07af4ee936bfb7acf1c15ad206d997098b75acbca1eb34766e1b7f1d3c'
m=json.loads(manifest.read_text());assert m['case_count']==27 and m['attempt_count']==54
assert m['generator_sha256']==bundle['files']['generate_family.py']['sha256']
assert m['acceptance']['relative_residual']==2e-12 and m['acceptance']['maximum_iterations']==120 and m['acceptance']['restart']==20
anchors=[('historical_large','b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'),('current_small','f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044'),('current_large','b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3')]
assert [(a['id'],a['sha256'])for a in m['anchors']]==anchors
case_results=[];cursor=0
for anchor in m['anchors']:
 raw=checked({k:anchor[k]for k in('path','sha256')}).read_bytes();assert raw[:16]==b'OPCTANGENT001\n\0\0'
 version,n,intervals,terms,count,dt,duration=struct.unpack_from('<5Q2d',raw,16)
 assert (version,n,intervals,count,dt,duration)==(1,51840,51839,311040,5.,259195.)
 offset=72+2*n*18*8;total=0
 for k in range(intervals):
  num=struct.unpack_from('<Q',raw,offset)[0];offset+=8;assert num<=100
  for index,integral,moment in struct.iter_unpack('<Q2d',raw[offset:offset+24*num]):
   assert index<n and math.isfinite(integral) and math.isfinite(moment)
  offset+=24*num;total+=num
 assert total==terms and offset+8*count==len(raw)
 assert offset==anchor['operator_bytes'] and digest(raw[:offset])==anchor['operator_sha256']
 rhs=struct.unpack_from('<'+str(count)+'d',raw,offset);half=count//2
 norm=math.sqrt(math.fsum((v if i<half else v*1000.)**2 for i,v in enumerate(rhs)))
 variants=[(None,0.,0)]+[(d,z,s)for d in('smooth','alternating')for z in(1e-12,1e-9)for s in(-1,1)]
 for direction,scale,sign in variants:
  case=m['cases'][cursor];cursor+=1;assert (case['anchor'],case['direction'],case['relative_scale'],case['sign'])==(anchor['id'],direction,scale,sign)
  data=checked({k:case[k]for k in('path','sha256')}).read_bytes();assert len(data)==case['bytes']==len(raw) and data[:offset]==raw[:offset]
  if direction is None:
   assert data==raw and case['changed_entries']==0 and case['actual_relative_balanced_norm']==0.
  else:
   direction_values=[math.sin(2.*math.pi*(i+1)/count)if direction=='smooth'else(1. if i%2==0 else-1.)for i in range(count)]
   direction_norm=math.sqrt(math.fsum(v*v for v in direction_values));magnitude=sign*scale*norm/direction_norm
   expected=[math.fsum((v,magnitude*direction_values[i]/(1. if i<half else 1000.)))for i,v in enumerate(rhs)]
   expected_bytes=struct.pack('<'+str(count)+'d',*expected);assert data[offset:]==expected_bytes,case['id']
   actual=math.sqrt(math.fsum(((v-rhs[i])*(1. if i<half else 1000.))**2 for i,v in enumerate(expected)))/norm
   assert actual==case['actual_relative_balanced_norm'] and norm==case['anchor_balanced_norm']
   assert sum(a!=b for a,b in zip(expected,rhs))==case['changed_entries'] and .99*scale<=actual<=1.01*scale
  case_results.append({'id':case['id'],'sha256':case['sha256'],'operator_identical':True,'rhs_prescribed_bytes':True})
assert cursor==27 and len(m['cases'])==27
expected_order=[]
for i,case in enumerate(m['cases']):
 for profile in(('baseline','wide')if i%2==0 else('wide','baseline')):
  expected_order.append({'attempt_id':f'{len(expected_order)+1:02d}-{case["id"]}-{profile}','case_id':case['id'],'profile':profile})
assert m['execution_order']==expected_order
reference=B/'tangent-rhs-family-preflight-02/run/preflight/family/manifest.json'
assert pin(reference)['sha256']=='1dc8e32c1a0e54c0b0b57d67a439657b795a8c1aee4966c0d53ab8c2cca8158b'
old=json.loads(reference.read_text());normalized=json.loads(manifest.read_text())
for member in(old,normalized):
 for row in member['cases']:row.pop('path')
assert old==normalized
repeat_digest=digest(json.dumps(old,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
assert repeat_digest=='9fe4e384438a78999e88aefe9ec652c2d8c9e58ababddc140cd777c737ad8077'

assert {p.name for p in manifest.parent.iterdir()}=={'manifest.json','captures'}
assert {p.name for p in(manifest.parent/'captures').iterdir()}=={Path(c['path']).name for c in m['cases']}
assert not(F/'run/replay').exists() and not(B/'tangent-rhs-family-run-02/run').exists()
owned=[];boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
identities=[pipeline['admission']['driver_identity']]+pipeline['cleanup']['identities']
for identity in identities:
 try:
  fields=(Path('/proc')/str(identity['pid'])/'stat').read_text().rsplit(')',1)[1].split();start=int(fields[19]);state=fields[0]
  live=start==identity['start_ticks']and state!='Z';row={'expected':identity,'start_ticks':start,'state':state,'live':live}
 except FileNotFoundError:row={'expected':identity,'absent':True,'live':False}
 assert not row['live'];owned.append(row)
assert pin(manifest)==result['family_manifest'] and pin(binary)==result['binary']
print(json.dumps({'schema':'orbit-poc-frozen-rhs-family-independent-byte-readback-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'family_manifest':pin(manifest),'preflight_plan':pin(C/'plan.json'),'preflight_result':pin(R/'result.json'),'source_bundle':result['source_bundle'],'binary':result['binary'],'pipeline':pin(C/'pipeline.json'),'cases':case_results,'case_count':27,'attempt_count':54,'repeat_reference':pin(reference),'repeat_normalized_sha256':repeat_digest,'case_bytes_independently_reconstructed':True,'owned':owned,'boot_id':boot,'planned_calls_started':0,'scope':'Read-only byte reconstruction and provenance/cleanup verification; no solver calls.'},indent=2))
