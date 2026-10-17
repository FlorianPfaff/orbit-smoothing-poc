"""Read only current-host exact identities after the pinned14-stage controller ends."""
from pathlib import Path
import argparse,datetime,hashlib,json,os
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-05')
PLAN_SHA='7a67e108c0a914951c3459c02da725c8317db69543f4481bb02df9ab048f7d52'
def need(ok,message):
 if not ok:raise ValueError(message)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):p=Path(p);return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def proc(pid):
 try:
  tail=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split();return {'pid':pid,'start_ticks':int(tail[19]),'state':tail[0]}
 except (FileNotFoundError,ProcessLookupError):return None

def inspect(controller,boot,pid_namespace,probe):
 need(controller['status']=='passed' and controller['returncode']==0 and controller['interrupted_or_timeout']is False,'Controller is not successful terminal')
 need(controller['final_cleanup']['verified']is True and controller['final_cleanup']['errors']==[],'Terminal cleanup incomplete')
 cli=controller['cli_validation'];need(cli['status']=='passed' and cli['passed']==cli['planned']==14,'Not all14 gates passed')
 need(controller['admission']['boot_id']==boot,'Current boot differs')
 driver=controller['admission']['driver_identity'];need(driver['pid_namespace']==pid_namespace,'Cleanup must run in original host PID namespace')
 identities={(driver['pid'],driver['start_ticks']):driver}
 for command in controller['final_cleanup']['commands']:
  need(command['verified']is True and command['live_owned_processes']==[],'Owned cleanup record incomplete')
  for row in command['identities']:identities[(row['pid'],row['start_ticks'])]=row
 need(len(identities)>1,'Owned identities missing')
 matching=[];live=[]
 for pid,start in identities:
  current=probe(pid)
  if current and current['start_ticks']==start:
   matching.append(current)
   if current['state']!='Z':live.append(current)
 need(not live,'Exact owned process remains live')
 return {'owned_identity_count':len(identities),'still_matching':matching,'live_exact_owned':live,'passed':True}

def main(argv=None):
 p=argparse.ArgumentParser()
 for name in ('controller','plan','output'):p.add_argument('--'+name,type=Path,required=True)
 for name in ('controller-sha256','plan-sha256'):p.add_argument('--'+name,required=True)
 a=p.parse_args(argv)
 for path in (a.controller,a.plan,a.output):need(path.is_absolute() and str(path.resolve())==str(path) and not path.is_symlink(),'Canonical cleanup path required')
 need(a.controller==R/'control/validation-controller.json' and a.plan==R/'control/launch-plan.json','Exact current validation paths required')
 need(a.output.parent.is_dir() and not a.output.exists(),'Fresh cleanup output required')
 need(sha(a.controller)==a.controller_sha256 and sha(a.plan)==a.plan_sha256==PLAN_SHA,'Terminal controller/plan pin changed')
 controller=json.loads(a.controller.read_text());plan=json.loads(a.plan.read_text())
 need(controller['plan']==pin(a.plan),'Controller launch plan attribution differs')
 need(plan['execution']['sha256']=='7a83bd89ce76d1e74b664ba421334b35cfac3969339c8083bf932118e074d875','Controller execution changed')
 boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 result=inspect(controller,boot,os.readlink('/proc/self/ns/pid'),proc)
 need(sha(a.controller)==a.controller_sha256,'Terminal controller mutated during check')
 result.update(schema='orbit-poc-independent-exact-owned-process-absence-v1',observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),boot_id=boot,controller=pin(a.controller),terminal_status=controller['status'],plan=pin(a.plan),helper=pin(__file__),scope='Current-boot exact PID/start check in original host PID namespace. Nonexecuting zombies are not live workloads. No signals, native execution or namespace mutation.')
 with a.output.open('x')as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
 print(json.dumps(pin(a.output)));return 0
if __name__=='__main__':raise SystemExit(main())
