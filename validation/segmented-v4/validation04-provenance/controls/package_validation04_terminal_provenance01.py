"""Append-only compact provenance for audited validation04 terminal publication."""
from pathlib import Path
import argparse,datetime,hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control');R=C.parent
FILES=['package_validation04_terminal_provenance01.py','segmented-validation04-presentation-plan-01.json','validation04-terminal-presentation01.stdout.json','validation04-terminal-presentation01.stderr.log','validation04-terminal-distribution01.stdout.json','validation04-terminal-distribution01.stderr.log','capture_segmented_validation01.py','capture_segmented_linearization_arrays01.py','present_segmented_validation03.py','distribute_segmented_validation03_02.py','test_capture_segmented_validation01.py','test_capture_segmented_linearization_arrays01.py','test_present_segmented_validation03.py','test_distribute_segmented_validation03_02.py','distribute_segmented_validation03.py','present_segmented_validation02_v2.py','test_present_segmented_validation02_v2.py','archive_validation04_terminal01.py','audit_validation04_terminal01.py','audit_validation04_terminal02.py','validation04-terminal-capture01.stdout.json','validation04-terminal-capture01.stderr.log','validation04-terminal-arrays01.stdout.json','validation04-terminal-arrays01.stderr.log','validation04-terminal-archive01.json','validation04-terminal-archive01.stderr.log','validation04-terminal-audit-01.log','validation04-independent-cleanup-01/result.json','validation04-independent-cleanup-01/stderr.log','validation04-independent-cleanup-01/probe.py','validation04-controller-terminal-check01.json','validation04-terminal-publication-recipe01.json','render_validation04_pending_report01.py','validation04-report-before-prepare-interface-01.json','validation04-report-before-prepare-interface-01.stdout.json','validation04-report-before-prepare-interface-01.stderr.log','validation04-pending-report-plan-identity01.json','preparation-profile-fix01/independent-review02-scope-clarification.json']
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def copy(src,root,rel):
 assert src.is_file() and not src.is_symlink(),src
 before=pin(src);target=root/rel;target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('xb') as f:f.write(src.read_bytes())
 after=pin(target);assert all(after[k]==before[k] for k in ['sha256','bytes']) and pin(src)==before
 return {'path':rel,'sha256':after['sha256'],'bytes':after['bytes'],'original':before}
def package(audit,audit_hash,full,distribution,output):
 assert pin(audit)['sha256']==audit_hash
 a=json.loads(audit.read_text());assert a['consistency_passed'] is True and a['cleanup_verified'] is True
 assert a['schema']=='orbit-poc-segmented-validation-terminal-independent-review-v1' and a['scientific_status']=='passed_scoped_checks'
 assert a['identity']['comparison_source_sha256']=='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
 assert a['benchmark_attempts_executed']==0 and a['release_ready'] is False
 f=json.loads(full.read_text());d=json.loads(distribution.read_text())
 assert f['scientific_status']==d['scientific_status']==a['scientific_status']
 assert f['source_plan']['independent_audit']==pin(audit)
 assert d['source_publication']==pin(full)
 assert not output.exists();output.mkdir(parents=True)
 files=[copy(C/n,output,'controls/'+n) for n in FILES]
 files.append(copy(audit,output,'independent-terminal-audit.json'))
 text='''<!doctype html><meta charset="utf-8"><title>Validation04 terminal provenance</title><style>body{font:16px system-ui;max-width:1000px;margin:3em auto;padding:0 1em}code{overflow-wrap:anywhere}</style><h1>Validation04 terminal provenance</h1><p>The complete prescribed 14-stage validation passed its independent terminal audit. The correction selects the already-corrected synthetic propagation profile only in the v4 multi-day preparation adapter. Native source, both native binaries, physical models and numerical acceptance limits are unchanged.</p><p>This verifies the bounded correctness suite; all 68 benchmark fits remain unrun. Multi-day preparation, shifted-cut diagnostics for this source/configuration, the actual benchmark, and completion of the original150 campaign remain separate requirements. No accepted-fit covariance, release readiness, speedup or accuracy claim follows.</p><p>The two environment-dependent native closure test parameters excluded from the focused adapter tests are not automatically covered by this 14-stage suite. The exact scope clarification is preserved among these controls. Existing publication and failure records remain immutable.</p><p>Raw arrays and numerical row/conditional payloads stay outside Git. The adjacent terminal report retains their exact external identities. These provenance files preserve capture, audit and presentation machinery without modifying or reevaluating scientific thresholds.</p><p><a href="independent-terminal-audit.json">Independent terminal audit</a> · <a href="manifest.json">Exact provenance inventory</a> · <a href="publication-links.json">Full/report manifest pins</a></p>'''
 p=output/'index.html';p.write_text(text);files.append({'path':'index.html',**{k:v for k,v in pin(p).items() if k!='path'}})
 links={'full_publication':pin(full),'git_distribution':pin(distribution),'independent_terminal_audit':pin(audit),'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_fix_scope_clarification':pin(C/'preparation-profile-fix01/independent-review02-scope-clarification.json')}
 p=output/'publication-links.json';p.write_text(json.dumps(links,indent=2)+'\n');files.append({'path':p.name,**{k:v for k,v in pin(p).items() if k!='path'}})
 result={'schema':'orbit-poc-validation04-terminal-provenance-v1','files':files,'bytes':sum(v['bytes'] for v in files),'benchmark_attempts_executed':0,'release_ready':False,'fit_covariance_authorized':False,'helper':pin(Path(__file__)),'scope':'Exact provenance and independently audited bounded validation only; no native execution or benchmark promotion.'}
 p=output/'manifest.json';p.write_text(json.dumps(result,indent=2)+'\n');return pin(p)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--audit',type=Path,required=True);p.add_argument('--audit-sha256',required=True);p.add_argument('--full-manifest',type=Path,required=True);p.add_argument('--distribution-manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(package(a.audit,a.audit_sha256,a.full_manifest,a.distribution_manifest,a.output)))
