#!/usr/bin/env python3
"""Assemble two immutable, attributed correction bundles without changing gates."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re

MAX_FILE=16*1024*1024
MAX_TOTAL=64*1024*1024
IDS=('04','05')
SCOPE=('Preserved execution history for the same frozen v3.1 correction candidate. '
       'Bundle contents and reported statuses are copied without modification. '
       'This index does not recompute or promote numerical gates, accept covariance, '
       'certify the v3.1 release, or replace the frozen 150-attempt benchmark. '
       'The earlier candidate01 publication remains separate.')


def require(value,message):
    if not value:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def pairs(items):
    result={}
    for key,value in items:
        require(key not in result,'Duplicate JSON key');result[key]=value
    return result


def decode(raw):
    value=json.loads(raw,object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    require(isinstance(value,dict),'Metadata must be a JSON object')
    # Reject exponent overflow too; encoding cannot silently preserve infinity.
    json.dumps(value,allow_nan=False)
    return value


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def read(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),'Missing or symlink metadata: '+str(path))
    require(path.stat().st_size<=MAX_FILE,'File exceeds 16 MiB bound')
    raw=path.read_bytes();require(len(raw)<=MAX_FILE,'File grew beyond bound');return raw


def digest(value,label):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value),'Invalid SHA256: '+label)
    return value


def pinned(item,label):
    require(isinstance(item,dict) and {'path','sha256'}<=set(item)<= {'path','sha256','bytes'},'Invalid artifact pin: '+label)
    require(isinstance(item.get('path'),str),'Artifact path must be a string')
    path=Path(item['path']);require(path.is_absolute() and '..' not in path.parts,'Artifact path must be absolute')
    raw=read(path);require(sha(raw)==digest(item['sha256'],label),'Pinned artifact changed: '+label)
    require(item.get('bytes',len(raw))==len(raw),'Pinned artifact size differs: '+label)
    return decode(raw),raw,path


def path_token(value):return 'private-path-sha256:'+sha(value.encode())


def scrub(value):
    if isinstance(value,dict):return {scrub(k):scrub(v) for k,v in value.items()}
    if isinstance(value,list):return [scrub(v) for v in value]
    if not isinstance(value,str):return value
    leading=re.match(r'^(?:/(?!/)|[A-Za-z]:[\\/]).*?(?=:\s|\r?\n)',value,re.DOTALL)
    if leading:return path_token(leading[0])+scrub(value[len(leading[0]):])
    if value.startswith('/') or re.match(r'^[A-Za-z]:[\\/]',value):return path_token(value)
    value=re.sub(r'''(?<![A-Za-z0-9_])(-[IL])((?:/(?!/)|[A-Za-z]:[\\/])[^\s<>"'&]+)''',lambda m:m[1]+path_token(m[2]),value)
    value=re.sub(r'''(["'])(/(?!/)[^"']+|[A-Za-z]:[\\/][^"']+)\1''',lambda m:m[1]+path_token(m[2])+m[1],value)
    return re.sub(r'''(?<![A-Za-z0-9_:/])(?:[A-Za-z]:[\\/][^\s<>"'&]+|/(?!/)[^\s<>"'&]+)''',lambda m:path_token(m[0]),value)


def checked_bundle(item):
    require(isinstance(item,dict) and set(item)=={'path','manifest_sha256'},'Bundle path and manifest identity required')
    root=Path(item['path']);require(root.is_absolute() and not root.is_symlink() and root.is_dir(),'Bundle must be a real absolute directory')
    manifest_raw=read(root/'manifest.json');require(sha(manifest_raw)==digest(item['manifest_sha256'],'bundle manifest'),'Bundle manifest changed')
    manifest=decode(manifest_raw)
    require(manifest.get('schema')=='orbit-poc-correctness-publication-bundle-v4','Unsupported publication protocol')
    require(manifest.get('release_acceptance')=='not_assessed' and manifest.get('frozen_campaign_reclassified') is False,'Unexpected release or benchmark promotion')
    require(type(manifest.get('reported_audit_passed')) is bool and isinstance(manifest.get('missing_receipts'),list),'Missing publication outcomes')
    entries=manifest.get('files');require(isinstance(entries,list) and 1<=len(entries)<=4096,'Empty or oversized publication inventory')
    files={};records={};total=0
    for entry in entries:
        require(isinstance(entry,dict) and isinstance(entry.get('destination'),str),'Invalid publication file record')
        name=entry['destination'];relative=Path(name)
        require(not relative.is_absolute() and relative.parts and all(x not in ('.','..') for x in relative.parts)
                and str(relative)==name and name not in files and name not in ('manifest.json','README.txt'),'Unsafe or duplicate publication destination')
        path=root/relative;require(path.resolve().is_relative_to(root.resolve()),'Publication path escapes bundle')
        raw=read(path);require(sha(raw)==digest(entry.get('published_sha256'),'published file') and len(raw)==entry.get('published_bytes'),'Publication bytes differ from manifest')
        total+=len(raw);require(total<=MAX_TOTAL,'Bundle exceeds total bound')
        files[name]=raw;records[name]=entry
    required={'index.html','summary.json','independent-audit.json','provenance/pipeline-04.json','provenance/execution.json','historical/pipeline-02.json','historical/pipeline-03.json'}
    require(required<=set(files),'Bundle lacks current or preserved historical provenance')
    files['manifest.json']=manifest_raw;files['README.txt']=read(root/'README.txt')
    observed=set()
    for path in root.rglob('*'):
        require(not path.is_symlink(),'Symlink inside publication bundle')
        require(path.is_file() or path.is_dir(),'Unsupported publication filesystem entry')
        if path.is_file():observed.add(str(path.relative_to(root)))
    require(observed==set(files),'Unlisted publication files')
    require(sum(map(len,files.values()))<=MAX_TOTAL,'Bundle exceeds total bound')
    return manifest,files,records,root


def recorded_step(post,name):
    values=[s for s in post.get('steps',[]) if isinstance(s,dict) and s.get('name')==name]
    require(len(values)==1,'Postprocessing step is not unique: '+name)
    value=values[0];require(value.get('cleanup_verified') is True and not value.get('result_error'),'Postprocessing step incomplete: '+name)
    return value


def inspect_attempt(number,item,source_sha256):
    require(set(item)=={'bundle','execution','run','postprocess','execution_root'},'Unknown attempt attribution fields')
    execution,execution_raw,execution_path=pinned(item['execution'],'attempt'+number+' execution')
    run,run_raw,run_path=pinned(item['run'],'attempt'+number+' run')
    post,post_raw,post_path=pinned(item['postprocess'],'attempt'+number+' postprocess')
    manifest,files,records,bundle_root=checked_bundle(item['bundle'])
    paths=execution.get('paths') or {}
    require(execution.get('schema')=='orbit-poc-correctness-execution-v1' and paths.get('root')==item['execution_root'],'Attempt execution root differs from declared attribution')
    root=Path(item['execution_root']);require(root.is_absolute() and Path(paths.get('run','')).is_relative_to(root),'Execution run is outside the declared root')
    require(run.get('status') in ('passed','failed') and run.get('finished_at') and run.get('final_cleanup',{}).get('verified') is True,'Attempt is not closed with verified cleanup')
    require(run.get('execution',{}).get('sha256')==sha(execution_raw),'Run does not bind its actual execution configuration')
    require(run.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'},'History must not invent a campaign resume')
    require(run.get('source',{}).get('sha256')==source_sha256 and len(run.get('source',{}).get('files',{}))==758,'Attempt does not preserve frozen source identity')
    require(sha(json.dumps(run['source']['files'],sort_keys=True,separators=(',',':')).encode())==source_sha256,'Executed source inventory digest is inconsistent')
    require(post.get('schema')=='orbit-poc-correctness-postprocess04-run-v1' and post.get('status')=='completed' and post.get('finished_at'),'Postprocessing did not complete')
    require(post.get('validation_pipeline',{}).get('sha256')==sha(run_raw)
            and post.get('validation_pipeline',{}).get('path')==str(Path(paths['run'])/'pipeline.json'),'Postprocessing run attribution differs')
    require(post.get('source',{}).get('sha256')==source_sha256,'Postprocessing source identity differs')
    require(isinstance(post.get('source',{}).get('commit'),str) and re.fullmatch('[0-9a-f]{40}',post['source']['commit']),'Missing exact source commit')
    require(manifest.get('source_inventory_sha256')==source_sha256,'Published source identity differs')
    require(manifest.get('reported_pipeline_status')==run['status'] and manifest.get('reported_evidence_status')==post.get('scientific_status'),'Published outcomes differ from actual execution')
    require(records['provenance/pipeline-04.json'].get('original_sha256')==sha(run_raw)
            and records['provenance/execution.json'].get('original_sha256')==sha(execution_raw),'Published provenance is attributed to another execution')
    audit=decode(files['independent-audit.json']);summary=decode(files['summary.json'])
    require(type(audit.get('passed')) is bool and audit['passed']==manifest['reported_audit_passed'],'Audit result differs from manifest')
    require(summary.get('schema')=='orbit-correction-evidence-report-v4' and summary.get('candidate_evidence_status')==manifest['reported_evidence_status'],'Report outcome differs from manifest')
    require(summary.get('release_acceptance')=='not_assessed' and summary.get('frozen_campaign_reclassified') is False,'Report promotes release or benchmark status')
    for name,destination,code in (('audit','independent-audit.json',0 if audit['passed'] else 1),('report','summary.json',0),('collect','manifest.json',0)):
        step=recorded_step(post,name)
        expected=sha(files[destination]) if name=='collect' else records[destination]['original_sha256']
        require(step.get('returncode')==code and step.get('result',{}).get('sha256')==expected,'Postprocessing result identity differs: '+name)
    if not run.get('native'):
        require(run['status']=='failed' and manifest.get('native_sha256') is None and summary.get('native_tests',{}).get('status')=='missing','Missing accepted executable is misreported')
        require(not any(s.get('name')=='native-tests' for s in run.get('steps',[])),'Native tests ran despite absent accepted native identity')
        classification='infrastructure_failure_before_native_validation'
    else:
        require(manifest.get('native_sha256')==run['native']['sha256'],'Native identity differs between execution and bundle')
        classification=manifest['reported_evidence_status']
    identity={'execution_attempt_id':number,'classification':classification,'reported_pipeline_status':run['status'],
        'reported_evidence_status':manifest['reported_evidence_status'],'reported_audit_passed':audit['passed'],
        'native_tests_status':summary.get('native_tests',{}).get('status','missing'),
        'execution_sha256':sha(execution_raw),'run_sha256':sha(run_raw),'postprocess_sha256':sha(post_raw),
        'execution_root_sha256':sha(str(root).encode()),'bundle_manifest_sha256':sha(files['manifest.json']),
        'source_sha256':source_sha256,'source_commit':post.get('source',{}).get('commit'),
        'files_copied':len(files),'bytes_copied':sum(map(len,files.values())),
        'missing_receipts':manifest['missing_receipts'],'copy_policy':'All original compact bundle files copied byte for byte.'}
    return identity,files,(execution_path,run_path,post_path,bundle_root),run


def document(attempts):
    esc=lambda x:html.escape(str(x),quote=True)
    rows=[]
    for number in IDS:
        item=attempts[number]
        rows.append('<tr><td><a href="attempt-'+number+'/index.html">Attempt '+number+'</a></td><td>'+esc(item['classification'])+'</td><td>'+esc(item['reported_evidence_status'])+'</td><td>'+esc(item['reported_audit_passed'])+'</td><td>'+esc(item['native_tests_status'])+'</td></tr>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        '<title>v3.1 correction execution history</title><style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem;color:#19212a}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:.6rem;text-align:left}code{overflow-wrap:anywhere}</style>'
        '<h1>v3.1 correction execution history</h1><p>'+esc(SCOPE)+'</p>'
        '<p>Attempt04 linked an executable, but its build smoke check failed because the host did not provide GLIBC_2.38. No native tests or scientific validation checks ran in that attempt. The linked executable was not accepted or archived as a validated binary.</p>'
        '<table><thead><tr><th>Execution</th><th>Classification</th><th>Evidence status</th><th>Audit passed</th><th>Native tests</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
        '<p>The existing report schemas describe protocol versions; the execution IDs04 and05 here identify distinct runs. Earlier validation02 failure and validation03 interruption remain in each bundle’s preserved provenance. The separate candidate01 publication retains its fuller numerical evidence.</p>'
        '<p>Audited numerical-floor-limited progress is not strict nuisance convergence and cannot authorize covariance. See each unchanged report for limitations and missing or failed checks.</p>'
        '<p><a href="evidence/independent-attempt04-review.json">Independent attempt04 infrastructure review</a> · <a href="manifest.json">Complete identities and copy manifest</a></p></html>\n').encode()


def assemble(plan_path,expected_plan_sha256):
    raw=read(plan_path);require(sha(raw)==digest(expected_plan_sha256,'plan'),'History plan changed')
    plan=decode(raw)
    require(set(plan)=={'schema','assembler_sha256','source_sha256','attempts','independent_review04','output'},'Unknown or missing history plan fields')
    require(plan['schema']=='orbit-poc-correctness-history-plan-v1','Unsupported history plan')
    require(sha(read(Path(__file__)))==digest(plan['assembler_sha256'],'assembler'),'History assembler changed')
    digest(plan['source_sha256'],'source')
    require(isinstance(plan['attempts'],dict) and set(plan['attempts'])==set(IDS),'Both distinct execution attempts04 and05 are required')
    output=Path(plan['output']);require(output.is_absolute() and not output.exists() and not output.is_symlink(),'Choose a NEW absolute history output directory')
    attempts={};files={};inputs=[];runs={}
    for number in IDS:
        item,contents,protected,run=inspect_attempt(number,plan['attempts'][number],plan['source_sha256'])
        attempts[number]=item;runs[number]=run;inputs.extend(protected)
        for name,value in contents.items():files['attempt-'+number+'/'+name]=value
    require(attempts['04']['run_sha256']!=attempts['05']['run_sha256']
            and attempts['04']['execution_sha256']!=attempts['05']['execution_sha256']
            and attempts['04']['execution_root_sha256']!=attempts['05']['execution_root_sha256'],
            'Two attempt labels refer to the same execution')
    require(attempts['04']['source_commit']==attempts['05']['source_commit'],'Source commits differ between execution attempts')
    review,review_raw,review_path=pinned(plan['independent_review04'],'independent04 review');inputs.append(review_path)
    require(review.get('schema')=='orbit-poc-infrastructure04-independent-review-v1' and review.get('passed') is True
            and review.get('classification')=='infrastructure_failure_dynamic_loader_abi'
            and review.get('scientific_validation')=='not_run' and review.get('accepted_native_identity') is False
            and review.get('linked_executable_present') is True and review.get('owned_cleanup_rechecked') is True
            and review.get('live_exact_owned_processes')==[],'Independent04 review does not establish the actual infrastructure failure')
    require(review.get('pipeline',{}).get('sha256')==attempts['04']['run_sha256']
            and review.get('postprocess',{}).get('sha256')==attempts['04']['postprocess_sha256']
            and review.get('publication_manifest',{}).get('sha256')==attempts['04']['bundle_manifest_sha256']
            and review.get('source_sha256')==plan['source_sha256'],'Independent04 review is attributed to another attempt')
    require(attempts['04']['classification']=='infrastructure_failure_before_native_validation','Attempt04 was reclassified as scientific validation')
    for path in inputs+[Path(plan_path)]:
        protect=path if path.is_dir() else path.parent
        require(not output.resolve().is_relative_to(protect.resolve()),'History output cannot be inside an input root')
    review_published=encoded(scrub(review));files['evidence/independent-attempt04-review.json']=review_published
    files['index.html']=document(attempts)
    records=[{'destination':name,'sha256':sha(value),'bytes':len(value),'transformation':'verbatim original compact bundle' if name.startswith('attempt-') else 'sanitized independent review' if name.startswith('evidence/') else 'new history index'} for name,value in sorted(files.items())]
    manifest={'schema':'orbit-poc-correctness-execution-history-v1','created_at':datetime.now(timezone.utc).isoformat(),'scope':SCOPE,
        'source_sha256':plan['source_sha256'],'source_commit':attempts['04']['source_commit'],'attempts':attempts,
        'plan_sha256':sha(raw),'assembler_sha256':plan['assembler_sha256'],
        'independent_attempt04_review':{'original_sha256':sha(review_raw),'published_sha256':sha(review_published),'original_bytes':len(review_raw),'published_bytes':len(review_published),'transformation':'Canonical JSON with absolute private paths tokenized; classifications, numerical values and artifact hashes unchanged.'},
        'release_acceptance':'not_assessed','frozen_campaign_reclassified':False,'files':records}
    files['manifest.json']=encoded(manifest)
    require(all(len(value)<=MAX_FILE for value in files.values()) and sum(map(len,files.values()))<=MAX_TOTAL,'Combined history exceeds fixed publication bounds')
    output.mkdir(parents=True,exist_ok=False)
    for name,value in files.items():
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(value)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--plan-sha256',required=True)
    args=parser.parse_args();result=assemble(args.plan,args.plan_sha256)
    print(json.dumps({'history_created':True,'attempts':{k:v['reported_evidence_status'] for k,v in result['attempts'].items()},'files':len(result['files'])+1,'release_acceptance':'not_assessed'}))


if __name__=='__main__':main()
