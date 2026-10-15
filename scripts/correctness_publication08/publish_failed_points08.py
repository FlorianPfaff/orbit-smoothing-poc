"""Preserve terminal execution08 failed objective points; no numerical gate evaluation."""
import argparse,datetime,gzip,hashlib,html,importlib.util,json,re
from pathlib import Path
BASE=Path('/mnt/d/orbit-numerics-v3.1/correctness')
HELPER=BASE/'control/publish_bounded_retry.py'
EXPECTED='0a2a33dde1906981dae09fce1dae1683e1c60783adad8c3d38d9af3545ccebf5'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest()==EXPECTED
spec=importlib.util.spec_from_file_location('bounded',HELPER);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def publish(manifest_path,manifest_hash,output):
 raw=manifest_path.read_bytes();M.require(M.digest(raw)==manifest_hash,'Transfer manifest changed');transfer=M.decode(raw)
 M.require(transfer['execution_attempt']=='08' and transfer['candidate_control_version']=='07' and transfer['validation_status']=='failed' and transfer['local_match_verified'] is True,'Not the closed failed execution08 transfer')
 root=Path(transfer['local_root']);remote=Path(transfer['remote_root']);records={r['source']:r for r in transfer['files']}
 M.require(len(records)==len(transfer['files']),'Duplicate transfer names')
 M.require(output.is_absolute() and not output.exists(),'New output required')
 selected={};points=[]
 for point in transfer['failed_objective_points']:
  relative=Path(point['point']);M.require(not relative.is_absolute() and '..' not in relative.parts and relative.parts[0]=='validation-07','Unsafe failed point path')
  name='/'.join(relative.parts[1:]);execution=point['execution'];M.require(execution['returncode']!=0 or execution['timed_out'],'Not a failed profile')
  files={};iterations={}
  for original in point['selected_files']:
   path=Path(original);M.require(path.parent==relative,'Unexpected nested point evidence')
   record=records[str(remote/path)];stored=Path(record['relative']);M.require(not stored.is_absolute() and '..' not in stored.parts,'Unsafe stored evidence path')
   value=M.artifact({'path':str(root/stored),**{key:record[key] for key in ('sha256','bytes','encoding','original_sha256','original_bytes')}})
   M.require(len(value)<=64*1024*1024 and not path.name.endswith('.rows.tsv'),'Bulky or unsupported evidence')
   selected[name+'/'+path.name]=value;files[path.name]={'sha256':M.digest(value),'bytes':len(value)}
   match=re.fullmatch(r'qr\.(\d+)\.nuisance_line_search\.json',path.name)
   if match:
    detail=M.decode(value);generation=int(match[1]);M.require(detail.get('schema')=='orbit-poc-native-nuisance-line-search-v1','Unexpected line-search schema')
    M.require('generation' not in detail or detail['generation']==generation,'Contradictory generation label')
    iterations[generation]={key:detail.get(key) for key in ('accepted','undamped_maximum_update_m','full_step_prediction','nuisance_floor_limited','floor_rejection')}
    iterations[generation]['trial_count']=len(detail.get('trials',[]))
  M.require(iterations and sorted(iterations)==list(range(1,max(iterations)+1)),'Failed profile iterations incomplete')
  for generation in iterations:
   for suffix in ('profile.json','factor.json'):
    M.require('qr.'+str(generation)+'.'+suffix in files,'Missing profile/factor/retention evidence')
   if generation<max(iterations):M.require('qr.'+str(generation)+'.retention.json' in files,'Missing superseded-factor retention receipt')
   iterations[generation]['retention_receipt_present']='qr.'+str(generation)+'.retention.json' in files
  M.require('profile.execution.json' in files and M.decode(selected[name+'/profile.execution.json'])==execution,'Profile execution receipt differs')
  points.append({'point':name,'execution':execution,'generations':len(iterations),'iterations':iterations,'files':files,'external_native_artifacts':point.get('external_native_artifacts',[]),'scientific_classification':'failed native nuisance profile; no strict or floor acceptance inferred by this appendix'})
 M.require(any(p['point']=='objective-log_drag_ou/point-006-direction-1.0-1-repeat' and p['generations']==52 for p in points),'Required failed density point006 52-generation history is absent')
 packed={};inventory={}
 for name,value in selected.items():
  sanitized=M.scrub(value.decode()).encode();compressed=gzip.compress(sanitized,mtime=0);target=name+'.gz';M.require(len(compressed)<=16*1024*1024,'Oversized compressed evidence')
  packed[target]=compressed;inventory[target]={'sha256':M.digest(compressed),'bytes':len(compressed),'original_sha256':M.digest(value),'original_bytes':len(value),'published_expanded_sha256':M.digest(sanitized),'published_expanded_bytes':len(sanitized)}
 summary={'schema':'orbit-poc-failed-objective-point-history-v1','execution_attempt':'08','candidate_control_version':'07','transfer_manifest_sha256':manifest_hash,'points':points,'scientific_gate_substitution':False,'covariance_authorized':False,'scope':'Complete failed-point compact iteration receipts. Original mathematical gates remain unchanged and failed. Raw row spools and binary factors stay external; retention receipts identify them.'}
 summary=M.decode(M.scrub(M.encoded(summary).decode()));packed['summary.json']=M.encoded(summary)
 sections=[]
 for point in summary['points']:
  rows=[]
  for generation,row in point['iterations'].items():
   prefix=point['point']+'/qr.'+str(generation)
   labels=[('nuisance_line_search.json','search'),('profile.json','profile'),('factor.json','factor')]
   if row['retention_receipt_present']:labels.append(('retention.json','retention'))
   links=' '.join('<a href="'+html.escape(prefix+'.'+suffix+'.gz',quote=True)+'">'+html.escape(label)+'</a>' for suffix,label in labels)
   if not row['retention_receipt_present']:links+=' (final generation has no superseding-factor retention receipt)'
   rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [generation,row['undamped_maximum_update_m'],row['full_step_prediction'],row['trial_count'],row['accepted'],row['nuisance_floor_limited']])+ '<td>'+links+'</td></tr>')
  sections.append('<h2>'+html.escape(point['point'])+'</h2><p>Native exit '+str(point['execution']['returncode'])+'; '+str(point['generations'])+' retained generations. <a href="'+html.escape(point['point']+'/profile.log.gz',quote=True)+'">Complete native log</a>; <a href="'+html.escape(point['point']+'/profile.execution.json.gz',quote=True)+'">execution receipt</a>; <a href="'+html.escape(point['point']+'/profile.xml.gz',quote=True)+'">original profile XML</a>.</p><table><tr><th>Generation</th><th>Undamped maximum update (m)</th><th>Predicted reduction</th><th>Trials</th><th>Native accepted</th><th>Native floor flag</th><th>Complete receipts</th></tr>'+''.join(rows)+'</table>')
 page='<!doctype html><html lang="en"><meta charset="utf-8"><title>Execution08 failed objective points</title><style>body{font:15px system-ui;max-width:1300px;margin:2rem auto;padding:0 1rem}table{border-collapse:collapse}td,th{border:1px solid #ccd;padding:.4rem}h2{overflow-wrap:anywhere}</style><h1>Execution08 failed objective points</h1><p>These compact receipts preserve failed points omitted from the top-level objective check\'s completed-profile list. Values in the table are reported native fields, not new acceptance decisions. A positive predicted reduction or an accepted earlier step does not establish strict convergence. The original execution08 correctness gate remains failed; no covariance or release acceptance is granted.</p>'+''.join(sections)+'<p>All complete compact point receipts are retained as gzip files. Original and transformed hashes are in <a href="manifest.json">manifest.json</a>; point inventory and exact retention hashes are in <a href="summary.json">summary.json</a>. Private paths are tokenized. Row spools are excluded.</p></html>'
 packed['index.html']=page.encode()
 for name in ('summary.json','index.html'):inventory[name]={'sha256':M.digest(packed[name]),'bytes':len(packed[name]),'transformation':'new presentation of recorded fields'}
 M.require(sum(len(x) for x in packed.values())<=64*1024*1024,'Appendix exceeds64MiB')
 result={'schema':'orbit-poc-failed-point-publication-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'execution_attempt':'08','transfer_manifest_sha256':manifest_hash,'helper_sha256':M.digest(Path(__file__).read_bytes()),'presentation_adapter_sha256':EXPECTED,'files':inventory,'bytes':sum(len(x) for x in packed.values()),'scientific_gate_substitution':False}
 output.mkdir(parents=True)
 for name,value in packed.items():p=output/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
 (output/'manifest.json').write_bytes(M.encoded(result));return result

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=publish(a.manifest,a.manifest_sha256,a.output);print(json.dumps({'files':len(result['files']),'bytes':result['bytes']}))
