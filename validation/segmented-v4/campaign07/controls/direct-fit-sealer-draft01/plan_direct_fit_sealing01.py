#!/usr/bin/env python3
"""Create a fresh sealing plan only from actual completed preparation."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json

def main():
 p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 raw=Path(a.request).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=a.sha256:raise ValueError('Sealing request changed')
 request=json.loads(raw);helper=request['helper'];source=Path(helper['path'])
 if not source.is_absolute() or hashlib.sha256(source.read_bytes()).hexdigest()!=helper['sha256']:raise ValueError('Sealer changed')
 spec=importlib.util.spec_from_file_location('pinned_direct_sealer',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 result=m.make_plan(request);output=m.path(a.output)
 if output.parent!=Path(request['control']['path']):raise ValueError('Sealing plan must be in dedicated control directory')
 m.write(output,result);print(json.dumps({'plan':m.pin(output),'actual_manifest':result['manifest'],'native_executions':0,'fit_attempts':0}))
if __name__=='__main__':main()
