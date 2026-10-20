#!/usr/bin/env python3
"""Seal the bootstrap, install the reviewed opt-in patch, and pin its build."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

B = Path('/home/emper/orbit-nuisance-performance')
S, R, BUILD = B/'native-source-01', B/'source', B/'build-01'
PY = Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python')
PREFIX = Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/v3/native-env')
CMAKE = PY.parent.parent/'lib/python3.11/site-packages/cmake/data/bin/cmake'


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True);f.write('\n')


def run(argv, log):
    with log.open('x') as f:
        subprocess.run(list(map(str, argv)), cwd=R, stdout=f, stderr=subprocess.STDOUT, check=True)


def main():
    assert json.loads((B/'control/bootstrap-complete01.json').read_text())['returncode'] == 0
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if (p/'comm').read_text().strip() in ('ninja', 'cc1plus', 'f951'):
                raise RuntimeError('An active compiler blocks source mutation')
        except FileNotFoundError: pass
    os.sched_setaffinity(0, {0, 1, 2, 3})
    bins = B/'binaries';bins.mkdir(exist_ok=True)
    spec = importlib.util.spec_from_file_location('builder', R/'scripts/build_groops.py')
    builder = importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    before = builder.source_receipt(S)
    oldsha = sha(BUILD/'groops');oldbin = bins/('groops-bootstrap-'+oldsha[:16])
    if oldbin.exists(): raise RuntimeError('Never overwrite a bootstrap binary')
    shutil.copy2(BUILD/'groops', oldbin);oldbin.chmod(0o555)
    save(B/'control/bootstrap-source01.json', before)
    save(B/'control/bootstrap-binary01.json', {'path': str(oldbin), 'sha256': oldsha,
                                              'source': before['sha256'], 'scope': 'development bootstrap; not a frozen campaign executable'})
    header = S/'source/misc/orbitPoc/nuisancePerformance.h'
    base_manifest = json.loads((S/'orbit-poc-extension.json').read_text())
    if sha(header) != base_manifest['files']['nuisancePerformance.h']:
        raise RuntimeError('Unattributed bootstrap header')
    # This unused header was copied before candidate development completed.
    # Its old bytes are attributed above; no compiler is active during refresh.
    save(B/'control/header-refresh01.json', {'before': sha(header),
         'after': sha(R/'groops/extension/nuisancePerformance.h'),
         'reason': 'Refresh the exact base-copied, previously unreferenced optional header before first installation'})
    header.write_bytes((R/'groops/extension/nuisancePerformance.h').read_bytes())
    run([PY, R/'groops/extension/native_nuisance_performance.py', '--source', S], B/'control/install-candidate01.log')
    after = builder.source_receipt(S)
    changed = sorted(k for k in set(before['files'])|set(after['files'])
                     if before['files'].get(k) != after['files'].get(k))
    expected = json.loads((S/'orbit-poc-nuisance-performance-extension.json').read_text())['installed_files']
    if changed != sorted(expected): raise RuntimeError('Unexpected native source mutation: '+repr(changed))
    save(B/'control/candidate-source01.json', after)
    run([PY, R/'scripts/build_groops.py', '--source-dir', S, '--build-dir', BUILD,
         '--prefix', PREFIX, '--jobs', '4', '--numerics', '--segmented', '--wide-tangent-candidate',
         '--nuisance-performance', '--cmake-executable', CMAKE], B/'control/candidate-build01.log')
    if builder.source_receipt(S) != after: raise RuntimeError('Source changed during compilation')
    bm = json.loads((BUILD/'build-manifest.json').read_text())
    candidate = bins/('groops-nuisance-'+bm['executable_sha256'][:16])
    if candidate.exists(): raise RuntimeError('Never overwrite a candidate binary')
    shutil.copy2(BUILD/'groops', candidate);candidate.chmod(0o555)
    shutil.copy2(BUILD/'build-manifest.json', str(candidate)+'.build-manifest.json')
    raw = subprocess.check_output(['ldd', str(candidate)], text=True)
    libraries = sorted(set(re.findall(r'(?:=>\s+)?(/[^\s]+)\s+\(', raw)))
    if 'not found' in raw: raise RuntimeError('Unresolved runtime dependency')
    receipt = {'schema': 'orbit-poc-nuisance-build-v1', 'native': {'path': str(candidate), 'sha256': sha(candidate)},
               'build_manifest': {'path': str(BUILD/'build-manifest.json'), 'sha256': sha(BUILD/'build-manifest.json')},
               'patched_source_sha256': after['sha256'], 'changed_files': changed,
               'ldd': raw, 'libraries': [{'path': p, 'resolved': str(Path(p).resolve()), 'sha256': sha(p)} for p in libraries],
               'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(B/'control/candidate-build-complete01.json', receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('ldd', 'libraries')}, indent=2), flush=True)


if __name__ == '__main__': main()
