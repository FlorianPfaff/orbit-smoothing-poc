from pathlib import Path
import json,hashlib,os,datetime
B=Path("/mnt/seagate10tb/orbit-segmented-v4-florianpfaff");C=B/"preparation-04/control";R=C/"recovery-startup02"
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {"path":str(p),"sha256":sha(p)}
def raw(p):
 b=Path(p).read_bytes();return {**pin(p),"bytes":len(b),"text":b.decode()}
pinplan={"path":str(R/"plan03.json"),"sha256":"3aa619222f8c7d59f2b7e980525a65cac6cd992a6fc95cd63c6b8bbdc05cfd79"};assert pin(R/"plan03.json")==pinplan
plan=json.loads((R/"plan03.json").read_text());launchpath=C/"preparation-launch.json";launch=json.loads(launchpath.read_text());recpath=R/"launch-result.json";recovery=json.loads(recpath.read_text())
assert recovery["status"]=="preparation_launched" and recovery["handoff_committed"] is True and recovery["plan"]==pinplan and recovery["preparation_launch"]==pin(launchpath)
assert recovery["startup"]["sha256"]=="b346203dc667c36037225db6d2ca135adfeb11f35d495c8392645ac692984a2f"
assert recovery["effective_environment"]==recovery["observed_driver_environment"]==plan["environment"]
assert launch["launch_committed"] and launch["execution_sha256"]==plan["execution"]["sha256"] and launch["pins_sha256"]==plan["preparation_pins"]["sha256"] and launch["launch_helper_sha256"]==plan["helpers"]["launcher"]["sha256"]
ident=launch["driver_process"];boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip();assert ident["boot_id"]==boot==plan["host"]["boot_id"]
proc=Path("/proc")/str(ident["pid"]);f=(proc/"stat").read_text().rsplit(")",1)[1].split();assert int(f[19])==ident["start_ticks"] and f[0]!="Z"
argv=[a.decode() for a in (proc/"cmdline").read_bytes().split(b"\0") if a];assert argv==launch["argv"]==launch["observed_argv"]
assert argv[-4:]==["--plan",plan["preparation_plan"]["path"],"--sha256",plan["preparation_plan"]["sha256"]]
env={}
for item in (proc/"environ").read_bytes().split(b"\0"):
 k,sep,val=item.partition(b"=")
 if sep and k.decode() in plan["environment"]:env[k.decode()]=val.decode()
assert env==plan["environment"] and sorted(os.sched_getaffinity(ident["pid"]))==[24,25,26,27]
locks=[line for line in Path("/proc/locks").read_text().splitlines() if " "+str(ident["pid"])+" " in line and line.split()[5].endswith(":"+str(plan["global_lock"]["identity"]["ino"]))];assert len(locks)==1
for item in plan["failure_records"]:assert sha(item["path"])==item["sha256"]
files=[raw(launchpath),raw(recpath)];pipeline=None
if (C/"pipeline.json").exists():
 pipeline=json.loads((C/"pipeline.json").read_text());assert pipeline["status"]=="running" and {k:pipeline["plan"][k] for k in ("path","sha256")}==plan["preparation_plan"] and pipeline["benchmark_attempts"]==0 and not pipeline["release_ready"]
 assert pipeline["admission"]["status"]=="admitted" and pipeline["admission"]["driver_identity"]["pid"]==ident["pid"]
 files.append(raw(C/"pipeline.json"))
print(json.dumps({"schema":"orbit-poc-preparation04-home-launch-independent-readback-v1","passed":True,"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"plan":pinplan,"launch":pin(launchpath),"recovery":pin(recpath),"process":{"pid":ident["pid"],"start_ticks":ident["start_ticks"],"boot_id":boot,"parent":int(f[1]),"state":f[0],"argv":argv,"affinity":sorted(os.sched_getaffinity(ident["pid"]))},"environment":env,"global_lock_lines":locks,"pipeline":pipeline,"files":files,"old_failure_records_unchanged":True,"benchmark_fits":0,"scope":"Actual durable preparation handoff/current ownership only; no completion or fit claim."},indent=2))
