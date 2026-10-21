#!/usr/bin/env python3
"""Read-only structural check of prepared integration fixtures; no native runs."""
import hashlib,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
B=Path('/home/emper/orbit-nuisance-performance'); P=B/'control'; Q=B/'paired01'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(v,m):
    if not v: raise ValueError(m)
def tree(e): return (e.tag,tuple(sorted(e.attrib.items())),(e.text or '').strip(),tuple(tree(c) for c in e))
prep=json.loads((Q/'preparation.json').read_text()); inv=json.loads((P/'fixture-discovery01.json').read_text()); cases={c['method']:c for c in inv['cases']}
require(sha(Q/'preparation.json')=='388a1253c8d999da8623d4f63f3727dd10c06f1727d7c9238eaa6cea8cc212ed','preparation pin')
require(sha(P/'fixture-discovery01.json')==prep['fixture_inventory']['sha256'],'inventory pin')
require(len(prep['jobs'])==8 and [j['name'] for j in prep['jobs']]==prep['predeclared_order'],'order')
require({(j['method'],j['accumulate'],j['cache']) for j in prep['jobs']}=={(m,a,c) for m in cases for a in (0,1) for c in (0,1)},'factorial coverage')
results=[]
for j in prep['jobs']:
    case=cases[j['method']]; profile=Path(j['profile']); root=profile.parent
    require(root==Q/j['name'] and profile==root/'profile.xml','job root')
    require(not root.is_symlink() and root.resolve()==root,'job symlink')
    require(j['input_files']==case['files'] and len(j['input_files'])==177,'exact input ledger')
    require(j['source_profile']==case['profile'],'source profile ledger')
    require(sha(profile)==j['profile_sha256'] and sha(j['source_profile']['path'])==j['source_profile']['sha256'],'xml hash')
    old=ET.parse(j['source_profile']['path']).getroot(); new=ET.parse(profile).getroot()
    newinputs=[tree(x) for x in new.iter() if x.tag.startswith('inputfile') or x.attrib.get('label')=='orbitPocCanonicalAttitude']
    oldinputs=[tree(x) for x in old.iter() if x.tag.startswith('inputfile') or x.attrib.get('label')=='orbitPocCanonicalAttitude']
    require(newinputs==oldinputs,'input XML structure changed')
    outputs=[x for x in new.iter() if x.tag.startswith('outputfile') or x.attrib.get('label')=='tmpDir']
    require(len(outputs)==len(j['output_remapping'])==8,'complete output remapping')
    for e,r in zip(outputs,j['output_remapping']):
        require(e.tag==r['tag'] and (e.text or '').strip()==r['after'],'remap order/value')
        target=Path(r['after']); require(target.is_absolute() and root in target.parents,'output escape')
        require(target.resolve().is_relative_to(root),'resolved output escape')
        require(not target.exists() or (target.is_dir() and not any(target.iterdir())),'preexisting output content')
        for f in j['input_files']:
            p=Path(f['resolved_path']); require(not p.is_relative_to(target.resolve()) and not target.resolve().is_relative_to(p),'output/input overlap')
        e.text=r['before']
    parents={c:p for p in new.iter() for c in p}
    accum=list(new.iter('accumulateEpochObservations')); require(len(accum)==1,'accum count')
    e=accum[0]; require(e.text==str(j['accumulate']) and not e.attrib and not list(e),'accum exact')
    wrapper=parents[e]; step=parents[wrapper]
    require(wrapper.tag=='selectNormalsBlockStructure' and len(wrapper)==1 and not wrapper.attrib,'block wrapper')
    require(step.tag=='processingStep' and len(step)==1 and not step.attrib,'step wrapper')
    parents[step].remove(step)
    require(tree(new)==tree(old),'other XML semantic change')
    files=[str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()]
    require(files==['profile.xml'],'nonfresh prepared job')
    results.append({'name':j['name'],'profile_sha256':j['profile_sha256'],'inputs':177,'remapped_outputs':8,'source_tree_reconstructed':True,'fresh_output_tree':True})
result={'schema':'orbit-poc-nuisance-pair-preparation-review-v1','status':'passed_metadata_checks','script':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__)},'preparation':{'path':str(Q/'preparation.json'),'sha256':sha(Q/'preparation.json')},'jobs':results,'scientific_inputs_rehashed_here':False,'input_hash_basis':'Earlier independent 177-file-per-case fixture-discovery01; this review verifies ledger equality and XML hashes, not repeated bulk hashing.','native_commands_executed':0}
out=P/'paired01-independent-preparation-result.json'
with out.open('x') as f: json.dump(result,f,indent=2,sort_keys=True); f.write('\n')
print(json.dumps({'path':str(out),'sha256':sha(out),'jobs':len(results)}))
