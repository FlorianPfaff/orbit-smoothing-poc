from pathlib import Path
import argparse,datetime,hashlib,json,shlex,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control');R=C/'campaign09-recovery-readback03/control/recovery.json';O=C/'campaign09-launch01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(v,m):
 if not v:raise ValueError(m)
p=argparse.ArgumentParser();p.add_argument('--root-review',type=Path,required=True);p.add_argument('--root-sha256',required=True);p.add_argument('--independent-review',type=Path,required=True);p.add_argument('--independent-sha256',required=True);a=p.parse_args()
require(sha(R)=='b1c43fc3dd7985cc01467d331c0f125fc6d2a8a0ef9a56d02ae77ae4c972aa3d','Recovery identity changed')
for path,digest in [(a.root_review,a.root_sha256),(a.independent_review,a.independent_sha256)]:require(sha(path)==digest,'Review identity changed')
v=json.loads(R.read_text());require(v['status']=='assembled_metadata' and v['fit_attempts']==0,'Unexpected recovery status')
command=v['launch_command'];require(command==['/usr/bin/taskset','-c','32','/usr/bin/python3','-B','/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/fit-seal-control-07/with_segmented_campaign_host_direct01.py','--plan','/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/fit-campaign-control-09/host-view-plan.json','--sha256','0276468ce244308ba8b082f41377bf30a61f371e41639b7e4e40c1eab597efe7'],'Launch command changed')
remote=['env','PATH=/usr/bin:/bin','HOME=/home/florianpfaff','PYTHONDONTWRITEBYTECODE=1','OPENBLAS_NUM_THREADS=1','OMP_NUM_THREADS=1','MKL_NUM_THREADS=1','NUMEXPR_NUM_THREADS=1']+command
argv=['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090',shlex.join(remote)]
O.mkdir();request={'recovery':{'path':str(R),'sha256':sha(R)},'reviews':[{'path':str(path),'sha256':digest} for path,digest in [(a.root_review,a.root_sha256),(a.independent_review,a.independent_sha256)]],'remote_argv':remote,'ssh_argv':argv,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Exact independently reviewed recovery09 launch. The unchanged actual inner positive and denial probes gate fitting.'}
with (O/'request.json').open('x') as f:json.dump(request,f,indent=2);f.write('\n')
start=time.monotonic()
with (O/'stdout.log').open('x') as out,(O/'stderr.log').open('x') as err:r=subprocess.run(argv,stdout=out,stderr=err,text=True)
result={'returncode':r.returncode,'elapsed_seconds':time.monotonic()-start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'request_sha256':sha(O/'request.json'),'stdout_sha256':sha(O/'stdout.log'),'stderr_sha256':sha(O/'stderr.log')}
with (O/'process.json').open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result));print((O/'stdout.log').read_text())
if r.returncode:raise SystemExit(r.returncode)
