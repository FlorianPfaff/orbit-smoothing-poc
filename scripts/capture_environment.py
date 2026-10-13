#!/usr/bin/env python3
"""Capture reproducibility metadata without reading credentials or environment secrets."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1])
args=parser.parse_args()
packages={}
for name in ['numpy','scipy','jax','jaxlib','numpyro','gtsam','matplotlib']:
    try: packages[name]=importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: packages[name]=None
try:
    gpu=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu','--format=csv'],capture_output=True,text=True,timeout=10).stdout.strip()
except (OSError,subprocess.TimeoutExpired): gpu=None
disk=shutil.disk_usage(args.project_root)
value={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'hostname':platform.node(),
       'python':platform.python_version(),'platform':platform.platform(),'logical_cpus':os.cpu_count(),
       'cpu_affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
       'package_versions':packages,'gpu_snapshot':gpu,'disk_free_bytes':disk.free,
       'project_root':str(args.project_root),'storage_cap_bytes':20*1024**3}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,indent=2))
