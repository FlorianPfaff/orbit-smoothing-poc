#!/usr/bin/env python3
"""Prepare an additions-only evidence commit after pinned publication review. No push."""
import argparse, hashlib, json, re, subprocess
from datetime import datetime, timezone
from pathlib import Path
import verify_packet as v

ROOT=Path(__file__).resolve().parent
PREFIX='validation/v4-fit-reliability/candidate06-terminal-stop01/'
REMOTE='https://github.com/FlorianPfaff/orbit-smoothing-poc.git'
BRANCH='v4-fit-reliability'
WIN_GIT='/mnt/c/Program Files/Git/cmd/git.exe'
TITLE='Archive candidate06 terminal admission stop and retained validation outcomes'
CASE_NAMES=['manifest_total','report_success','cold_fit_claim','cleanup_claim','competitor_claim','audit_changed','missing_responsibility','missing_timing_limit','omitted_member','extra_member','remapped_provenance','unlaunched_stage_pass']
PRESERVED_PACKAGING_FAILURES=[
 ('assembly01/verification-portable.json','initial-publication-verification-failure.json','962d732c8dd15fdfa85445b437ed264a883cd88c9a9343374c21ad2d70fabb33'),
 ('assembly01/packet/artifact-manifest.json','initial-publication-manifest.json','7b1c0bffa75d34febe04afd6716cb8b271ab18d068cfcc6ef1f996d55bb8a045'),
 ('execution01/source/verify_packet.py','initial-publication-verifier.py','d12a379f8901783313c715cf8f99ba281624c968c08175f1bf2d6ccf2a874e69'),
 ('execution02/correction.json','publication-verifier-correction.json','3901273d0c625dd44b9a1c115d5b2dde843e37e2fef4f9746d5d11a2b435b5f5'),
 ('execution02/verifier-correction.patch','publication-verifier-correction.patch','14b55ed0a35e90fadfa0abfac42192d28ee749c4ed9023883937add5e71bc843'),
 ('execution02/source-snapshot.json','publication-corrected-source-snapshot.json','eb650e82468714658f7799febb10dbebd84b16747f083a2857bb719069e06e3a')]
EXPECTED_FAILURES=['manifest totals']+['report exact recomputation from evidence']*4+['exact independent audit trust anchor','README.md essential disclosure','README.md essential disclosure','manifest exact planned paths','manifest exact planned paths','exact14 original copy mapping','report exact recomputation from evidence']

def pin(p):
 p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':v.sha(p)}
def require(value,message):
 if not value:raise ValueError(message)
def verify_pin(row):
 p=Path(row['path']);require(p.is_absolute() and p.is_file() and not p.is_symlink() and pin(p)==row,'Changed required publication evidence: '+str(p));return p
