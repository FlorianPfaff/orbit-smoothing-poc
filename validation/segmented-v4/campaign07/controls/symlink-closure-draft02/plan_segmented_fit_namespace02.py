#!/usr/bin/env python3
"""Verify canonical/backing identities and plan an empty-root fit namespace.

This module never launches bwrap, a verifier, a preparation job or a fit. Its
output is conditional until an owned wrapper revalidates it and executes the
required positive/negative namespace probes.
"""
from pathlib import Path,PurePosixPath
import argparse,ctypes,fcntl,hashlib,json,os,posixpath,stat,sys
SCHEMA='orbit-poc-segmented-fit-mount-plan-input-v1'
MAP_SCHEMA='orbit-poc-segmented-fit-backing-map-v1'
BANNED=('/proc','/sys','/dev')
def need(ok,msg):
 if not ok:raise ValueError(msg)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(v):return digest(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def absolute(s):
 need(isinstance(s,str) and s.startswith('/') and '\0' not in s and posixpath.normpath(s)==s,'Noncanonical absolute path')
 p=PurePosixPath(s);need(s!='/' and not any(p==PurePosixPath(x) or PurePosixPath(x) in p.parents for x in BANNED),'Kernel/host root is forbidden');return s
def within(p,root):return p==root or p.startswith(root.rstrip('/')+'/')
def sha_file(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def host_pin(path):
 path=absolute(path);p=Path(path);need(not p.is_symlink() and p.is_file() and str(p.resolve())==path,'Backing must be a resolved regular file')
 s=p.stat();need(stat.S_ISREG(s.st_mode) and not s.st_mode&0o6000,'Special/set-id backing is forbidden')
 return {'path':path,'sha256':sha_file(path),'bytes':s.st_size,'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode)}
def check_pin(p):
 q=host_pin(p['path']);need(q['sha256']==p['sha256'] and q['bytes']==p['bytes'],'Pinned backing bytes differ')
 for k in ('device','inode','mode'):
  if k in p:need(q[k]==p[k],'Pinned backing identity differs')
 return q
def read(pin):
 check_pin(pin);return json.loads(Path(pin['path']).read_bytes())
def links_resolve(path,links,used=None):
 path=absolute(path);seen=set()
 for _ in range(64):
  parts=PurePosixPath(path).parts;found=False
  for n in range(2,len(parts)+1):
   prefix=str(PurePosixPath(*parts[:n]))
   if prefix in links:
    if used is not None:used.add(prefix)
    state=(path,prefix);need(state not in seen,'Canonical symlink cycle');seen.add(state)
    target=links[prefix];base=target if target.startswith('/') else posixpath.join(posixpath.dirname(prefix),target)
    path=absolute(posixpath.normpath(posixpath.join(base,*parts[n:])));found=True;break
  if not found:return path
 raise ValueError('Canonical symlink depth exceeded')
def symlink_placements(links):
 """One actual link location per resolved parent, retaining the full ledger."""
 out={}
 for path,target in links.items():
  parent=posixpath.dirname(path)
  location=posixpath.join(links_resolve(parent,links) if parent!='/' else '/',posixpath.basename(path))
  need(location in links,'Missing canonical-parent symlink closure')
  need(links[location]==target,'Conflicting aliased symlink targets')
  need(location not in out or out[location]==target,'Conflicting aliased symlink targets')
  need(links_resolve(location,links)==links_resolve(path,links),'Missing canonical-parent symlink closure')
  out[location]=target
 return out
def inode(q):return (q['device'],q['inode'])
def directory(pin,empty=False):
 path=absolute(pin['path']);p=Path(path);need(p.is_dir() and not p.is_symlink() and str(p.resolve())==path,'Backing directory must be resolved')
 s=p.stat();need((s.st_dev,s.st_ino)==(pin['device'],pin['inode']),'Directory backing identity differs')
 if empty:need(not any(p.iterdir()),'Writable directory must be empty')
 return path
def physical_tree(root):
 out={}
 def walk(p,rel):
  for q in sorted(p.iterdir()):
   name=(rel/q.name).as_posix();s=q.lstat()
   if stat.S_ISLNK(s.st_mode):out[name]={'link_target':os.readlink(q)}
   elif stat.S_ISDIR(s.st_mode):out[name]={'kind':'directory','link_target':None};walk(q,rel/q.name)
   elif stat.S_ISREG(s.st_mode):
    need(not s.st_mode&0o6000,'Set-id safe-tree file is forbidden');out[name]={'kind':'file','link_target':None,'sha256':sha_file(q),'bytes':s.st_size}
   else:raise ValueError('Special file in safe tree')
 walk(Path(root),Path());return out
def strict_rows(items,key,label):
 result={}
 for row in items:
  name=absolute(row[key]);need(name not in result,'Duplicate '+label);result[name]=row
 return result

def _build(plan,verify_skeleton):
 need(set(plan)=={'schema','allowlist','mapping'} and plan['schema']==SCHEMA,'Wrong mount planner schema/fields')
 allow=read(plan['allowlist']);mapping=read(plan['mapping'])
 need(allow.get('schema')=='orbit-poc-segmented-fit-read-allowlist-v2' and allow.get('fit_execution_authorized') is False,'Expected reviewed conditional allowlist02')
 need(allow.get('allowlist_hash')==canonical({k:v for k,v in allow.items() if k!='allowlist_hash'}),'Allowlist content hash differs')
 need(set(mapping)=={'schema','allowlist_sha256','execution','canonical_symlinks','files','inventories','safe_trees','writable','run_skeleton'} and mapping['schema']==MAP_SCHEMA,'Wrong backing-map schema/fields')
 need(mapping['allowlist_sha256']==plan['allowlist']['sha256'],'Mapping binds another allowlist')
 execution=read(mapping['execution']);bindings=execution['read_only_bindings']
 need(isinstance(bindings,list),'Execution binding inventory missing')
 links={}
 for v in mapping['canonical_symlinks']:
  need(set(v)=={'path','target'},'Unknown canonical symlink fields');p=absolute(v['path']);t=v['target']
  need(isinstance(t,str) and t and '\0' not in t and p not in links,'Invalid/duplicate symlink');links[p]=t
  absolute(posixpath.normpath(t if t.startswith('/') else posixpath.join(posixpath.dirname(p),t)))
 rows=strict_rows(allow['files'],'path','allowlisted file')
 required_directories={absolute(x) for x in allow['directories']}
 tree_specs=strict_rows(allow['verified_safe_trees'],'root','safe tree')
 mapped_trees=strict_rows(mapping['safe_trees'],'canonical','safe-tree backing')
 need(set(tree_specs)==set(mapped_trees),'Safe-tree mapping membership differs')
 inventory_maps=strict_rows(mapping['inventories'],'canonical','inventory backing')
 need(set(inventory_maps)=={x['inventory']['path'] for x in tree_specs.values()},'Exact safe-tree inventory map membership required')
 file_maps=strict_rows(mapping['files'],'canonical','file backing')
 need(set(file_maps)=={absolute(x['resolved']) for x in rows.values()},'Exact resolved-file map membership required')
 sensitive_inodes={inode(x) for x in allow['denied_files'] if x['content_sensitive']}
 sensitive_contents={(x['bytes'],x['sha256']) for x in allow['denied_files'] if x['content_sensitive'] and x['bytes']}
 denied_paths={absolute(x[k]) for x in allow['denied_files'] for k in ('path','resolved')}
 def allowed(path,record):
  need(path not in denied_paths and inode(record) not in sensitive_inodes and (record['bytes'],record['sha256']) not in sensitive_contents,'Denied path/inode/content backing')
 def provenance(canonical_path,backing):
  matches=[]
  for i,b in enumerate(bindings):
   need(set(b)=={'source','target'},'Unknown execution binding fields');target=links_resolve(absolute(b['target']),links);source=absolute(b['source'])
   if within(canonical_path,target):matches.append((len(PurePosixPath(target).parts),i,source+canonical_path[len(target):]))
  expected=max(matches)[2] if matches else canonical_path
  # Resolve only the declared backing source path, never a canonical host path.
  need(str(Path(expected).resolve())==backing,'Backing does not match pinned execution binding/direct identity')
 checked={}
 for name,v in file_maps.items():
  need(set(v)=={'canonical','backing'},'Unknown file mapping fields');q=check_pin(v['backing']);allowed(name,q);provenance(name,q['path']);checked[name]=q
 for path,row in rows.items():
  resolved=links_resolve(path,links);need(resolved==row['resolved'],'Canonical parent/file symlink topology differs')
  if row['link_target'] is not None:need(links.get(path)==row['link_target'],'Missing/changed required file symlink')
  q=checked[resolved];need(q['sha256']==row['sha256'] and q['bytes']==row['bytes'] and inode(q)==inode(row),'Canonical/backing file identity differs');allowed(path,q)
 inventories=[];verified_trees=[]
 for root,spec in tree_specs.items():
  need(spec['kind'] in ('source','python_runtime','native_runtime'),'Unknown safe-tree kind')
  need(links_resolve(root,links)==root,'Safe-tree root cannot be a canonical symlink alias')
  invpath=absolute(spec['inventory']['path']);im=inventory_maps[invpath];need(set(im)=={'canonical','backing'},'Unknown inventory mapping fields');ip=check_pin(im['backing']);provenance(links_resolve(invpath,links),ip['path'])
  need(ip['sha256']==spec['inventory']['sha256'] and ip['bytes']==spec['inventory']['bytes'] and inode(ip)==inode(spec['inventory']),'Safe-tree inventory pin differs');invraw=Path(ip['path']).read_bytes();inv=json.loads(invraw)
  need(inv['schema']=='orbit-poc-native-data-directory-v1' and inv['root']==root,'Safe-tree inventory root/schema differs')
  entries={e['relative']:e for e in inv['entries']};need(len(entries)==len(inv['entries']),'Duplicate tree inventory member')
  expected={};symlink_dirs={r for r,e in entries.items() if e['kind']=='directory' and e['link_target'] is not None}
  for rel,e in entries.items():
   need(not PurePosixPath(rel).is_absolute() and '..' not in PurePosixPath(rel).parts and rel not in ('','.'),'Unsafe tree member')
   path=root+'/'+rel;need(e['kind'] in ('file','directory'),'Unknown tree member kind');required_directories.add(path if e['kind']=='directory' else str(PurePosixPath(path).parent))
   if e['link_target'] is not None:need(links.get(path)==e['link_target'],'Safe-tree symlink differs')
   need(links_resolve(path,links)==e['resolved'],'Safe-tree resolved topology differs')
   if e['kind']=='file':need(path in rows and rows[path]['sha256']==e['sha256'] and rows[path]['bytes']==e['bytes'],'Safe-tree file not exactly allowlisted')
   if not any(rel.startswith(d+'/') for d in symlink_dirs):
    expected[rel]={'link_target':e['link_target']} if e['link_target'] is not None else {k:e[k] for k in (('kind','link_target','sha256','bytes') if e['kind']=='file' else ('kind','link_target'))}
  tm=mapped_trees[root];need(set(tm)=={'canonical','backing'},'Unknown safe-tree mapping fields');back=directory(tm['backing']);provenance(root,back)
  need(physical_tree(back)==expected,'Safe-tree physical membership/bytes/link text differs')
  verified_trees.append({'canonical':root,'backing':tm['backing'],'kind':spec['kind'],'inventory':spec['inventory'],'physical_entries':len(expected)})
  inventories.append(inv)
 for inv in allow['native_data_inventories']:
  root=absolute(inv['root']);required_directories.add(root)
  for e in inv['entries']:
   p=root+'/'+e['relative'];absolute(p)
   if e['kind']=='directory':required_directories.add(p)
   else:need(p in rows and rows[p]['sha256']==e['sha256'] and rows[p]['bytes']==e['bytes'],'Native data member differs')
   if e['link_target'] is not None:need(links.get(p)==e['link_target'],'Native-data symlink differs')
   need(links_resolve(p,links)==e['resolved'],'Native-data resolved topology differs')
 roots=sorted(tree_specs)
 need(not any(a!=b and within(a,b) for a in roots for b in roots),'Overlapping safe trees')
 need(all(not any(within(d['root'],r) or within(r,d['root']) for d in allow['denied_tree_inventories']) for r in roots),'Safe tree overlaps denied generation tree')
 requested=set(rows)|required_directories|set(roots)
 used=set()
 for p in requested:links_resolve(p,links,used)
 need(all(link in used or any(within(p,link) for p in requested) for link in links),'Unused canonical symlink could expose an extra alias')
 for link in links:links_resolve(link,links)
 placements=symlink_placements(links)
 writes=mapping['writable'];need(set(writes)=={'attempts','temporary','lock'},'Exact writable mapping required');rw=[]
 for kind in ('attempts','temporary'):
  dest=absolute(allow['writable'][kind]);need(links_resolve(dest,links)==dest,'Writable canonical path aliases');src=directory(writes[kind],True);provenance(dest,src)
  need(not any(within(dest,r) or within(r,dest) for r in roots),'Writable directory overlaps safe tree')
  need(not any(within(p,dest) or within(dest,p) for p in rows),'Writable directory overlaps readonly input')
  need(not any(within(dest,d['root']) or within(d['root'],dest) for d in allow['denied_tree_inventories']),'Writable directory overlaps truth tree');rw.append({'kind':kind,'source':src,'target':dest,'identity':writes[kind]})
 lock=allow['writable']['lock'];dest=absolute(lock['path']);q=check_pin(writes['lock']);need(q['bytes']==0 and inode(q)==inode(lock),'Writable lock differs');provenance(dest,q['path']);allowed(dest,q)
 need(links_resolve(dest,links)==dest and dest not in rows and not any(within(dest,r) for r in roots),'Writable lock overlaps readonly input');rw.append({'kind':'lock','source':q['path'],'target':dest,'identity':q})
 need(len({x['source'] for x in rw})==3 and not any(a!=b and within(a['source'],b['source']) for a in rw for b in rw),'Writable host roots overlap')
 mounts=[]
 for tree in verified_trees:mounts.append({'operation':'ro-bind','source':tree['backing']['path'],'target':tree['canonical'],'kind':tree['kind']})
 for name,q in sorted(checked.items()):
  # The exact coarse tree already exposes these bytes. External symlink targets
  # are outside the tree and therefore remain individual readonly file mounts.
  if not any(within(name,r) for r in roots):mounts.append({'operation':'ro-bind','source':q['path'],'target':name,'kind':'file'})
 dirs=set()
 for p in required_directories|{x['target'] for x in mounts}|{x['target'] for x in rw}|set(links):
  target=links_resolve(p,links)
  if p in required_directories:dirs.add(target)
  dirs.update(str(x) for x in PurePosixPath(target).parents if str(x)!='/')
 for tree in roots:dirs.add(tree)
 for location in placements:dirs.update(str(x) for x in PurePosixPath(location).parents if str(x)!='/')
 dirs={d for d in dirs if not any(within(d,r) and d!=r for r in roots)}
 run_root=str(PurePosixPath(allow['writable']['attempts']).parent);need(run_root==allow['source_plan']['run_root'],'Run-root identity differs')
 skeleton_path=directory(mapping['run_skeleton']);attempt_source=next(x for x in rw if x['kind']=='attempts')['identity']
 need(mapping['run_skeleton']['device']==attempt_source['device'],'Run skeleton must share the attempts filesystem')
 need(not any(within(skeleton_path,x['source']) or within(x['source'],skeleton_path) for x in rw),'Run skeleton overlaps writable backing')
 need(not any(within(skeleton_path,x['backing']['path']) or within(x['backing']['path'],skeleton_path) for x in verified_trees),'Run skeleton overlaps a safe tree')
 skeleton={}
 def placeholder(path,kind,target=None):
  if path==run_root or not within(path,run_root):return
  rel=path[len(run_root)+1:];entry={'relative':rel,'kind':kind}
  if target is not None:entry['link_target']=target
  old=skeleton.get(rel);need(old is None or old==entry,'Conflicting skeleton placeholder');skeleton[rel]=entry
  for parent in PurePosixPath(path).parents:
   if str(parent)==run_root:break
   if within(str(parent),run_root):placeholder(str(parent),'directory')
 for d in dirs:placeholder(d,'directory')
 for x in mounts:placeholder(x['target'],'file' if x['kind']=='file' else 'directory')
 for x in rw:placeholder(x['target'],'file' if x['kind']=='lock' else 'directory')
 for path,target in placements.items():
  if not any(within(path,r) for r in roots):placeholder(path,'symlink',target)
 spec={'schema':'orbit-poc-segmented-fit-run-skeleton-v1','canonical_root':run_root,'backing':mapping['run_skeleton'],'entries':[skeleton[k] for k in sorted(skeleton)],'content_rule':'Only empty regular file placeholders, directories and exact declared symlinks; no data bytes.','same_filesystem_as_attempts':True}
 if not verify_skeleton:return {'schema':'orbit-poc-segmented-fit-run-skeleton-request-v1','inputs':plan,'skeleton':spec,'fit_execution_authorized':False}
 expected={}
 for e in spec['entries']:
  expected[e['relative']]={'link_target':e['link_target']} if e['kind']=='symlink' else {'kind':e['kind'],'link_target':None,**({'sha256':digest(b''),'bytes':0} if e['kind']=='file' else {})}
 need(physical_tree(skeleton_path)==expected,'Run skeleton exact empty membership differs')
 args=['--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv','--tmpfs','/']
 for d in sorted(dirs,key=lambda p:(len(PurePosixPath(p).parts),p)):
  absolute(d)
  if not within(d,run_root) or d==run_root:args+=['--dir',d]
 args+=['--ro-bind',skeleton_path,run_root]
 for p,t in sorted(placements.items(),key=lambda x:(len(PurePosixPath(x[0]).parts),x[0])):
  if not within(p,run_root) and not any(within(p,r) for r in roots):args+=['--symlink',t,p]
 for m in mounts:args+=['--ro-bind',m['source'],m['target']]
 args+=['--proc','/proc','--dev','/dev']
 for m in rw:args+=['--bind',m['source'],m['target']]
 required_env={'TMPDIR':allow['writable']['temporary'],'TMP':allow['writable']['temporary'],'TEMP':allow['writable']['temporary'],'HOME':allow['writable']['temporary']+'/home','XDG_CACHE_HOME':allow['writable']['temporary']+'/cache','PYTHONDONTWRITEBYTECODE':'1','PWD':run_root}
 for key,value in sorted(required_env.items()):args+=['--setenv',key,value]
 args+=['--chdir',run_root,'--remount-ro','/']
 payload=args_bytes(args)
 result={'schema':'orbit-poc-segmented-fit-mount-plan-v1','inputs':plan,'execution':mapping['execution'],'allowlist_hash':allow['allowlist_hash'],'manifest_hash':allow['manifest_hash'],'mount_args':args,'mount_args_payload':{'sha256':digest(payload),'bytes':len(payload),'encoding':'nul-terminated-utf8'},'readonly_mounts':[{'operation':'ro-bind','source':skeleton_path,'target':run_root,'kind':'verified_empty_run_skeleton'}]+mounts,'run_skeleton':spec,'run_skeleton_verified':True,'verified_safe_trees':verified_trees,'verified_file_backings':checked,'writable_mounts':rw,'canonical_symlinks':mapping['canonical_symlinks'],'policy':{'host_root_mounted':False,'host_proc_mounted':False,'host_dev_mounted':False,'network_namespace':'fresh','root_readonly':True,'command_included':False,'inherited_descriptors':'Wrapper closes all descriptors >=3 except the sealed args memfd during bwrap setup, then consumes/closes that fd before the target command. Target stdin is fresh /dev/null; stdout/stderr are separately owned logs. No host directory descriptors.','runtime_environment':'Empty; wrapper may set only explicitly pinned runtime values, never inherited LD_* or PATH. HOME/private caches are beneath the empty writable temporary directory.', 'required_environment':required_env,'prelaunch_required':['Recheck every input/backing/tree identity immediately before bind execution','Use an owned isolated launcher with current admission and host lock','Verified same-filesystem run skeleton preserves run_root statvfs; independently guard actual attempts/temp backing free bytes and quotas before and during fits','Probe canonical/resolved/backing aliases, /proc/self/root and /proc/1/root for truth/GNV denial','Inspect descriptors/mounts and verify fresh PID/network namespaces','Run exact frozen verify_manifest and require_passed read-only inside this namespace']},'fit_execution_authorized':False,'release_ready':False}
 result['mount_plan_hash']=canonical(result);return result

def build(plan):return _build(plan,True)
def skeleton_spec(plan):return _build(plan,False)

def args_bytes(args):
 need(all(isinstance(a,str) and a and '\0' not in a for a in args),'Invalid bwrap argument');return b''.join(a.encode('utf-8')+b'\0' for a in args)
def sealed_args_fd(args):
 """Return a sealed CLOEXEC memfd; caller owns closing/passing this single FD."""
 payload=args_bytes(args);need(sys.platform=='linux','Linux sealed memfd support is required')
 # Linux UAPI: MFD_CLOEXEC=1, MFD_ALLOW_SEALING=2. Some pinned scientific
 # Python builds omit the os wrapper and fcntl names despite kernel support.
 libc=ctypes.CDLL(None,use_errno=True);need(hasattr(libc,'memfd_create'),'libc memfd_create is required')
 create=libc.memfd_create;create.argtypes=[ctypes.c_char_p,ctypes.c_uint];create.restype=ctypes.c_int
 fd=create(b'orbit-fit-bwrap-args',3)
 if fd<0:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
 try:
  with os.fdopen(os.dup(fd),'wb') as f:f.write(payload)
  os.lseek(fd,0,os.SEEK_SET);seals=0x000f;fcntl.fcntl(fd,1033,seals);need(fcntl.fcntl(fd,1034)==seals,'Args fd was not fully sealed');return fd
 except BaseException:os.close(fd);raise

def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--skeleton-spec',action='store_true');a=p.parse_args();raw=a.plan.read_bytes();need(digest(raw)==a.sha256,'Input plan changed');result=skeleton_spec(json.loads(raw)) if a.skeleton_spec else build(json.loads(raw));need(a.output.is_absolute() and not a.output.exists(),'Use a fresh absolute output');a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open('x') as f:f.write(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps({'output':host_pin(str(a.output)),'fit_execution_authorized':False,'mounts':len(result.get('readonly_mounts',[]))}))
if __name__=='__main__':main()
