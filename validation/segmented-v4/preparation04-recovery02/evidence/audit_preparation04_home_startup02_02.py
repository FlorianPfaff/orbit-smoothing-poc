from pathlib import Path
import json,hashlib,importlib.util,datetime,os
B=Path("/mnt/seagate10tb/orbit-segmented-v4-florianpfaff");P=B/"preparation-04/control/recovery-startup02/plan03.json";H="3aa619222f8c7d59f2b7e980525a65cac6cd992a6fc95cd63c6b8bbdc05cfd79"
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {"path":str(p),"sha256":sha(p)}
def raw(p):
 b=Path(p).read_bytes();return {**pin(p),"bytes":len(b),"text":b.decode()}
assert sha(P)==H
plan=json.loads(P.read_text());assert sha(plan["helper"]["path"])=="b4630b23afde0b9680f51c09adeafb8bc470f507a0d3d372a74fa38d9b9ce2e2"
spec=importlib.util.spec_from_file_location("reviewed_recovery",plan["helper"]["path"]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);assert m.load_plan(P,H)==plan
smoke=m.read(plan["smoke"]);probe=m.read(plan["probe"])
processpath=Path(smoke["output"])/"process.json";process=json.loads(processpath.read_text());m.check_startup(process,plan);assert process["returncode"]==0 and not process["interrupted_or_timeout"]
recoverypath=Path(plan["control_root"])/"startup-result.json";recovery=json.loads(recoverypath.read_text());assert recovery["phase"]=="startup" and recovery["status"]=="passed" and recovery["plan"]==pin(P) and recovery["startup"]==pin(processpath) and recovery["effective_environment"]==plan["environment"] and not recovery["handoff_committed"]
resultpath=Path(process["result"]["path"]);result=m.read({k:process["result"][k] for k in ("path","sha256")});assert result["config"]==probe["config"] and result["source_sha256"]==probe["source_sha256"]
assert sha(resultpath)=="2a83fd4f94d3f2ae5897fe52608be33560511f106568aa74428bf4b57fe2de6a"
assert sha(processpath)=="b346203dc667c36037225db6d2ca135adfeb11f35d495c8392645ac692984a2f"
assert sha(recoverypath)=="a0d9e9ba24cd7b54c5d124d280e831a23e87a25de475e012d5a9e91e1b8205ad"
assert process["admission"]["status"]=="admitted" and process["admission"]["boot_id"]==plan["host"]["boot_id"]
owned=[]
for row in process["final_cleanup"]["commands"]:
 for identity in row["identities"]:assert not m.exact_live(identity);owned.append(identity)
for item in plan["failure_records"]:assert sha(item["path"])==item["sha256"]
prep=m.read(plan["preparation_plan"]);control=Path(prep["control_root"])
for name in ("preparation-launch.json","pipeline.json","preparation-driver.log"):assert not (control/name).exists()
e=m.read(plan["execution"])
for name in ("preparation","preparation-status.json","prepared-catalog.json","prepared-manifest.json","preparation-jobs","attempts"):assert not (Path(e["paths"]["run"])/name).exists()
print(json.dumps({"schema":"orbit-poc-preparation04-home-startup02-independent-readback-v1","passed":True,"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"plan":pin(P),"process":pin(processpath),"result":pin(resultpath),"recovery":pin(recoverypath),"actual_environment":recovery["effective_environment"],"owned_processes_nonlive":owned,"original_failure_records_preserved":plan["failure_records"],"files":[raw(p) for p in (processpath,resultpath,recoverypath)],"preparation_not_launched":True,"benchmark_fits":0,"physical_propagations":0},indent=2))
