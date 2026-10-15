#!/usr/bin/env python3
"""Pinned canonical read-only aliases and narrowly writable recovery outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

MUTABLE_KEYS=('native_source','build','binaries','run','temporary')


def namespace_command(execution):
    paths=execution['paths'];writable=[Path(paths[name]) for name in MUTABLE_KEYS]
    for path in writable:
        if path.is_symlink() or not path.is_dir():raise RuntimeError('Missing or non-real fresh writable directory: '+str(path))
    source=Path(paths['source'])
    if source.is_symlink() or not source.is_dir():raise RuntimeError('Missing or non-real frozen source snapshot')
    for path in writable:
        if path==source or source in path.parents or path in source.parents:raise RuntimeError('Writable path overlaps frozen source')
    command=['/usr/bin/bwrap','--die-with-parent','--unshare-user','--unshare-pid',
             '--ro-bind','/','/','--dev-bind','/dev','/dev','--proc','/proc','--ro-bind','/sys','/sys',
             '--tmpfs','/mnt','--tmpfs','/home',
             '--ro-bind',paths['root'],paths['root']]
    # Parent aliases first, then any more specific child overlays.
    bindings=sorted(execution['read_only_bindings'],key=lambda row:len(Path(row['target']).parts))
    for row in bindings:
        source_path=Path(row['source']);target=Path(row['target'])
        if not source_path.exists():raise RuntimeError('Missing read-only alias source: '+str(source_path))
        if any(target==w or target in w.parents or w in target.parents for w in writable):
            raise RuntimeError('Read-only alias overlaps writable output')
        command+=['--ro-bind',str(source_path),str(target)]
    for path in writable:command+=['--bind',str(path),str(path)]
    temporary=Path(paths['temporary'])
    command+=['--bind',str(temporary),'@TEMP_ROOT@','--ro-bind',str(source),str(source)]
    empty=Path(tempfile.mkdtemp(prefix='empty-bytecode-',dir=temporary))
    command+=['--ro-bind',str(empty),str(empty)]
    return command,empty


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution',type=Path,required=True);parser.add_argument('--execution-sha256',required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args(argv)
    if hashlib.sha256(args.execution.read_bytes()).hexdigest()!=args.execution_sha256:
        raise RuntimeError('Execution configuration changed before namespace launch')
    execution=json.loads(args.execution.read_text())
    if execution.get('schema')!='orbit-poc-correctness-execution-v1':raise RuntimeError('Wrong execution schema')
    requested=args.command[1:] if args.command[:1]==['--'] else args.command
    if not requested:raise RuntimeError('Supply a command inside the recovery namespace')
    command,empty=namespace_command(execution)
    temporary=execution['paths']['temporary']
    os.environ.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=str(empty),TMPDIR=temporary,TEMP=temporary,TMP=temporary)
    os.execv(command[0],command+['--']+requested)


if __name__=='__main__':main()
