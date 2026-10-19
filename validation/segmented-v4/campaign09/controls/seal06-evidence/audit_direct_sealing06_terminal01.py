from pathlib import Path
import json,hashlib,datetime,os,stat
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'fit-seal-control-07';out=C/'sealed-inputs-04'
def need(v,w):
 if not v:raise ValueError(w)
def pin(p):
 raw=p.read_bytes();st=p.stat();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'device':st.st_dev,'inode':st.st_ino}
ep=B/'direct-sealing-execution-06/execution.json';e=json.loads(ep.read_text());rp=out/'result.json';r=json.loads(rp.read_text())
need(pin(ep)['sha256']=='5690be37f694a717983d91075959bfca1bde07498d8585b106aa36ef97064d8b','Execution changed')
need(e['status']=='sealed_metadata' and e['returncode']==0 and e['cleanup']['verified'] and not e['cleanup']['live_owned_processes'],'Not clean terminal success')
need(r['status']=='sealed_metadata' and r['native_executions']==r['fit_attempts']==0 and r['fit_execution_authorized'] is False,'Not metadata-only result')
need(pin(rp)['sha256']==e['result']['sha256'],'Result changed')
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();need(boot==e['admission']['boot_id'],'Changed host boot');owned=[]
for wanted in [e['admission']['driver_identity'],*e['cleanup']['identities']]:
 p=Path('/proc')/str(wanted['pid'])/'stat';current=None
 try:
  fields=p.read_text().rsplit(')',1)[1].split();current={'start_ticks':int(fields[19]),'state':fields[0]}
 except FileNotFoundError:pass
 live=current is not None and current['start_ticks']==wanted['start_ticks'] and current['state']!='Z';need(not live,'Owned identity remains live');owned.append({'wanted':wanted,'current':current,'live':live})
run=B/'validation-07/run';need(not any((run/'attempts').iterdir()) and not any((B/'validation-07/temporary/fit-private').iterdir()),'Fit directories are not empty')
need(not (out/'failure.json').exists(),'Unexpected failure receipt')
sr=out/'skeleton-request.json';spec=json.loads(sr.read_text())['skeleton'];root=out/'run-skeleton';st=root.stat();need((st.st_dev,st.st_ino)==(spec['backing']['device'],spec['backing']['inode']),'Skeleton identity changed')
actual={}
for current,dirs,files in os.walk(root,followlinks=False):
 for name in dirs+files:
  p=Path(current)/name;s=p.lstat();relative=str(p.relative_to(root));row={'relative':relative}
  if stat.S_ISLNK(s.st_mode):row.update(kind='symlink',link_target=os.readlink(p))
  elif stat.S_ISDIR(s.st_mode):row['kind']='directory'
  else:need(stat.S_ISREG(s.st_mode) and s.st_size==0,'Skeleton contains nonempty or special data');row['kind']='file'
  actual[relative]=row
need(actual=={x['relative']:x for x in spec['entries']},'Skeleton membership changed')
need(hashlib.sha256((run/'manifest.json').read_bytes()).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6','Prepared manifest changed')
for path,digest in [(B/'direct-sealing-execution-03/execution.json','3b6aa4e40a04f2c4036005a5913912c53f2bd012eb804194152812cd5518b0f4'),(B/'direct-sealing-execution-04/execution.json','cb733f6b310b9e1368e7da67e16f9aee383b94b60b9fb7c6078cff16b0a59454')]:need(pin(path)['sha256']==digest,'Prior failed execution changed')
print(json.dumps({'schema':'orbit-poc-direct-sealing06-terminal-independent-readback-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'verified_metadata_seal_and_cleanup','boot_id':boot,'execution':pin(ep),'result':pin(rp),'owned_checks':owned,'output_names':sorted(x.name for x in out.iterdir()),'skeleton_request':pin(sr),'skeleton_entries':len(actual),'skeleton_counts':{k:sum(x['kind']==k for x in actual.values()) for k in ('file','directory','symlink')},'skeleton_exact_and_zero_data':True,'attempts_empty':True,'temporary_empty':True,'native_executions':0,'fit_attempts':0},indent=2))
