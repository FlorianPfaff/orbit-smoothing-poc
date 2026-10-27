#!/usr/bin/env python3
"""Probe the candidate's actual QR-spool C stdio operations, not design storage."""
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/mnt/d/orbit-v41-recovery01/candidate04/source/groops/extension/scaledRowQr.h')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    output = ROOT / 'result.json'
    if output.exists():
        raise RuntimeError('Preserve the preceding probe; use a separate attempt')
    source_sha = digest(SOURCE)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fdopen.argtypes = [ctypes.c_int, ctypes.c_char_p]
    libc.fdopen.restype = ctypes.c_void_p
    for name in ('fwrite', 'fread'):
        fn = getattr(libc, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
        fn.restype = ctypes.c_size_t
    for name in ('fflush', 'fclose', 'feof', 'ferror'):
        fn = getattr(libc, name)
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_int
    libc.fseek.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_int]
    libc.fseek.restype = ctypes.c_int
    steps = []
    scratch = Path(tempfile.mkdtemp(prefix='owned-stdio-', dir=ROOT))
    stream = None
    descriptor = None
    error = None
    path = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix='orbit-poc-qr-', dir=scratch)
        path = Path(raw_path)
        stream = libc.fdopen(descriptor, b'w+b')
        if not stream:
            raise OSError(ctypes.get_errno(), 'fdopen failed')
        os.unlink(path)
        initial = os.fstat(descriptor)
        steps.append({'operation': 'mkstemp_fdopen_unlink', 'links': initial.st_nlink,
                      'device': initial.st_dev, 'inode': initial.st_ino, 'passed': initial.st_nlink == 0})
        if initial.st_nlink != 0:
            raise RuntimeError('File was not actually unlinked')
        payload = bytes(range(256)) * 32  # 1024 Double-sized elements per row block.
        block = ctypes.create_string_buffer(payload)
        count = len(payload) // 8
        repetitions = 1024
        for _ in range(repetitions):
            ctypes.set_errno(0)
            written = libc.fwrite(block, 8, count, stream)
            if written != count:
                raise OSError(ctypes.get_errno(), f'fwrite transferred {written}/{count} elements')
        steps.append({'operation': 'fwrite', 'element_bytes': 8, 'elements_per_block': count,
                      'blocks': repetitions, 'bytes': len(payload) * repetitions, 'passed': True})
        ctypes.set_errno(0)
        if libc.fflush(stream):
            raise OSError(ctypes.get_errno(), 'fflush failed')
        size = os.fstat(descriptor).st_size
        if size != len(payload) * repetitions:
            raise RuntimeError('Unexpected stored byte count')
        steps.append({'operation': 'fflush_fstat', 'bytes': size, 'passed': True})
        ctypes.set_errno(0)
        if libc.fseek(stream, 0, os.SEEK_SET):
            raise OSError(ctypes.get_errno(), 'fseek failed')
        steps.append({'operation': 'fseek_start', 'passed': True})
        received = ctypes.create_string_buffer(len(payload))
        observed_hash = hashlib.sha256()
        expected_hash = hashlib.sha256()
        for _ in range(repetitions):
            ctypes.set_errno(0)
            read = libc.fread(received, 8, count, stream)
            if read != count:
                raise OSError(ctypes.get_errno(), f'fread transferred {read}/{count} elements')
            actual = received.raw
            if actual != payload:
                raise RuntimeError('C stdio payload changed')
            observed_hash.update(actual)
            expected_hash.update(payload)
        if libc.ferror(stream) != 0:
            raise RuntimeError('C stdio error flag was set')
        steps.append({'operation': 'fread_exact_content', 'bytes': size,
                      'sha256': observed_hash.hexdigest(),
                      'expected_sha256': expected_hash.hexdigest(), 'passed': True})
    except BaseException as exc:
        error = repr(exc)
    finally:
        if stream:
            ctypes.set_errno(0)
            result = libc.fclose(stream)
            steps.append({'operation': 'fclose', 'result': result,
                          'errno': ctypes.get_errno(), 'passed': result == 0})
        elif descriptor is not None:
            os.close(descriptor)
        if path is not None and path.exists():
            os.unlink(path)  # Only the file exclusively created by this probe.
    empty = not list(scratch.iterdir())
    unchanged = digest(SOURCE) == source_sha
    record = {'schema': 'orbit-poc-v41-drvs-qr-spool-stdio-probe-v1',
              'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'source': {'path': str(SOURCE), 'sha256': source_sha},
              'probe': {'path': str(Path(__file__).resolve()), 'sha256': digest(__file__)},
              'scratch': str(scratch), 'steps': steps, 'error': error,
              'scratch_empty_after_close': empty, 'source_unchanged': unchanged,
              'passed': error is None and empty and unchanged and all(s['passed'] for s in steps),
              'scope': '8 MiB C stdio QR-spool filesystem semantics only; no GROOPS, compiler, numerical fit or large-file capacity test',
              'design_store_compatibility': False, 'numerical_authority': False}
    with output.open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({'passed': record['passed'], 'result': str(output), 'error': error}))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
