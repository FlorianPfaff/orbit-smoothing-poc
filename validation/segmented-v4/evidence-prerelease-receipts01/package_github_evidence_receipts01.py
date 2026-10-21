"""Preserve recorded GitHub prerelease responses; no network request or upload."""
from pathlib import Path
import datetime,hashlib,json
R=Path('/mnt/d/orbit-segmented-v4');C=R/'control';O=R/'publication-github-evidence-receipts01'
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink();b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def put(name,b):
 with (O/name).open('xb') as f:f.write(b)
def jput(name,v):put(name,(json.dumps(v,indent=2,sort_keys=True)+'\n').encode())
assert not O.exists();O.mkdir()
specs=[('validation04','v4-validation-04','f883252352cbdc16e122e6bc7797166588095c6b',R/'validation-evidence-assets04-01/manifest.json',{'manifest.json':('d3c0b8589edb57d45d3b4c38058e03bc3b933bfcda8f1d605dc80b32e7114d03',676650),'segmented-v4-validation04-full-evidence.tar.gz':('7f90578b56dcdf26f3537beef5574e814ae5f909cf56194943db33e36803208e',21672414)}),('shifted02','v4-shifted-02','6a21f41e2602183a61e13f985c96859f8f622266',R/'publication-shifted02-assets-01/manifest.json',{'manifest.json':('18770eebec2c9507ef3f0d02762dcd8e15e119f572a52126cdbeb018877a4026',16332),'segmented-v4-shifted02-full-capture.tar.gz':('17c16d8ee9c628f33346e61bbbc065eba6830afb10c54a686b5c8ac3eeb85c5c',14653964)})]
receipts=[]
for name,tag,commit,asset_manifest,expected in specs:
 p=C/(name+'-github-release-readback01.json');d=json.loads(p.read_text());assert d['tag_name']==tag and d['target_commitish']==commit and d['prerelease'] is True and d['draft'] is False
 assert d['html_url']=='https://github.com/FlorianPfaff/orbit-smoothing-poc/releases/tag/'+tag
 assert {x['name'] for x in d['assets']}==set(expected)
 assets=[]
 for a in d['assets']:
  digest,size=expected[a['name']];assert a['state']=='uploaded' and a['size']==size and a['digest']=='sha256:'+digest
  assets.append({k:a[k] for k in ['id','name','state','size','digest','browser_download_url']})
 assert pin(asset_manifest)['sha256']==expected['manifest.json'][0] and pin(asset_manifest)['bytes']==expected['manifest.json'][1]
 put(p.name,p.read_bytes());receipts.append({'tag':tag,'url':d['html_url'],'target_commit':commit,'published_at':d['published_at'],'prerelease':True,'v4_release_ready':False,'recorded_github_response':pin(p),'local_asset_manifest':pin(asset_manifest),'assets':assets})
jput('receipt.json',{'schema':'orbit-poc-evidence-prerelease-recorded-response-verification-v1','verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':True,'receipts':receipts,'network_requests_by_this_verifier':0,'source_archives_reread':False,'scope':'Exact recorded GitHub API responses verified for prerelease status, target commit, uploaded asset membership, server digests and sizes against the separately audited local manifest pins. This does not claim a fresh download or current server state after the recorded responses. These are evidence prereleases, not the v4.0 release.'})
put('README.txt',b'These recorded GitHub responses verify publication of the validation04 and shifted02 evidence prereleases, their exact commit targets, asset digests and sizes. They are not a v4.0 release or completed benchmark. No new network request or archive download was performed by this metadata verifier. Later server changes are outside this recorded observation.\n')
put('package_github_evidence_receipts01.py',Path(__file__).read_bytes())
entries=[{'relative':p.name,'sha256':pin(p)['sha256'],'bytes':p.stat().st_size} for p in sorted(O.iterdir())]
jput('manifest.json',{'schema':'orbit-poc-evidence-publication-receipts-manifest-v1','entries':entries,'files':len(entries),'bytes':sum(x['bytes'] for x in entries),'release_ready':False,'builder':pin(Path(__file__))})
print(json.dumps({'root':str(O),'manifest':pin(O/'manifest.json'),'receipt':pin(O/'receipt.json')}))
