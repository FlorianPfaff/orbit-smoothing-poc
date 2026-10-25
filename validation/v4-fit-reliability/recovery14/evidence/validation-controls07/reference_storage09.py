"""Owned tmpfs for design storage; named outputs and stdio row spools stay on D."""
from pathlib import Path
import hashlib
import os
import shutil
import stat

LEAVES = ('tmp', 'scratch')


def identity(path):
    path = Path(path)
    info = path.stat()
    if path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Scratch must be an ordinary owned directory: ' + str(path))
    return {'path': str(path), 'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid}


def create(output, stages):
    output = Path(output)
    root = Path('/tmp') / ('orbit-reference09-' + hashlib.sha256(str(output).encode()).hexdigest()[:20])
    root.mkdir(mode=0o700)
    storage = {'schema': 'orbit-poc-reference-storage-v2', 'root': identity(root),
               'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'output': str(output), 'stages': {}}
    for stage in ('prepared', *stages):
        backing = root / stage
        backing.mkdir(mode=0o700)
        for leaf in LEAVES:
            (backing / leaf).mkdir(mode=0o700)
        storage['stages'][stage] = {'backing': identity(backing),
            'leaves': {leaf: identity(backing / leaf) for leaf in LEAVES}}
    return storage


def check_host(storage, stage):
    if storage['schema'] != 'orbit-poc-reference-storage-v2':
        raise ValueError('Unexpected scratch schema')
    if storage['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise ValueError('Owned scratch belongs to a different boot; preserve interrupted evidence')
    root = Path(storage['root']['path'])
    if root.parent != Path('/tmp') or not root.name.startswith('orbit-reference09-'):
        raise ValueError('Scratch root escapes owned tmpfs namespace')
    rows = [storage['root'], storage['stages'][stage]['backing'], *storage['stages'][stage]['leaves'].values()]
    for row in rows:
        if identity(row['path']) != row or not Path(row['path']).is_relative_to(root):
            raise ValueError('Owned scratch identity changed')
    return storage['stages'][stage]


def binds(storage, writable):
    writable = Path(writable)
    if writable.parent != Path(storage['output']):
        raise ValueError('Stage scratch path escapes output')
    row = check_host(storage, writable.name)
    result = ['--bind', str(writable), str(writable)]
    for leaf in LEAVES:
        result += ['--bind', row['leaves'][leaf]['path'], str(writable / leaf)]
    return result + ['--bind', row['leaves']['tmp']['path'], '/tmp']


def child_identity(storage, path):
    path = Path(path)
    relative = path.relative_to(Path(storage['output']))
    if len(relative.parts) != 2 or relative.parts[1] not in LEAVES:
        raise ValueError('Unexpected child scratch role')
    expected = storage['stages'][relative.parts[0]]['leaves'][relative.parts[1]]
    actual = identity(path)
    if any(actual[key] != expected[key] for key in ('device', 'inode', 'uid')):
        raise ValueError('Scratch mount does not refer to the frozen owned directory')
    return actual


def capacity(storage, stage, required_bytes):
    row = check_host(storage, stage)
    free = shutil.disk_usage(row['backing']['path']).free
    if type(required_bytes) is not int or required_bytes <= 0 or free < required_bytes:
        raise ValueError('Insufficient measured owned tmpfs capacity')
    return {'stage': stage, 'available_bytes': free, 'required_bytes': required_bytes,
            'scope': 'Design/TMPDIR admission only; row spools and named outputs remain on D. Native fallocate and original process-tree/disk limits remain enforced.'}
