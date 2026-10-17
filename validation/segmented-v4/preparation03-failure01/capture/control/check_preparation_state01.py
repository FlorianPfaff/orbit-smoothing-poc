#!/usr/bin/env python3
"""Recheck frozen validation and, after preparation, the actual public manifest."""
from pathlib import Path
import argparse,hashlib,json

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,why):
 if not ok:raise ValueError(why)
def pin(path):return {'path':str(path),'sha256':sha(path)}
def inspect_prepared(protocol,config,root,source):
 status=protocol.read_json(root/'preparation-status.json')
 need(status.get('status')=='prepared' and status.get('expected_attempts')==68,'Public preparation is blocked, failed or incomplete')
 manifest=protocol.verify_manifest(config,root,source)
 need(status.get('manifest_hash')==manifest['manifest_hash'],'Preparation status does not identify actual manifest')
 catalog=protocol.read_json(protocol.verify_artifact(manifest['prepared_input_catalog'],source))
 need(catalog.get('schema')=='orbit-poc-segmented-input-catalog-v1' and len(catalog.get('entries',[]))==28,'Prepared catalog is incomplete')
 need(len(manifest.get('cases',[]))==28 and len(manifest.get('attempts',[]))==68,'Actual manifest does not contain28cases/68attempts')
 need(len({x['case_id'] for x in catalog['entries']})==28 and {x['case_id'] for x in catalog['entries']}=={x['case_id'] for x in manifest['cases']},'Prepared catalog case identities differ')
 attempts=root/'attempts';need(not attempts.exists() or attempts.is_dir() and not any(attempts.iterdir()),'Data-only preparation unexpectedly contains benchmark fits')
 return manifest,{'status':pin(root/'preparation-status.json'),'manifest':pin(root/'manifest.json'),'catalog':manifest['prepared_input_catalog'],'cases':28,'attempts':68,'benchmark_fit_count':0}

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--config-sha256',required=True);ap.add_argument('--source-sha256',required=True);ap.add_argument('--phase',choices=('before','after'),required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args(argv)
 need(sha(a.config)==a.config_sha256,'Frozen config changed');need(not a.output.exists() and not a.output.is_symlink(),'Previous preparation check must be preserved')
 from orbit_poc.segmented.config import load_config
 from orbit_poc.segmented import protocol as p,validation as v
 config=load_config(a.config);source=Path(config.segmented_runtime.source_root);root=Path(config.output_dir)
 need(config.segmented_runtime.source_sha256==a.source_sha256==config.dense_runtime.source_sha256,'Preparation source differs from executed validation')
 context=v.execution_context(config,root,source)
 prepared=None
 if a.phase=='after':manifest,prepared=inspect_prepared(p,config,root,source)
 else:manifest=context
 checked=v.require_passed(config,manifest,root,source)
 need(checked['status']=='passed','Prescribed14gates no longer pass their original checks')
 result={'schema':'orbit-poc-segmented-preparation-state-check-v1','status':'passed','phase':a.phase,'config':pin(a.config),'source_sha256':a.source_sha256,'validation_context_hash':context['validation_context_hash'],'validation':checked,'prepared':prepared,'scope':'Data preparation only; no benchmark fit or acceptance promotion.'}
 p.write_json(a.output,result);return 0
if __name__=='__main__':raise SystemExit(main())
