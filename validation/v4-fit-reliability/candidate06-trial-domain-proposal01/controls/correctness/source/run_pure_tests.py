"""Bounded pure-control tests, preserving every attempt and its source bytes."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
PYTHON=Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python')
SOURCE=Path('/mnt/d/orbit-v41-density-trial-candidate06/source')


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def save(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',required=True);args=parser.parse_args()
    if not args.attempt.isdigit():raise ValueError('Numeric fresh attempt required')
    output=ROOT/('pure-tests'+args.attempt);output.mkdir();(output/'source').mkdir()
    files=sorted(ROOT.glob('*.py'))
    before=[pin(path) for path in files]
    for path in files:shutil.copyfile(path,output/'source'/path.name)
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    argv=[str(PYTHON),'-s','-B','-m','pytest','-q','-p','no:cacheprovider',
          '--basetemp='+str(output/'tmp'),'--junitxml='+str(output/'junit.xml'),
          *[str(path) for path in files if path.name.startswith('test_')]]
    environment={'HOME':os.environ['HOME'],'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
      'PYTHONPATH':str(SOURCE/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1',
      'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
      'LD_LIBRARY_PATH':'/home/emper/orbit-nuisance-warmstarts/toolchain-01/lib'}
    save(output/'plan.json',{'schema':'candidate06-controls-pure-test-plan-v1','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'boot_id':boot,'files':before,'python':pin(PYTHON),'argv':argv,'environment':environment,
      'native_launch':False,'timeout_seconds':180})
    start=time.monotonic();timed_out=False
    with (output/'pytest.log').open('x') as stream:
        try:code=subprocess.run(argv,cwd=ROOT,env=environment,stdout=stream,stderr=subprocess.STDOUT,timeout=180).returncode
        except subprocess.TimeoutExpired:code=None;timed_out=True
    same=before==[pin(path) for path in files]
    same_boot=boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    counts={}
    if (output/'junit.xml').exists():
        xml=ET.parse(output/'junit.xml').getroot()
        counts={key:sum(int(suite.get(key,'0')) for suite in xml.findall('testsuite')) for key in ['tests','failures','errors','skipped']}
    passed=code==0 and same and same_boot and counts.get('tests',0)>0 and all(counts.get(k)==0 for k in ['failures','errors','skipped'])
    result={'returncode':code,'elapsed_seconds':time.monotonic()-start,'timed_out':timed_out,'boot_unchanged':same_boot,
      'files_unchanged':same,'passed':passed,'counts':counts,'log':pin(output/'pytest.log'),'plan':pin(output/'plan.json'),
      'scope':'Pure control tests and tiny fabricated JUnit/data fixtures only; no native gates or fits'}
    save(output/'result.json',result)
    print(json.dumps(result))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