def save(p,value):
 with p.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--authority',type=Path,required=True);parser.add_argument('--authority-sha256',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 require(v.sha(args.authority)==args.authority_sha256,'Commit authority bytes changed')
 a=v.load(args.authority);require(a['schema']=='candidate06-terminal-commit-authority-v1' and a['approved_for_commit_preparation'] is True,'Explicit reviewed commit-preparation authority required')
 require(a['target_pr']==9 and a['target_branch']==BRANCH and a['new_prefix']==PREFIX,'Wrong publication target')
 require(isinstance(a['parent_commit'],str) and re.fullmatch('[0-9a-f]{40}',a['parent_commit']),'Pin the actual reviewed remote parent first')
 require(a['terminal_audit_sha256']==v.AUDIT_SHA and a['active_source_changes'] is False and a['push_authorized_by_this_script'] is False,'Source/release/push scope changed')
 output=args.output;require(output.is_absolute() and output.parent==ROOT and output.resolve()==output and re.fullmatch(r'commit[0-9]+',output.name),'Fresh commitNN child under draft root required')
 manifest=verify_pin(a['manifest']);packet=manifest.parent;require(manifest.name=='artifact-manifest.json','Wrong manifest identity')
 packet_manifest=v.load(manifest);manifest_sha=v.sha(manifest)
 # Commit preparation never substitutes a new scientific or publication check.
 review_paths=[]
 for name,mode in [('portable_verification',False),('original_verification',True)]:
  path=verify_pin(a[name]);review_paths.append(path);r=v.load(path)
  require(r['passed'] is True and r['manifest_sha256']==manifest_sha and r['verify_originals'] is mode and r['scientific_code_executed'] is False and r['check_count']==len(r['checks'])>0 and all(x['passed'] is True for x in r['checks']),'Missing exact successful '+name)
 tamper_path=verify_pin(a['tamper_result']);review_paths.append(tamper_path);t=v.load(tamper_path)
 require(t['schema']=='candidate06-terminal-packet-tamper-tests-v1' and t['passed'] is True and t['tests']==t['expected_tests']==13 and t['case_registry']==CASE_NAMES and [x['name'] for x in t['cases']]==CASE_NAMES and all(x['passed'] is True for x in t['cases']) and t['original_packet_unchanged'] is True and t['manifest_sha256']==manifest_sha and t['scientific_code_executed'] is False,'Missing complete tamper evidence')
 for row in [t['checker'],t['harness'],t['baseline'],*[x['result'] for x in t['cases']],*[x['verification'] for x in t['cases']]]:verify_pin(row)
 baseline=v.load(t['baseline']['path']);require(baseline['passed'] is True and baseline['manifest_sha256']==manifest_sha and all(x['passed'] is True for x in baseline['checks']),'Tamper baseline is not a verified unchanged packet')
 for case,expected_failure in zip(t['cases'],EXPECTED_FAILURES):
  raw=v.load(case['result']['path']);observed=v.load(case['verification']['path']);failure=next((x['name'] for x in observed['checks'] if not x['passed']),None)
  require(raw['name']==case['name'] and raw['passed'] is True and raw['actual_failure']==raw['expected_failure']==expected_failure and observed['passed'] is False and failure==expected_failure,'Tamper result did not exercise the required semantic rejection')
 require(t['checker']==pin(ROOT/'verify_packet.py') and t['harness']==pin(ROOT/'test_packet_tampering.py'),'Checker or tamper source changed after testing')
 independent_path=verify_pin(a['independent_publication_review']);review_paths.append(independent_path);ind=v.load(independent_path)
 require(ind.get('independent') is True and ind.get('passed') is True and ind.get('manifest_sha256')==manifest_sha and ind.get('check_count')==len(ind.get('checks',[]))>0 and all(x['passed'] is True for x in ind['checks']),'Independent exact packet review missing')
 require(len(review_paths)==len(set(review_paths)),'Review receipts must be separately attributed')
 require(packet_manifest['file_count']==len(packet_manifest['files']) and {r['path'] for r in packet_manifest['files']}=={d for s,d in v.SELECTION}|v.GENERATED,'Unexpected packet inventory')
 require({str(p.relative_to(packet)) for p in packet.rglob('*') if p.is_file()}=={r['path'] for r in packet_manifest['files']}|{'artifact-manifest.json'},'Packet files added or missing')
 for r in packet_manifest['files']:
  p=packet/r['path'];require(p.resolve().is_relative_to(packet.resolve()) and not p.is_symlink() and p.stat().st_size==r['bytes'] and v.sha(p)==r['sha256'],'Packet drift before commit')
 require(v.sha(packet/'verify_packet.py')==v.sha(ROOT/'verify_packet.py'),'Reviewed packet checker differs from tested checker')
 require('[codex]' not in TITLE.lower(),'Forbidden title marker')
 output.mkdir();gitdir=output/'git';windows='D:/'+str(gitdir.relative_to('/mnt/d')).replace('\\','/')
 save(output/'intent.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'authority':pin(args.authority),'source':pin(Path(__file__)),'packet_manifest':pin(manifest),'parent_commit':a['parent_commit'],'new_prefix':PREFIX,'no_push':True})
 commands=[]
 def run(argv,data=None):
  r=subprocess.run(argv,input=data,capture_output=True,timeout=180);commands.append({'argv':argv,'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace') if len(r.stdout)<=8192 else None,'stdout_bytes':len(r.stdout),'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr':r.stderr.decode(errors='replace') if len(r.stderr)<=8192 else None,'stderr_bytes':len(r.stderr),'stderr_sha256':hashlib.sha256(r.stderr).hexdigest()})
  require(r.returncode==0,'Git command failed; preserve this attempt');return r.stdout
 def git(*values,data=None):return run(['git','--git-dir='+str(gitdir),*values],data).decode().strip()
 try:
  run([WIN_GIT,'init','--bare','--initial-branch='+BRANCH,windows])
  run([WIN_GIT,'--git-dir='+windows,'fetch','--no-tags','--depth=1',REMOTE,'refs/heads/'+BRANCH])
  parent=git('rev-parse','FETCH_HEAD');require(parent==a['parent_commit'],'Remote head changed; no overwrite or automatic rebase')
  require(not git('ls-tree','-r',parent,'--',PREFIX),'Additive prefix already exists')
  targets=[(p,PREFIX+str(p.relative_to(packet))) for p in sorted(packet.rglob('*')) if p.is_file()]
  extras=[(args.authority,'commit-authority.json'),(a['portable_verification']['path'],'verification-portable.json'),(a['original_verification']['path'],'verification-originals.json'),(tamper_path,'tamper-result.json'),(independent_path,'independent-review.json'),(ROOT/'test_packet_tampering.py','test-packet-tampering.py'),(Path(__file__),'prepare-additive-commit.py')]
  for relative,name,digest in PRESERVED_PACKAGING_FAILURES:
   path=ROOT/relative;require(path.is_file() and not path.is_symlink() and v.sha(path)==digest,'Preserved packaging failure changed: '+relative);extras.append((path,name))
  targets.extend((Path(p),PREFIX[:-1]+'-'+name) for p,name in extras)
  for path,name in targets:require(not git('ls-tree',parent,'--',name),'Would overwrite an existing published path')
  git('read-tree',parent);entries=[];filepins=[]
  for path,name in targets:
   blob=git('hash-object','-w','--stdin',data=path.read_bytes());entries.append('100644 '+blob+'\t'+name+'\n');filepins.append({'git_path':name,'git_blob':blob,'source':pin(path)})
  git('update-index','--index-info',data=''.join(entries).encode());tree=git('write-tree');diff=git('diff','--cached','--name-status',parent)
  require(set(diff.splitlines())=={'A\t'+name for path,name in targets},'Commit contains modifications/deletions or unplanned paths')
  body=TITLE+'\n\nPreserve the failed first sequence, four completed stages, six unlaunched numerical stages and both unlaunched cold fits. Record the overlapping-review scheduling error and timing limitation. No active implementation, threshold, benchmark or earlier packet changes.\n'
  commit=git('-c','user.name=Florian Pfaff','-c','user.email=6773539+FlorianPfaff@users.noreply.github.com','commit-tree',tree,'-p',parent,data=body.encode())
  git('update-ref','refs/heads/candidate06-terminal-stop01',commit)
  require(git('diff-tree','--no-commit-id','--name-status','-r',commit)==diff,'Committed path scope differs')
  for path,name in targets:require(run(['git','--git-dir='+str(gitdir),'show',commit+':'+name])==path.read_bytes(),'Committed blob differs from verified source')
  save(output/'file-pins.json',{'commit':commit,'tree':tree,'files':filepins});save(output/'commands.json',{'commands':commands})
  receipt={'schema':'candidate06-terminal-additive-commit-v1','status':'prepared_not_pushed','commit':commit,'tree':tree,'parent':parent,'files_added':len(targets),'files_modified':0,'files_deleted':0,'all_commit_blobs_verified':True,'manifest_sha256':manifest_sha,'pushed':False,'pr_updated':False,'active_source_changed':False,'native_runs':0,'git_directory':str(gitdir),'remote_branch':BRANCH}
  save(output/'result.json',receipt);print(json.dumps(receipt));return 0
 except BaseException as exc:
  save(output/'failure.json',{'status':'failed','error':repr(exc),'commands':commands,'partial_git_state_preserved':True,'pushed':False});raise
if __name__=='__main__':raise SystemExit(main())
