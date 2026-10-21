#!/usr/bin/env python3
"""Read-only checks inside a prepared empty-root fit namespace.

This helper never runs a fit. The host verifies correspondence before exec;
final plan hashes are attribution strings, avoiding self-referential pins.
"""
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib,json,os,posixpath,re,stat,sys
SCHEMA='orbit-poc-segmented-fit-inner-probe-spec-v1'
KEYS={'schema','config','run_root','source_root','public_api_files','manifest_hash','source_sha256','host_namespaces','denied_paths','protected_readonly_targets','writable'}
API_NAMES={'config.py','protocol.py','validation.py'}
DEVICES={'/dev/null':(1,3),'/dev/zero':(1,5),'/dev/full':(1,7),'/dev/random':(1,8),'/dev/urandom':(1,9),'/dev/tty':(5,0)}
VIRTUAL={'/proc':'proc','/dev':'tmpfs','/dev/pts':'devpts'}

def need(ok,msg):
 if not ok:raise ValueError(msg)
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def absolute(p):need(isinstance(p,str) and p.startswith('/') and '\0' not in p and posixpath.normpath(p)==p,'Noncanonical path');return p
def within(p,r):return p==r or p.startswith(r.rstrip('/')+'/')
def pin_check(v):
 p=Path(absolute(v['path']));need(p.is_file() and digest(p)==v['sha256'] and ('bytes' not in v or p.stat().st_size==v['bytes']),'Pinned probe/config/API bytes differ');return p
def load(pin):return json.loads(pin_check(pin).read_bytes())
def validate_spec(spec):
 need(set(spec)==KEYS and spec['schema']==SCHEMA,'Unknown probe specification fields/schema')
 for k in ('run_root','source_root'):need(absolute(spec[k]) not in ('/','/proc','/dev','/sys'),'Unsafe source/run root')
 need(set(spec['writable'])=={'attempts','temporary','lock'},'Exact writable set required')
 for k,v in spec['writable'].items():absolute(v)
 need(spec['writable']['attempts']==spec['run_root']+'/attempts' and spec['writable']['lock']==spec['run_root']+'/.segmented.lock','Run writable topology differs')
 need(set(spec['host_namespaces'])=={'pid','net'} and all(re.fullmatch(k+r':\[\d+\]',v) for k,v in spec['host_namespaces'].items()),'Host namespace identities missing')
 for k in ('manifest_hash','source_sha256'):need(re.fullmatch('[0-9a-f]{64}',spec[k]) is not None,'Invalid identity digest')
 for key in ('denied_paths','protected_readonly_targets'):
  need(isinstance(spec[key],list) and spec[key]==sorted(set(spec[key])),'Sorted unique path inventory required')
  for p in spec[key]:need(absolute(p) not in ('/','/proc','/dev','/sys'),'Unsafe inventoried path')
 need(not set(spec['denied_paths'])&set(spec['protected_readonly_targets']),'Denied/protected path conflict')
 need(set(spec['public_api_files'])==API_NAMES,'Exact frozen public API inventory required')
 for name,pin in spec['public_api_files'].items():need(pin['path']==spec['source_root']+'/src/orbit_poc/segmented/'+name,'Public API path differs')
 return spec

def link_resolve(path,links):
 seen=set()
 for _ in range(64):
  found=False;parts=PurePosixPath(path).parts
  for n in range(2,len(parts)+1):
   p=str(PurePosixPath(*parts[:n]))
   if p in links:
    need((path,p) not in seen,'Link cycle');seen.add((path,p));t=links[p];path=posixpath.normpath(posixpath.join(t if t.startswith('/') else posixpath.join(posixpath.dirname(p),t),*parts[n:]));found=True;break
  if not found:return absolute(path)
 raise ValueError('Link depth exceeded')

