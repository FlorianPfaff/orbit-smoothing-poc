#!/usr/bin/env python3
"""Full frozen runtime check inside the exact post-suite namespace."""
from pathlib import Path
import argparse,hashlib,json

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--config-sha256',required=True);p.add_argument('--source-sha256',required=True);p.add_argument('--solver-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args(argv)
 if hashlib.sha256(a.config.read_bytes()).hexdigest()!=a.config_sha256:raise ValueError('Config changed')
 if a.output.exists() or a.output.is_symlink():raise ValueError('Preserve previous runtime check')
 from orbit_poc.segmented.config import load_config
 from orbit_poc.segmented.protocol import verify_runtime,canonical_hash,write_json
 config=load_config(a.config);r=config.segmented_runtime
 if r.source_sha256!=a.source_sha256 or r.segmented_solver.sha256!=a.solver_sha256:raise ValueError('Runtime identity differs')
 value=verify_runtime(r,Path(r.source_root))
 write_json(a.output,{'schema':'orbit-poc-shifted-runtime-check-v1','status':'passed','full_runtime_verified':True,'source_root':r.source_root,'source_sha256':r.source_sha256,'native':value['native'],'solver':value['segmented_solver'],'python':value['python'],'config':{'path':str(a.config),'sha256':a.config_sha256},'verified_runtime_sha256':canonical_hash(value),'scope':'Full frozen verify_runtime: source, native/build, solver, Python, library membership, complete runtime trees and loader-resolved dependency closure. No native solve or physical evaluation.'})
 return 0
if __name__=='__main__':raise SystemExit(main())
