"""Read-only Python/runtime closure for the isolated original reference gates."""
from __future__ import annotations
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig

SCHEMA = 'orbit-poc-reference-python-runtime-v2'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

ELF_TYPES = {0: 'ET_NONE', 1: 'ET_REL', 2: 'ET_EXEC', 3: 'ET_DYN', 4: 'ET_CORE'}


def elf_header_type(header):
    """Classify the file header; this never executes or loads its contents."""
    if not header.startswith(b'\x7fELF'):
        return None
    if len(header) < 20:
        raise ValueError('Truncated ELF header')
    if header[4] not in (1, 2) or header[5] not in (1, 2) or header[6] != 1:
        raise ValueError('Unsupported ELF class, byte order, or version')
    endian = 'little' if header[5] == 1 else 'big'
    value = int.from_bytes(header[16:18], endian)
    if value not in ELF_TYPES:
        raise ValueError('Unsupported ELF e_type: ' + str(value))
    return ELF_TYPES[value]


def file_content(path):
    h=hashlib.sha256();first=True;kind=None
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            if first: kind=elf_header_type(block[:64]);first=False
            h.update(block)
    return h.hexdigest(),kind


def entry(path):
    p=Path(path).absolute(); digest_value,kind=file_content(p)
    row={'path':str(p),'resolved':str(p.resolve(strict=True)),'sha256':digest_value,'bytes':p.stat().st_size,'elf':kind is not None,'elf_type':kind}
    if p.is_symlink(): row['link_target']=os.readlink(p)
    return row


def tree(root, excluded=()):
    root=Path(root).absolute(); rows=[]
    if root.is_symlink() or not root.is_dir(): raise ValueError('Runtime tree root is not an ordinary directory: '+str(root))
    resolved_root=root.resolve(strict=True)
    def visit(parent):
        # DirEntry caches the directory metadata supplied by the kernel. Resolve
        # the already checked ordinary ancestors once, not once per file.
        with os.scandir(parent) as stream: entries=sorted(stream,key=lambda x:x.name)
        for member in entries:
            p=Path(member.path);rel=str(p.relative_to(root))
            if rel in excluded: continue
            if member.is_symlink():
                if member.is_dir(): raise ValueError('Runtime directory symlink needs explicit handling: '+str(p))
                if not member.is_file(): raise ValueError('Unsupported runtime link: '+str(p))
                rows.append({'relative':rel,'kind':'file',**entry(p)})
            elif member.is_file():
                digest_value,kind=file_content(p)
                rows.append({'relative':rel,'kind':'file','path':str(p),'resolved':str(resolved_root/rel),
                             'sha256':digest_value,'bytes':member.stat().st_size,'elf':kind is not None,'elf_type':kind})
            elif member.is_dir():
                rows.append({'relative':rel,'kind':'directory'});visit(p)
            else: raise ValueError('Unsupported runtime member: '+str(p))
    visit(root)
    return {'root':str(root),'excluded':list(excluded),'entries':sorted(rows,key=lambda x:x['relative'])}


def elf_type(path):
    with Path(path).open('rb') as f: return elf_header_type(f.read(64))


def elf(path):
    return elf_type(path) is not None

def dependency_paths(text):
    result=set()
    for line in text.splitlines():
        if 'not found' in line: raise ValueError('ELF dependency is unresolved: '+line)
        if '=> ' in line:
            value=line.split('=> ',1)[1].split(' (',1)[0].strip()
        else: value=line.strip().split(' (',1)[0]
        if value.startswith('/'): result.add(os.path.normpath(value))
        elif value and not value.startswith(('linux-vdso','statically linked','not a dynamic executable')):
            raise ValueError('Unrecognized ldd dependency: '+line)
    return sorted(result)

def is_dependency_only_elf(path):
    return any(part.endswith('.libs') for part in Path(path).parts)