def verify_spec_correspondence(spec,mount_plan,allowlist,backing_mapping):
 """Host-only: prove static inner spec matches the exact sealed final context."""
 validate_spec(spec)
 need(spec['host_namespaces']=={k:os.readlink('/proc/self/ns/'+k) for k in ('pid','net')},'Static host namespace baseline differs from current wrapper host')
 need(allowlist.get('schema')=='orbit-poc-segmented-fit-read-allowlist-v2' and allowlist.get('allowlist_hash')==canonical({k:v for k,v in allowlist.items() if k!='allowlist_hash'}),'Allowlist identity differs')
 initial=mount_plan
 if mount_plan.get('schema')=='orbit-poc-segmented-fit-resume-mount-plan-v1':
  need(mount_plan.get('resume_mount_plan_hash')==canonical({k:v for k,v in mount_plan.items() if k!='resume_mount_plan_hash'}),'Resume mount identity differs');initial=load(mount_plan['inputs']['inputs']['initial_mount_plan'])
  need(mount_plan['initial_mount_plan_hash']==initial['mount_plan_hash'] and mount_plan['original_allowlist_hash']==allowlist['allowlist_hash'],'Resume input identity differs')
 need(initial.get('schema')=='orbit-poc-segmented-fit-mount-plan-v1' and initial.get('mount_plan_hash')==canonical({k:v for k,v in initial.items() if k!='mount_plan_hash'}),'Initial mount identity differs')
 need(initial['allowlist_hash']==allowlist['allowlist_hash'] and initial['manifest_hash']==spec['manifest_hash']==allowlist['manifest_hash'],'Probe manifest/allowlist differs')
 need(load(initial['inputs']['allowlist'])==allowlist and load(initial['inputs']['mapping'])==backing_mapping,'Exact initial input pins differ')
 links={x['path']:x['target'] for x in backing_mapping['canonical_symlinks']};execution=load(backing_mapping['execution']);denied=set()
 for d in allowlist['denied_files']:
  for path in (d['path'],d['resolved']):
   denied.add(path);resolved=link_resolve(path,links);denied.add(resolved)
   for binding in execution['read_only_bindings']:
    target=link_resolve(binding['target'],links)
    if within(resolved,target):
     backing=posixpath.normpath(binding['source']+resolved[len(target):]);denied.add(backing);denied.add(str(Path(backing).resolve()))
 need(spec['denied_paths']==sorted(denied),'Probe must cover exact canonical/resolved/all declared old backing aliases')
 need(spec['protected_readonly_targets']==sorted({x['target'] for x in initial['readonly_mounts']}),'Protected readonly mount closure differs')
 need(spec['writable']=={x['kind']:x['target'] for x in initial['writable_mounts']},'Writable probe roots differ')
 need(spec['run_root']==allowlist['source_plan']['run_root'],'Probe run root differs')
 rows={x['path']:x for x in allowlist['files']}
 for pin in [spec['config'],*spec['public_api_files'].values()]:need(pin['path'] in rows and rows[pin['path']]['sha256']==pin['sha256'],'Probe config/API is not exact allowlisted content')
 sources={x['root'] for x in allowlist['verified_safe_trees'] if x['kind']=='source'};need(sources=={spec['source_root']},'Probe source differs')
 return {'correspondence_verified':True,'manifest_hash':spec['manifest_hash'],'denied_paths':len(denied),'protected_readonly_targets':len(spec['protected_readonly_targets']),'expected_completed':len(mount_plan.get('terminal_prefix',[])),'fit_execution_authorized':False}

def decode_mount_field(s):
 return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),s)
def parse_mountinfo(text):
 rows=[]
 for line in text.splitlines():
  left,sep,right=line.partition(' - ');need(sep and len(left.split())>=6 and len(right.split())>=3,'Malformed mountinfo')
  a,b=left.split(),right.split();rows.append({'id':int(a[0]),'parent':int(a[1]),'target':absolute(decode_mount_field(a[4])),'options':a[5].split(','),'filesystem':b[0],'source':decode_mount_field(b[1])})
 need(rows and len({x['id'] for x in rows})==len(rows),'Missing/duplicate mount identities');return rows

def descriptors():
 out=[]
 for name in os.listdir('/proc/self/fd'):
  if name.isdigit() and int(name)>=3:
   try:out.append({'fd':int(name),'target':os.readlink('/proc/self/fd/'+name)})
   except FileNotFoundError:pass # only the already-closed enumeration fd
 return sorted(out,key=lambda x:x['fd'])
