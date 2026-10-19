#!/usr/bin/env python3
import hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
B=Path('/home/emper/orbit-nuisance-performance');P=B/'control';Q=B/'replay-pairs01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':sha(p)}
def tree(e):return(e.tag,tuple(sorted(e.attrib.items())),(e.text or '').strip(),tuple(tree(c) for c in e))
prep=json.loads((Q/'preparation.json').read_text()); inv=json.loads((P/'exact-nuisance-replays-local-inputs01.json').read_text())
require(sha(Q/'preparation.json')=='dadc63c0a2fdb067fcc30a00205a0740df4aaa4a1346adc3481c0dcb27d31669','preparation pin')
require(sha(P/'exact-nuisance-replays-local-inputs01.json')=='8526cff36c95ab165d7d29770387a55c356c90e5ba24116422475e1140e47984','inventory pin')
require(sha(inv['pin_source']['path'])==inv['pin_source']['sha256'],'historical pin source'); oldpins=json.loads(Path(inv['pin_source']['path']).read_text())['input_artifacts']; cases={c['role']:c for c in inv['cases']}
require([j['name'] for j in prep['jobs']]==prep['predeclared_order'] and len(prep['jobs'])==4,'order')
require({(j['method'],j['cache'],j['accumulate']) for j in prep['jobs']}=={(m,c,0) for m in cases for c in (0,1)},'coverage')
distinct=[]
for c in cases.values():
 for f in c['distinct_original_inputs']:
  require(oldpins[f['role']]=={'path':f['path'],'sha256':f['sha256']},'wrong historical artifact')
  require(sha(f['path'])==f['sha256'],'historical artifact changed')
  distinct.append({'role':f['role'],**pin(Path(f['path']))})
require(len({c['source_profile']['sha256'] for c in cases.values()})==2,'distinct original profiles')
rows=[]
for j in prep['jobs']:
 c=cases[j['method']];profile=Path(j['profile']);root=profile.parent
 require(root==Q/j['name'] and profile==root/'profile.xml' and root.resolve()==root,'job root')
 require(sha(profile)==j['profile_sha256'],'prepared profile hash')
 require({(f['path'],f['bytes'],f['sha256']) for f in j['input_files']}=={(f['path'],f['bytes'],f['sha256']) for f in c['inputs']},'input ledger')
 require(len(j['input_files'])==177,'input count')
 require(j['source_profile']['path']==c['source_profile']['path'] and j['source_profile']['sha256']==c['source_profile']['sha256'],'original source')
 old=ET.parse(j['source_profile']['path']).getroot();new=ET.parse(profile).getroot()
 outputs=[e for e in new.iter() if e.tag.startswith('outputfile') or e.attrib.get('label')=='tmpDir']
 require(len(outputs)==len(j['output_remapping'])==8,'outputs')
 for e,r in zip(outputs,j['output_remapping']):
  require(e.tag==r['tag'] and (e.text or '').strip()==r['after'],'remap')
  p=Path(r['after']);require(p.is_absolute() and root in p.resolve().parents,'output escape')
  require(not p.exists() or(p.is_dir() and not any(p.iterdir())),'nonempty output')
  for f in j['input_files']:
   ip=Path(f['resolved_path']);require(not ip.is_relative_to(p.resolve()) and not p.resolve().is_relative_to(ip),'input/output overlap')
  e.text=r['before']
 parents={child:parent for parent in new.iter() for child in parent};a=list(new.iter('accumulateEpochObservations'));require(len(a)==1 and a[0].text=='0' and not a[0].attrib and not list(a[0]),'accumulation')
 block=parents[a[0]];step=parents[block];require(block.tag=='selectNormalsBlockStructure' and len(block)==1 and not block.attrib and step.tag=='processingStep' and len(step)==1 and not step.attrib,'inserted structure');parents[step].remove(step)
 require(tree(new)==tree(old),'unapproved XML change')
 require([str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()]==['profile.xml'],'nonfresh job')
 rows.append({'name':j['name'],'profile':pin(profile),'source_profile':pin(Path(j['source_profile']['path'])),'input_count':177,'remapped_outputs':8,'original_xml_reconstructed':True,'fresh_isolated_outputs':True})
r={'schema':'orbit-poc-exact-nuisance-replay-independent-preparation-review-v1','status':'accepted_for_isolated_exact_replay_pairs','script':pin(Path(__file__)),'preparation':pin(Q/'preparation.json'),'input_inventory':pin(P/'exact-nuisance-replays-local-inputs01.json'),'historical_prescribed_pin_source':inv['pin_source'],'distinct_original_artifacts_independently_rehashed':distinct,'jobs':rows,'scope':'Read-only metadata/XML/prescribed physical-input check; no native command. All 177-entry-per-case ledgers match fresh author inventory; only the eight prescribed differentiating artifacts are independently rehashed again.','limitations':['Original failure fixtures retain distinct prescribed physical and statistical inputs; outcomes using the new candidate are pending.','No substitute for the frozen benchmark, whole-fit convergence or release gates.','Execution must use separate frozen runner identities and owned serial limits as in the separately reviewed pair controls.'],'frozen_campaign_changed':False,'native_commands_executed':0}
q=P/'exact-replay-preparation-independent-review01.json'
with q.open('x') as f:json.dump(r,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(q)))