def linked(path,env):
    if elf_type(path) not in ('ET_EXEC', 'ET_DYN') or is_dependency_only_elf(path):
        raise ValueError('Loader trace requires an executable/shared entrypoint, not a relocatable object or dependency-only library: '+str(path))
    completed=subprocess.run(['/usr/bin/ldd',str(path)],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    if completed.returncode: raise ValueError('ldd failed on trusted runtime ELF: '+str(path)+'\n'+completed.stdout)
    try: return dependency_paths(completed.stdout)
    except ValueError as exc: raise ValueError('Loader trace failed for '+str(path)+': '+str(exc)) from exc

def probe(source):
    sys.path[:0]=[str(Path(source)/'src'),str(Path(source)/'scripts')]
    # Import code only, with subprocess launch prohibited for the probe.
    launch=subprocess.Popen
    def forbidden(*a,**k): raise RuntimeError('Runtime import probe attempted a subprocess')
    subprocess.Popen=forbidden
    names=('pytest','numpy','scipy.linalg','scipy.sparse','scipy.spatial.transform','psutil',
           'validate_numerics_synthetic_refinement','validate_numerics_flight_refinement',
           'validate_numerics_objective','validate_numerics_nuisance',
           'orbit_poc.segmented.supervisor','orbit_poc.segmented.validation')
    try:
        for name in names: importlib.import_module(name)
    finally: subprocess.Popen=launch
    return names

def collect(source,env):
    names=probe(source)
    std=Path(sysconfig.get_paths()['stdlib']); site=Path(sysconfig.get_paths()['purelib'])
    roots={str(std):('site-packages',),str(Path(source)/'src'):(),str(Path(source)/'scripts'):()}
    imported=[]
    for name,module in sorted(sys.modules.items()):
        raw=getattr(module,'__file__',None)
        if not raw: continue
        p=Path(raw).absolute()
        if not p.is_file(): continue
        if p.is_relative_to(site):
            first=p.relative_to(site).parts[0]; top=site/first
            if top.is_dir(): roots[str(top)]=()
            imported.append({'module':name,'file':str(p)})
        elif not (p.is_relative_to(std) or p.is_relative_to(Path(source)) or p.parent==Path(__file__).absolute().parent):
            raise ValueError('Unaccounted imported module: '+name+' '+str(p))
    for p in site.iterdir():
        if p.is_dir() and (p.name.startswith(('numpy','scipy','psutil','setuptools')) or p.name=='_distutils_hack'):
            roots[str(p)]=()
    trees=[tree(root,excluded) for root,excluded in sorted(roots.items())]
    single={str(Path(__file__).absolute()),str(Path(__file__).with_name('reference_gates09.py').absolute()),str(Path(sys.executable).absolute()),str(Path(sys.prefix)/'pyvenv.cfg'),'/usr/bin/ldd','/etc/ld.so.cache','/etc/ld.so.conf'}
    single.update(str(p) for p in site.glob('*.pth'))
    single.update(str(p) for p in Path('/etc/ld.so.conf.d').glob('*') if p.is_file())
    for row in imported:
        p=Path(row['file'])
        if not any(p.is_relative_to(Path(x)) for x in roots): single.add(str(p))
    zip_path=std.parent/('python'+str(sys.version_info.major)+str(sys.version_info.minor)+'.zip')
    optional=[zip_path]
    for root in (std,site,Path(source)/'src',Path(source)/'scripts',Path(__file__).parent):
        optional.extend(root/(name+ext) for name in ('sitecustomize','usercustomize') for ext in ('.py','.pyc','.so'))
    absent=[]
    for p in optional:
        if p.exists() or p.is_symlink(): single.add(str(p))
        else: absent.append(str(p))
    files={str(Path(p).absolute()):entry(p) for p in sorted(single)}
    candidates={row['path']:row['elf_type'] for t in trees for row in t['entries'] if row['kind']=='file' and row['elf']}
    candidates.update({p:row['elf_type'] for p,row in files.items() if row['elf']})
    # All ELF bytes remain in the hashed trees/files. Relocatable .o files and
    # core/untyped records have no executable loader entrypoint. Wheel .libs
    # inherit the extension's RPATH and are traced transitively from that root.
    non_entrypoints=[{'path':p,'elf_type':kind,'reason':'ELF type has no executable loader entrypoint'}
                    for p,kind in sorted(candidates.items()) if kind not in ('ET_EXEC','ET_DYN')]
    dependency_only=sorted(p for p,kind in candidates.items()
                           if kind in ('ET_EXEC','ET_DYN') and is_dependency_only_elf(p))
    elf_records=[]
    for p,kind in sorted(candidates.items()):
        if kind not in ('ET_EXEC','ET_DYN') or p in dependency_only: continue
        deps=linked(p,env)
        elf_records.append({'path':p,'elf_type':kind,'dependencies':deps})
        for dep in deps:
            if dep not in files: files[dep]=entry(dep)
    return {'schema':SCHEMA,'python':entry(sys.executable),'prefix':sys.prefix,'base_prefix':sys.base_prefix,
            'version':sys.version,'probe_imports':list(names),'imported_site_modules':imported,'trees':trees,
            'files':list(files.values()),'absent':sorted(absent),'elf_dependencies':elf_records,
            'dependency_only_elf_objects':dependency_only,'non_entrypoint_elf_objects':non_entrypoints,
            'elf_context_policy':'Hash every member, including ET_REL objects; trace only ET_EXEC/ET_DYN interpreter and extension roots under the exact environment. Wheel .libs remain fully hashed and resolve transitively using each extension RPATH.',
            'site_startup_members':sorted(str(p) for p in site.glob('*.pth')),'site_directory':str(site),
            'ld_library_path':env.get('LD_LIBRARY_PATH',''),'native_fit_launched':False}

def verify(value,env,*,check_links=True):
    if value['schema']!=SCHEMA or env.get('LD_LIBRARY_PATH','')!=value['ld_library_path']:
        raise ValueError('Python runtime schema/environment differs')
    if sorted(str(p) for p in Path(value['site_directory']).glob('*.pth'))!=value['site_startup_members']:
        raise ValueError('Python startup membership differs')
    for p in value['absent']:
        if Path(p).exists() or Path(p).is_symlink(): raise ValueError('Absent Python startup path appeared: '+p)
    for t in value['trees']:
        if tree(t['root'],t['excluded'])!=t: raise ValueError('Python runtime tree changed: '+t['root'])
    for row in value['files']:
        if entry(row['path'])!=row: raise ValueError('Python runtime file changed: '+row['path'])
    if check_links:
        for row in value['elf_dependencies']:
            if linked(row['path'],env)!=row['dependencies']: raise ValueError('Python ELF resolution changed: '+row['path'])
    return {'trees':len(value['trees']),'files':sum(len(t['entries']) for t in value['trees'])+len(value['files']),
            'elf_objects':len(value['elf_dependencies']),'hashes_and_membership_verified':True,'elf_resolution_verified':check_links}