def denied_probe(paths):
 checked=[]
 for path in paths:
  for candidate in (path,'/proc/self/root'+path,'/proc/1/root'+path):
   try:fd=os.open(candidate,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
   except OSError as e:
    need(e.errno in (2,13,20,1),'Unexpected denial error for '+candidate+': '+str(e));checked.append({'path':candidate,'errno':e.errno})
   else:os.close(fd);raise ValueError('Forbidden truth/reference alias is readable: '+candidate)
 return checked

def check_mounts(spec,rows,readonly,device_info,prefix):
 expected=set(spec['protected_readonly_targets']);rw=set(spec['writable'].values());retained={spec['writable']['attempts']+'/'+x for x in prefix};targets={x['target'] for x in rows}
 need(expected|rw|retained|{'/','/proc','/dev'}<=targets,'Required mount target absent')
 ordinary=expected|rw|retained|{'/'}
 need(all(x['filesystem']=='tmpfs' for x in rows if x['target']=='/'),'Namespace root is not the planned empty tmpfs')
 for row in rows:
  path=row['target']
  if path in ordinary:
   ro=path not in rw;need(('ro' in row['options'])==ro and readonly[path]==ro,'Mount readonly/writable policy differs: '+path)
  elif path in VIRTUAL:need(row['filesystem']==VIRTUAL[path],'Virtual mount type differs')
  elif path in DEVICES:need(device_info.get(path)==list(DEVICES[path]),'Unexpected/nonminimal device binding')
  else:raise ValueError('Unapproved mount: '+path)
 need(readonly[spec['run_root']] is True,'Run root must be readonly')
 return {'mounts':rows,'retained_attempts_readonly':sorted(retained),'ordinary_writable':sorted(rw),'virtual_mount_scope':'Only fresh proc, minimal private dev tmpfs/devpts and declared character devices; no host proc/dev directory or extra ordinary writable storage.'}

def device_entries():
 out={}
 for p in Path('/dev').iterdir():
  s=p.lstat()
  if stat.S_ISLNK(s.st_mode):out[p.name]={'kind':'symlink','target':os.readlink(p)}
  elif stat.S_ISCHR(s.st_mode):out[p.name]={'kind':'character','device':[os.major(s.st_rdev),os.minor(s.st_rdev)]}
  elif stat.S_ISDIR(s.st_mode):out[p.name]={'kind':'directory'}
  else:out[p.name]={'kind':'other'}
 return out

def check_devices(entries):
 links={'fd':'/proc/self/fd','stdin':'/proc/self/fd/0','stdout':'/proc/self/fd/1','stderr':'/proc/self/fd/2','ptmx':'pts/ptmx'}
 for name,value in entries.items():
  if '/dev/'+name in DEVICES:need(value=={'kind':'character','device':list(DEVICES['/dev/'+name])},'Device identity differs')
  elif name in links:need(value=={'kind':'symlink','target':links[name]},'Device alias differs')
  elif name=='pts':need(value=={'kind':'directory'},'Private devpts directory differs')
  else:raise ValueError('Extra file/device in private /dev: '+name)
 need('null' in entries,'Private /dev/null missing')

def verify_loaded_public_modules(spec):
 """Permit repeated probes only for modules from the exact selected source tree."""
 from types import ModuleType
 root=(Path(spec['source_root'])/'src'/'orbit_poc').resolve()
 checked=[]
 for name,module in sorted(list(sys.modules.items())):
  if name!='orbit_poc' and not name.startswith('orbit_poc.'):continue
  need(isinstance(module,ModuleType),'Unknown cached public module: '+name)
  file=getattr(module,'__file__',None);origin=getattr(module,'__spec__',None)
  need(isinstance(file,str) and Path(file).is_absolute() and Path(file).suffix=='.py','Cached public module has no source file: '+name)
  path=Path(file).resolve();parts=name.split('.')[1:];stem=root.joinpath(*parts)
  expected=(stem/'__init__.py') if hasattr(module,'__path__') else stem.with_suffix('.py')
  need(path.is_file() and within(str(path),str(root)) and path==expected.resolve(),'Cached public module source differs: '+name)
  need(origin is not None and origin.name==name and isinstance(origin.origin,str) and Path(origin.origin).resolve()==path,'Cached public module import origin differs: '+name)
  package=name if hasattr(module,'__path__') else name.rpartition('.')[0]
  need(module.__package__==package,'Cached public module package differs: '+name)
  if hasattr(module,'__path__'):
   locations=list(module.__path__);spec_locations=origin.submodule_search_locations
   need(len(locations)==1 and Path(locations[0]).resolve()==path.parent and spec_locations is not None and list(spec_locations)==locations,'Cached public package search path differs: '+name)
  else:need(origin.submodule_search_locations is None,'Cached nonpackage has package search locations: '+name)
  checked.append({'name':name,'path':str(path)})
 return checked

def public_checks(spec):
 for pin in [spec['config'],*spec['public_api_files'].values()]:pin_check(pin)
 verify_loaded_public_modules(spec)
 sys.path.insert(0,str(Path(spec['source_root'])/'src'))
 config_module=importlib.import_module('orbit_poc.segmented.config');protocol=importlib.import_module('orbit_poc.segmented.protocol');validation=importlib.import_module('orbit_poc.segmented.validation')
 verify_loaded_public_modules(spec)
 for pin in spec['public_api_files'].values():pin_check(pin)
 for module,name in ((config_module,'config.py'),(protocol,'protocol.py'),(validation,'validation.py')):need(str(Path(module.__file__).resolve())==str(Path(spec['public_api_files'][name]['path']).resolve()),'Imported another public source')
 config=config_module.load_config(spec['config']['path']);root=Path(spec['run_root']);manifest=protocol.verify_manifest(config,root,Path(spec['source_root']));passed=validation.require_passed(config,manifest,root,Path(spec['source_root']))
 need(manifest['manifest_hash']==spec['manifest_hash'] and all(r['source_sha256']==spec['source_sha256'] for r in manifest['runtimes'].values()),'Public verified source/manifest differs')
 need(passed.get('status')=='passed','Public validation guard did not pass')
 ids=[x['attempt_id'] for x in manifest['attempts']];present={x.name for x in (root/'attempts').iterdir()};need(present==set(ids[:len(present)]),'Attempt directories are not a contiguous frozen prefix');cases={x['case_id']:x for x in manifest['cases']};previous=[]
 for attempt in manifest['attempts'][:len(present)]:
  job=protocol.attempt_job(config,manifest,cases[attempt['case_id']],attempt);v=protocol.checkpoint(root/'attempts'/attempt['attempt_id'],job);need(v.get('harness_execution',{}).get('owned_process_group_cleaned') is True,'Prior public checkpoint cleanup missing');previous.append({'attempt_id':attempt['attempt_id'],'status':v['status'],'job_sha256':v['job_sha256']})
 verify_loaded_public_modules(spec)
 for pin in [spec['config'],*spec['public_api_files'].values()]:pin_check(pin)
 return {'manifest_hash':manifest['manifest_hash'],'validation':passed,'terminal_prefix':previous}

def probe(spec,*,allowlist_sha256,mount_plan_sha256,expected_readonly_prefix,public=None,facts=None):
 attribution={'allowlist_sha256':allowlist_sha256,'mount_plan_sha256':mount_plan_sha256,'expected_completed':expected_readonly_prefix}
 validate_spec(spec);need(set(attribution)=={'allowlist_sha256','mount_plan_sha256','expected_completed'} and all(re.fullmatch('[0-9a-f]{64}',attribution[k]) for k in ('allowlist_sha256','mount_plan_sha256')) and type(attribution['expected_completed']) is int and 0<=attribution['expected_completed']<=68,'Missing final host-verified identity strings/prefix')
 if facts is None:
  namespaces={x:os.readlink('/proc/self/ns/'+x) for x in ('pid','net')};fds=descriptors();rows=parse_mountinfo(Path('/proc/self/mountinfo').read_text());denials=denied_probe(spec['denied_paths']);ro={x['target']:bool(os.statvfs(x['target']).f_flag&os.ST_RDONLY) for x in rows};dev={p:[os.major(os.stat(p).st_rdev),os.minor(os.stat(p).st_rdev)] for p in DEVICES if os.path.exists(p) and stat.S_ISCHR(os.stat(p).st_mode)}
  facts={'namespaces':namespaces,'fds':fds,'mounts':rows,'denials':denials,'readonly':ro,'devices':dev,'device_entries':device_entries(),'proc1_pid_namespace':os.readlink('/proc/1/ns/pid'),'proc_self_pid':int(Path('/proc/self/stat').read_text().split()[0]),'pid':os.getpid()}
 need(facts['fds']==[],'Surviving inherited descriptor >=3');check_devices(facts['device_entries']);need(facts['proc1_pid_namespace']==facts['namespaces']['pid'] and facts['proc_self_pid']==facts['pid'],'Proc does not belong to the fresh PID namespace');need(all(facts['namespaces'][x]!=spec['host_namespaces'][x] and re.fullmatch(x+r':\[\d+\]',facts['namespaces'][x]) for x in ('pid','net')),'PID/network namespace is not fresh')
 wanted={q for p in spec['denied_paths'] for q in (p,'/proc/self/root'+p,'/proc/1/root'+p)};need({x['path'] for x in facts['denials']}==wanted and all(x['errno'] in (2,13,20,1) for x in facts['denials']),'Complete negative alias probes missing')
 # Structural namespace checks precede importing any scientific package.
 maybe_prefix=[]
 for row in facts['mounts']:
  p=row['target'];base=spec['writable']['attempts']
  if p!=base and within(p,base):
   rel=p[len(base)+1:];need('/' not in rel,'Unexpected nested attempt mount');maybe_prefix.append(rel)
 checked=check_mounts(spec,facts['mounts'],facts['readonly'],facts['devices'],maybe_prefix)
 result=(public or public_checks)(spec);need(result['manifest_hash']==spec['manifest_hash'] and result['validation'].get('status')=='passed','Public verification result differs');prefix=[x['attempt_id'] for x in result['terminal_prefix']];count=attribution['expected_completed'];need(len(prefix)>=count and set(prefix[:count])==set(maybe_prefix),'Readonly output mounts differ from sealed initial checkpoint prefix')
 # Actual public guards may open libraries temporarily; no descriptors survive.
 if public is None:need(descriptors()==[],'Public verifier left a descriptor open')
 return {'schema':'orbit-poc-segmented-fit-inner-probe-result-v1','status':'passed','specification_content_sha256':canonical(spec),'host_verified_final_artifacts':attribution,'namespaces':facts['namespaces'],'descriptors':facts['fds'],'denial_probes':facts['denials'],'mount_checks':checked,'public_readonly_checks':result,'benchmark_attempts_launched':0,'fit_execution_authorized':False,'release_ready':False,'scope':'Read-only positive/negative probe only. Host-owned guard/admission and full publication policy remain separate.'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--allowlist-sha256',required=True);p.add_argument('--mount-plan-sha256',required=True);p.add_argument('--expected-completed',type=int,required=True);a=p.parse_args();raw=a.spec.read_bytes();need(hashlib.sha256(raw).hexdigest()==a.sha256,'Static probe specification changed')
 try:v=probe(json.loads(raw),allowlist_sha256=a.allowlist_sha256,mount_plan_sha256=a.mount_plan_sha256,expected_readonly_prefix=a.expected_completed)
 except BaseException as e:v={'schema':'orbit-poc-segmented-fit-inner-probe-result-v1','status':'failed','error':type(e).__name__+': '+str(e),'benchmark_attempts_launched':0,'fit_execution_authorized':False};print(json.dumps(v,sort_keys=True));raise SystemExit(1)
 v['specification_file_sha256']=a.sha256;print(json.dumps(v,sort_keys=True))
if __name__=='__main__':main()
