"""Dated interruption/restart publication; never claims a later fit from a launch."""
from pathlib import Path
import json,hashlib,sys
C=Path('/mnt/d/orbit-segmented-v4/control');BASE=C.parent;RECOVERY=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume');CAMPAIGN=RECOVERY/'benchmark-01'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def require(x,m):
 if not x:raise ValueError(m)
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str)and len(v['sha256'])==64:yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
def run(spec):
 require(set(spec)=={'schema','output','sources'},'Unexpected option');require(spec['schema']=='orbit-poc-original150-interruption18-publication-spec-v1','Wrong schema')
 files={}
 for r in spec['sources']:
  p=Path(r['path']);require(p.is_file()and not p.is_symlink()and(p.is_relative_to(C)or p.is_relative_to(RECOVERY)),'Unexpected input');require(pin(p)==r,'Changed exact record: '+str(p));files[str(p)]=p.read_bytes()
 def doc(rel):return json.loads(files[str(C/rel)])
 root=doc('original150-interruption18-root-review01.json');post=doc('original150-eighteen-prefix-postappend01.json');proposal=doc('original150-interrupted-attempt18-proposal01/proposal.json');live=doc('original150-resume04-live02.json');observation=doc('original150-boot-interruption-20261016-02/observation.json');resume=doc('original150-resume04-root-review01.json')
 require(root['passed']and resume['passed']and post['passed'],'Missing accepted audit');require(post['actual_three_files_equal_approved_candidates']and post['new_eighteenth_archived_checkpoint_validation_passed']and post['first_seventeen_result_index_bytes_unchanged'],'Prefix preservation missing')
 require(live['terminal_attempts']==18 and live['terminal_statuses']=={'failed':5,'timeout':9,'interrupted':2,'complete':2},'Wrong dated counts');require(not live['campaign_adapter_receipt_present']and not live['next_request_present'],'Dated phase differs');require(live['startup_receipt_body']['status']=='verified'and len(live['startup_receipt_body']['trees'])==9,'Startup not verified')
 require(observation['partial_regular_file_count']==224 and observation['partial_regular_bytes']==570869254 and observation['existing_input_alias_count']==9 and observation['boot_changed'],'Interruption inventory differs');require(observation['parent_wall_time_seconds']is None and observation['parent_peak_memory_bytes']is None and observation['parent_returncode']is None and not observation['process_cleanup_verified'],'Invented interruption metrics')
 for row in proposal['append_files']:
  require(files[row['destination']]==files[row['candidate']['path']],'Actual append differs from candidate')
 out=Path(spec['output']);require(out==BASE/'publication-original150-interruption18-resume04-01'and not out.exists(),'Fresh publication required');out.mkdir();rows=[];copies={};documents=[]
 def put(rel,b,origin=None,attribution=None):
  q=out/rel;q.parent.mkdir(parents=True,exist_ok=True)
  with q.open('xb')as f:f.write(b)
  r={'path':rel,'sha256':sha(b),'bytes':len(b)}
  if origin:r['original']=origin;copies[(origin['path'],origin['sha256'])]=rel
  if attribution:r['attribution']=attribution
  rows.append(r)
 for name,b in sorted(files.items()):
  p=Path(name);rel=('evidence/'+str(p.relative_to(C)))if p.is_relative_to(C)else('campaign-records/'+str(p.relative_to(RECOVERY)));put(rel,b,pin(p),'Exact already-recorded local evidence; historical copies retain their original source attribution.')
  if p.suffix=='.json':
   try:documents.append((name,json.loads(b)))
   except json.JSONDecodeError:pass
 # Associate explicit old source->copy receipts only, never identical hashes alone.
 for row in observation['copies']:
  k=(row['copy']['path'],row['copy']['sha256']);require(k in copies,'Historical copy missing');require(row['source']['sha256']==row['copy']['sha256'],'Historical attribution differs');copies[(row['source']['path'],row['source']['sha256'])]=copies[k]
 refs={}
 for name,d in documents:
  for r in walk(d):
   if not r['path'].startswith('/'):continue
   key=(r['path'],r['sha256']);e=refs.setdefault(key,{'path':r['path'],'sha256':r['sha256'],'recorded_in':[]})
   if 'bytes'in r:e['bytes']=r['bytes']
   if name not in e['recorded_in']:e['recorded_in'].append(name)
   if key in copies:e.update(availability='copied_exact_bytes',copy=copies[key])
   else:e['availability']='external_payload_not_read_or_copied_by_this_publication'
 summary={'schema':'orbit-poc-original150-interruption18-resume04-publication-v1','observed_at':live['observed_at'],'status':'interruption18_retained_restart_runtime_verified_input_checks_pending','terminal_outcomes':{'planned':150,'terminal':18,'failed':5,'timeout':9,'interrupted':2,'legacy_complete':2},'interruption':{'attempt':proposal['attempt'],'old_boot':observation['previous_boot_id'],'current_boot':observation['current_boot_id'],'partial_files':224,'partial_bytes':570869254,'input_aliases':9,'parent_wall_time_seconds':None,'parent_peak_memory_bytes':None,'parent_returncode':None,'cleanup_claimed':False,'covariance_authorized':False,'retried':False,'first17_index_and_result_bytes_preserved':True,'three_exact_files_appended':True},'restart':{'launch':live['launch'],'startup_receipt':live['startup_receipt'],'nine_runtime_trees_verified':True,'owned_live_chain':live['owned_live_chain'],'campaign_input_verification_complete':False,'attempt19_started':False,'observation_scope':'Dated observation only; no later fit or continuing liveness is inferred.'},'scope':['The original frozen source, executable, inputs, seeds and settings are retained. No corrected-v3.1 or v4 executable is substituted.','Two complete results use archived legacy criteria; they do not establish corrected-v3.1/v4 strict convergence.','All original partial outputs and checkpoints remain preserved. Selected compact logs/receipts are copied here; bulky native arrays and other partial files remain external with exact inventories.','The earlier taskset CPU1 metadata-checker invocation failure is retained. The fresh controller was independently admitted and launched with its original CPU30 numerical affinity.','No v4 full build, full suite, benchmark fit or release result is inferred.'],'release_ready':False}
 put('summary.json',(json.dumps(summary,indent=2)+'\n').encode());put('external-evidence.json',(json.dumps({'schema':'orbit-poc-explicit-copy-attribution-v1','records':list(refs.values())},indent=2)+'\n').encode())
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Original150 interruption and restart</title><style>body{font:16px system-ui;line-height:1.55;max-width:960px;margin:3rem auto}td,th{padding:.6rem;border-bottom:1px solid #ccc;text-align:left}code{word-break:break-all}</style><h1>Original150: interruption retained, runtime startup verified</h1><p><strong>18/150 terminal records: five failures, nine timeouts, two interruptions and two legacy completions.</strong> These counts distinguish terminal bookkeeping from successful numerical results. The legacy completions use their original criteria.</p><p>A WSL boot change interrupted attempt18. Its 224 regular partial files (570,869,254 bytes), nine original input aliases and the first seventeen result/index records were preserved. Independent review checked every partial-file hash. Exactly three reviewed interruption records were appended under the existing lock; unknown wall time, return code and peak memory remain null. No numerical retry, covariance, convergence or cleanup was invented.</p><p>The unchanged controller was launched at 21:30:42 UTC on October 16, 2026. At the dated observation in <a href="summary.json">the summary</a>, its nine frozen runtime trees had passed verification, and the original recovery helper was live on CPU30 performing mandatory campaign-input verification. The adapter and attempt19 request were still absent. This is not a claim that attempt19 had started or that the process remains live later.</p><p>The original numerical source, binary, data and settings remain frozen. A prior metadata-checker invocation restricted to CPU1 failed its CPU30 membership check and is retained separately; it did not launch a numerical worker. V4 is a separate effort, and no v4 success is inferred here.</p><p><a href="evidence/original150-interruption18-root-review01.json">Interruption review</a> · <a href="evidence/original150-resume04-root-review01.json">Continuation review</a> · <a href="external-evidence.json">Exact copy/external attribution</a> · <a href="manifest.json">Byte manifest</a></p></html>'''
 put('index.html',page.encode());m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Original frozen150 interruption and dated restart verification only; attempt19 has not been observed starting.'};(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');return {'output':str(out),'manifest':pin(out/'manifest.json'),'files':len(rows),'bytes':m['total_bytes'],'references':len(refs)}
if __name__=='__main__':
 p=Path(sys.argv[1]);require(sha(p.read_bytes())==sys.argv[2],'Changed spec');print(json.dumps(run(json.loads(p.read_bytes())),indent=2))
