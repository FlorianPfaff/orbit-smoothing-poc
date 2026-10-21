from pathlib import Path
import hashlib,json,tarfile,datetime,os
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');e=B/'direct-sealing-execution-06';s=B/'fit-seal-control-07/sealed-inputs-04';c=B/'fit-seal-control-07';out=B/'direct-sealing06-terminal-01'
def need(v,m):
 if not v:raise ValueError(m)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def ident(pid):
 try:
  t=Path('/proc/%s/stat'%pid).read_text();r=t[t.rfind(')')+2:].split();return {'pid':pid,'start_ticks':int(r[19]),'state':r[0]}
 except (FileNotFoundError,ProcessLookupError):return None
x=json.loads((e/'execution.json').read_text());need(x['status'] in ('failed','sealed_metadata') and x['cleanup']['verified'] and not x['cleanup']['live_owned_processes'],'Terminal cleanup required')
live=[]
for old in x['cleanup']['identities']:
 now=ident(old['pid'])
 if now and now['start_ticks']==old['start_ticks'] and now['state']!='Z':live.append(now)
need(not live,'Owned process remains')
files={}
for p in e.iterdir():
 if p.is_file():files['execution/'+p.name]=p
plan=json.loads((c/'sealing-plan05.json').read_text());allowed=set(plan['planned_outputs'])
for p in s.iterdir():
 need(p.name in allowed,'Unexpected output member')
 if p.is_file():
  need(p.suffix=='.json' and not p.is_symlink(),'Unexpected generated file');files['sealed/'+p.name]=p
 elif p.name!='run-skeleton':raise ValueError('Unexpected generated directory')
for n in ('sealing-request05.json','sealing-plan05.json','readonly-view-plan06.json','readonly-view-plan06-parents.json'):files['control/'+n]=c/n
out.mkdir()
skeleton=s/'run-skeleton'
if skeleton.exists():
 import stat
 entries=[]
 for root,dirs,names in os.walk(skeleton,followlinks=False):
  for name in sorted(dirs+names):
   p=Path(root)/name;st=p.lstat();kind='symlink' if stat.S_ISLNK(st.st_mode) else 'directory' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'special'
   need(kind!='special','Special skeleton entry')
   if kind=='file':need(st.st_size==0,'Skeleton contains actual input bytes')
   entries.append({'relative':p.relative_to(skeleton).as_posix(),'kind':kind,'bytes':st.st_size,'device':st.st_dev,'inode':st.st_ino,'mode':stat.S_IMODE(st.st_mode),'link_target':os.readlink(p) if kind=='symlink' else None})
 si=out/'skeleton-inventory.json';si.write_text(json.dumps({'schema':'orbit-poc-zero-byte-skeleton-inventory-v1','root':str(skeleton),'entries':entries},indent=2,sort_keys=True)+'\n');files['capture/skeleton-inventory.json']=si
records=[{'path':str(p),'relative_path':r,'bytes':p.stat().st_size,'sha256':sha(p)} for r,p in sorted(files.items())]
v={'schema':'orbit-poc-direct-sealing06-terminal-capture-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':x['status'],'execution_sha256':sha(e/'execution.json'),'fit_attempts':0,'native_executions':0,'owned_live':live,'output_preserved':str(s),'files':records}
mp=out/'manifest.json';mp.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
with tarfile.open(out/'terminal.tar.gz','w:gz') as t:
 t.add(mp,arcname='manifest.json',recursive=False)
 for r in records:
  p=Path(r['path']);need(sha(p)==r['sha256'],'Source changed');t.add(p,arcname=r['relative_path'],recursive=False)
print(json.dumps({'files':len(records),'bytes':sum(r['bytes'] for r in records),'manifest_sha256':sha(mp),'archive':str(out/'terminal.tar.gz'),'archive_sha256':sha(out/'terminal.tar.gz')}))
