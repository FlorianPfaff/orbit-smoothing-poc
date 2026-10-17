import pathlib,json,hashlib,datetime,os
r=pathlib.Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-04');p=r/'control/validation-controller.json';b=p.read_bytes();c=json.loads(b);assert hashlib.sha256(b).hexdigest()=='76a17184e28246c76b6f3d6d346ae12caf31dab548dd9130b79f10bb2e1ef814';boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip();observed=[];live=[]
def proc(pid):
 try:
  raw=pathlib.Path('/proc')/str(pid)/'stat';v=raw.read_text();tail=v[v.rfind(')')+2:].split();return {'pid':pid,'start_ticks':int(tail[19]),'state':tail[0]}
 except (FileNotFoundError,ProcessLookupError):return None
identities={}
for command in c['final_cleanup']['commands']:
 for x in command['identities']:identities[(x['pid'],x['start_ticks'])]=x
identity=c['admission']['driver_identity'];identities[(identity['pid'],identity['start_ticks'])]=identity
for (pid,start),x in identities.items():
 now=proc(pid)
 if now and now['start_ticks']==start:
  observed.append(now)
  if now['state']!='Z':live.append(now)
assert boot==c['admission']['boot_id']
assert c['status']=='passed' and c['final_cleanup']['verified'] and not c['final_cleanup']['errors']
print(json.dumps({'schema':'orbit-poc-independent-exact-owned-process-absence-v1','observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot,'controller':{'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)},'terminal_status':c['status'],'owned_identity_count':len(identities),'still_matching':observed,'live_exact_owned':live,'passed':not live,'scope':'Read-only current-boot exact PID/start identity check; no signals or namespace mutation.'},indent=2))
