#!/usr/bin/env python3
"""Verify a starting checkpoint prefix and all68 outcomes after one public campaign."""
from pathlib import Path
import argparse,json,hashlib

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,why):
 if not ok:raise ValueError(why)

def inspect(config,source_sha,expected_completed,phase,protocol,validation,project):
 root=Path(config.output_dir);need(protocol.source_snapshot(project)['sha256']==source_sha,'Frozen source changed')
 manifest=protocol.verify_manifest(config,root,project);verified=validation.require_passed(config,manifest,root,project)
 need(len(manifest['attempts'])==68 and len(manifest['cases'])==28,'Wrong frozen benchmark inventory')
 ids=[a['attempt_id'] for a in manifest['attempts']];need(len(set(ids))==68,'Duplicate attempts');cases={c['case_id']:c for c in manifest['cases']};terminal=[];first_missing=None
 parent=root/'attempts'
 if parent.exists():need(parent.is_dir() and not parent.is_symlink() and all(p.is_dir() and not p.is_symlink() and p.name in ids for p in parent.iterdir()),'Unexpected attempt directory')
 for i,a in enumerate(manifest['attempts']):
  directory=parent/a['attempt_id'];job=protocol.attempt_job(config,manifest,cases[a['case_id']],a)
  if (directory/'result-record.json').exists():
   need(first_missing is None,'Terminal attempts are not a frozen-order prefix');v=protocol.checkpoint(directory,job)
   need(v.get('harness_execution',{}).get('owned_process_group_cleaned') is True,'Prior owned process cleanup unverified')
   runtime=manifest['runtimes']['dense' if a['profile']=='dense_corrected' else 'segmented'];need(v['harness_execution']['runtime']==runtime,'Attempt runtime attribution differs')
   terminal.append({'attempt_id':a['attempt_id'],'profile':a['profile'],'status':v['status'],'converged':v.get('converged',False),'covariance_valid':v.get('covariance_valid',False),'result':protocol.artifact(directory/'result.json'),'record':protocol.artifact(directory/'result-record.json')})
  else:
   if first_missing is None:first_missing=i
   need(not directory.exists() or not any(directory.iterdir()),'Nonterminal attempt evidence must be preserved; no automatic retry')
 need(type(expected_completed) is int and 0<=expected_completed<68,'Explicit starting terminal-prefix count required')
 need(phase in ('before','after'),'Unknown campaign-check phase');count=expected_completed if phase=='before' else 68
 need(len(terminal)==count,'Public run did not produce exactly the expected terminal prefix')
 return {'schema':'orbit-poc-segmented-fit-state-check-v2','status':'passed','phase':phase,'manifest_hash':manifest['manifest_hash'],'validation':verified,'starting_terminal_attempts':expected_completed,'terminal_attempts':len(terminal),'expected_attempts':68,'terminal':terminal,'scientific_success_inferred':False,'scope':'Checkpoint attribution, fixed order and cleanup only; failed scientific fits remain failed.'}

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--config-sha256',required=True);ap.add_argument('--source-sha256',required=True);ap.add_argument('--expected-completed',type=int,required=True);ap.add_argument('--phase',choices=('before','after'),required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args(argv)
 need(sha(a.config)==a.config_sha256,'Frozen config changed');need(not a.output.exists() and not a.output.is_symlink(),'Preserve prior check')
 from orbit_poc.segmented.config import load_config
 from orbit_poc.segmented import protocol,validation
 config=load_config(a.config);project=Path(config.segmented_runtime.source_root);v=inspect(config,a.source_sha256,a.expected_completed,a.phase,protocol,validation,project);v['config']={'path':str(a.config),'sha256':a.config_sha256};v['source_sha256']=a.source_sha256;protocol.write_json(a.output,v);return 0
if __name__=='__main__':raise SystemExit(main())
