from pathlib import Path
import hashlib,io,json,tarfile
C=Path('/mnt/d/orbit-segmented-v4/control');P=C/'direct-fit-helper-install12';B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');T=B/'fit-seal-control-07'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p,path=None):return {'path':str(path or p),'sha256':sha(p)}
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
new=C/'normalization-sealing-draft01';collector=C/'normalization-support-draft01/prepare_segmented_fit_allowlist04.py'
request=json.loads((C/'direct-fit-helper-install11/sealing-request04.json').read_text());request['helper']=pin(new/'seal_direct_fit_inputs05.py',T/'seal_direct_fit_inputs05.py');request['helpers']['allowlist']=pin(collector,T/collector.name);request['output_root']=str(T/'sealed-inputs-04');write(P/'sealing-request05.json',request)
files=[collector,new/'seal_direct_fit_inputs05.py',new/'plan_direct_campaign06.py',new/'plan_direct_sealing_view06.py',P/'sealing-request05.json'];rows=[]
archive=P/'helpers-and-request.tar'
with tarfile.open(archive,'x:') as tar:
 for source in files:
  data=source.read_bytes();member=tarfile.TarInfo(source.name);member.mode=0o644;member.size=len(data);member.mtime=0;tar.addfile(member,io.BytesIO(data));rows.append({'name':source.name,'source':pin(source),'target':str(T/source.name),'sha256':sha(source),'bytes':len(data),'mode':420})
smokes=[]
for num in ('01','02'):
 cap=C/('loader-alias-smoke-terminal'+num)/'manifest.json';smokes.append({'capture':pin(cap),'files':json.loads(cap.read_text())['files']})
write(P/'install-plan.json',{'schema':'orbit-poc-direct-fit-helper-install-plan-v2','control':{'path':str(T),'device':2048,'inode':239600078},'files':rows,'archive':pin(archive),'preserved_inventory':pin(P/'preserved-control-inventory01.json'),'preserved_smokes':smokes,'preserved_campaign_captures':[{'path':str(B/'campaign07-terminal-01/manifest.json'),'sha256':'20c14ed104f0a7e1dd3f270f29fd43ceb0e59922d9ccb3535d5a19abcf15dbc0'},{'path':str(B/'campaign08-terminal-01/manifest.json'),'sha256':'cd831883bd951e2d36deadd1f8cadd0954e9ed5daa5c4e785226868d5785325d'}],'fresh_install_root':str(B/'direct-fit-helper-inputs-12'),'request':pin(P/'sealing-request05.json',T/'sealing-request05.json'),'driver':{'path':str(B/'validation-07/control/owned_driver09.py'),'sha256':'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd'},'execution':{'path':str(B/'preparation-07/control/execution.json'),'sha256':'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3'},'fit_attempts':0,'native_executions':0,'scope':'Five exclusive metadata helper/request writes. Preserve exact original metadata trees and all zero-fit failures; no namespace or scientific/native execution.'})
print(json.dumps({'plan_sha256':sha(P/'install-plan.json'),'request_sha256':sha(P/'sealing-request05.json'),'archive_sha256':sha(archive)}))
