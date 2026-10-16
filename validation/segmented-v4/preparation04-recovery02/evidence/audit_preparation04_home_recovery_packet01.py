from pathlib import Path
import json,hashlib,importlib.util,os,pwd,socket,datetime
P=Path("/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/preparation-04/control/recovery-startup02/plan.json")
H="fe84073082404a3f1a78ea9a2372b3dbec139ea143170b96a8d926ea284b2a32"
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {"path":str(p),"sha256":sha(p)}
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
assert sha(P)==H
p=json.loads(P.read_text());assert sha(p["helper"]["path"])=="d73d5cf7274347dc78baf468f9c80fa1fddfc3757cf80cc338a07eb1669debcf"
m=load("recovery_reviewed",p["helper"]["path"]);assert m.load_plan(P,H)==p
d=m.load("owned_driver_reviewed",p["helpers"]["driver"]);e=d.load_execution(p["execution"]["path"])
r=m.load("prep_runner_reviewed",p["helpers"]["runner"]);prep=r.load_plan(p["preparation_plan"]["path"],p["preparation_plan"]["sha256"])
assert e["paths"]["root"]=="/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-05"
freeze=m.read(prep["source_freeze"]);actual=d.source_receipt(e["paths"]["source"]);assert actual==freeze["source"]
assert actual["sha256"]=="87a3a10ab538d606837e1ebcfa579c1b5cc6bfe57f2b3220b47bfe340cab1130" and len(actual["files"])==384
config=m.read(prep["config"]);natives={}
for role in ("segmented_runtime","dense_runtime"):
 for key in ("native","segmented_solver"):
  if key in config[role]:
   item=config[role][key];actualpath=d.resolved_host_path(item["path"],e);assert sha(actualpath)==item["sha256"];natives[role+"/"+key]=item
assert natives["segmented_runtime/native"]["sha256"]=="eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133"
failed=[];owned=[]
for item in p["failure_records"]:
 assert sha(item["path"])==item["sha256"];failed.append(item)
 if Path(item["path"]).name=="process.json":
  value=m.read(item);assert value["status"]=="failed" and value["final_cleanup"]["verified"] and value["final_cleanup"]["errors"]==[]
  for row in value["final_cleanup"]["commands"]:
   for ident in row["identities"]:assert not m.exact_live(ident);owned.append(ident)
smoke=m.read(p["smoke"]);assert not Path(smoke["output"]).exists()
control=Path(prep["control_root"])
for name in ("preparation-launch.json","pipeline.json","preparation-driver.log"):assert not (control/name).exists()
for name in ("preparation","preparation-status.json","prepared-catalog.json","prepared-manifest.json","preparation-jobs","attempts"):assert not (Path(e["paths"]["run"])/name).exists()
admission=d.admission(e,[]);assert admission["status"]=="admitted"
print(json.dumps({"schema":"orbit-poc-preparation04-home-recovery-packet-independent-readback-v1","passed":True,"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"plan":pin(P),"host":p["host"],"account":p["account"],"environment":p["environment"],"resource":p["resource"],"global_lock":p["global_lock"],"source":{"sha256":actual["sha256"],"file_count":len(actual["files"])},"config":prep["config"],"natives":natives,"unchanged_failure_records":failed,"old_owned_processes_nonlive":owned,"startup_output_absent":True,"preparation_output_markers_absent":True,"admission":admission,"benchmark_fits":0,"no_launch":True},indent=2))
