from pathlib import Path
import argparse,base64,datetime,hashlib,json
p=argparse.ArgumentParser();p.add_argument('--root',required=True,choices=('tangent-complete-single-01','tangent-complete-single-02','tangent-complete-closure-01','tangent-complete-closure-02'));a=p.parse_args();D=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')/a.root;C=D/'control';l=json.loads((C/'native-check-launch.json').read_text());j=json.loads((C/'pipeline.json').read_text());boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();rows=[];queue=[l['driver_process']['pid']];seen=set()
while queue:
 pid=queue.pop(0)
 if pid in seen:continue
 seen.add(pid);r=Path('/proc')/str(pid)
 try:
  f=(r/'stat').read_text().rsplit(')',1)[1].split();argv=[x.decode()for x in(r/'cmdline').read_bytes().split(b'\0')if x];status=(r/'status').read_text().splitlines();env=dict(x.split(b'=',1)for x in(r/'environ').read_bytes().split(b'\0')if b'='in x);children=[int(x)for x in(r/'task'/str(pid)/'children').read_text().split()];queue+=children;rows.append({'pid':pid,'start_ticks':int(f[19]),'parent':int(f[1]),'state':f[0],'argv':argv,'affinity':next(x for x in status if x.startswith('Cpus_allowed_list:')),'HOME':env.get(b'HOME',b'').decode(),'pid_namespace':str((r/'ns/pid').readlink())})
 except(FileNotFoundError,ProcessLookupError):pass
logs=[]
for q in (D/'run/replay').rglob('*.log'):
 b=q.read_bytes();logs.append({'path':str(q),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'tail_base64':base64.b64encode(b[-4096:]).decode()})
print(json.dumps({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot,'root':str(D),'launch':l,'pipeline':j,'processes':rows,'driver_exact_live':any(x['pid']==l['driver_process']['pid']and x['start_ticks']==l['driver_process']['start_ticks']and x['state']not in('Z','X')for x in rows),'lock_rows':[x for x in Path('/proc/locks').read_text().splitlines()if'217252784'in x],'logs':logs},indent=2))
