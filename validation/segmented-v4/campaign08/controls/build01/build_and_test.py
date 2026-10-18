from pathlib import Path
import argparse, datetime, errno, fcntl, hashlib, json, os, re, shutil, stat, subprocess, tarfile, time

def need(v, why):
    if not v: raise ValueError(why)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p): return {'path': str(p), 'sha256': sha(p)}
def save(p, x):
    with Path(p).open('x') as f: json.dump(x, f, indent=2, sort_keys=True); f.write('\n')
def check(q): need(sha(q['path']) == q['sha256'], 'Changed pin '+q['path'])
def inventory(root, rows):
    expected = set()
    for r in rows:
        p = root/r['path']; expected.add(r['path'])
        need(not p.is_symlink(), 'Unexpected source link')
        if r['kind']=='directory':need(p.is_dir(), 'Source directory changed')
        else:
            need(r['kind']=='file' and p.is_file(), 'Source kind changed')
            need(sha(p) == r['sha256'] and p.stat().st_size == r['bytes'], 'Source bytes changed')
        need(stat.S_IMODE(p.stat().st_mode) == r['mode'], 'Source mode changed')
    need({p.relative_to(root).as_posix() for p in root.rglob('*')} == expected, 'Source membership changed')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--plan',required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args()
    need(sha(a.plan)==a.sha256,'Build plan changed');p=json.loads(Path(a.plan).read_text());root=Path(p['root']);need(root.is_dir(),'Owned root absent')
    for row in [p['source_archive'],p['worker'],*p['host_files'].values()]:check(row)
    need(set(os.sched_getaffinity(0))=={32},'Control build must use CPU32')
    logs=root/'logs';logs.mkdir();results=root/'results';results.mkdir();commands=[]
    def run(name,argv,cwd,env=None,expected=0):
        start=time.monotonic();r=subprocess.run(argv,cwd=cwd,env=env,text=True,capture_output=True)
        (logs/(name+'.stdout')).write_text(r.stdout);(logs/(name+'.stderr')).write_text(r.stderr)
        v={'name':name,'argv':argv,'cwd':str(cwd),'environment':env,'returncode':r.returncode,'elapsed_seconds':time.monotonic()-start,'stdout':pin(logs/(name+'.stdout')),'stderr':pin(logs/(name+'.stderr'))};commands.append(v);save(results/(name+'.json'),v)
        need(r.returncode==expected,'Command failed: '+name);return r
    try:
        inputs=root/'inputs';inputs.mkdir()
        with tarfile.open(p['source_archive']['path']) as t:
            for m in t.getmembers():
                need(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts and (m.isfile() or m.isdir()),'Unsafe source member')
            t.extractall(inputs)
        check({'path':str(inputs/'provenance/source-manifest.json'),'sha256':p['source_manifest_sha256']})
        m=json.loads((inputs/'provenance/source-manifest.json').read_text());inventory(inputs/'source-distro',m['distro_source_inventory']);inventory(inputs/'source-candidate',m['candidate_source_inventory'])
        old=(inputs/'source-distro/bubblewrap.c').read_bytes();new=(inputs/'source-candidate/bubblewrap.c').read_bytes()
        need(old.count(b'static const uint32_t MAX_ARGS = 9000;')==1 and new==old.replace(b'static const uint32_t MAX_ARGS = 9000;',b'static const uint32_t MAX_ARGS = 16384;'),'Candidate change exceeds cap')
        need(len(m['differences'])==1,'Unexpected source delta')
        private=root/'private-dev';private.mkdir();baseenv={'PATH':'/usr/bin:/bin','HOME':str(root),'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
        run('extract-private-dev',['/usr/bin/dpkg-deb','-x',str(inputs/'downloads/libcap-dev_2.44-1ubuntu0.22.04.3_amd64.deb'),str(private)],root,baseenv)
        link=private/'usr/lib/x86_64-linux-gnu/libcap.so';need(link.is_symlink() and os.readlink(link)=='/lib/x86_64-linux-gnu/libcap.so.2.44','Private libcap link changed');check(p['host_files']['/lib/x86_64-linux-gnu/libcap.so.2.44'])
        build=root/'build';build.mkdir();env={**baseenv,**p['build_environment']}
        run('configure',[str(inputs/'source-candidate/configure'),'--disable-maintainer-mode','--disable-man','--with-priv-mode=none','--enable-selinux'],build,env)
        run('make',['/usr/bin/make','-j1','V=1','bwrap'],build,env)
        binaries=root/'binaries';binaries.mkdir();binary=Path(p['binary']);need(binary.parent==binaries,'Unexpected binary path');shutil.copyfile(build/'bwrap',binary);binary.chmod(0o755)
        need(stat.S_IMODE(binary.stat().st_mode)==0o755,'Privileged binary mode')
        try: cap=os.getxattr(binary,'security.capability')
        except OSError as ex:
            if ex.errno not in (errno.ENODATA,errno.ENOTSUP):raise
            cap=b''
        need(not cap,'Unexpected file capabilities')
        config=(build/'config.h').read_text();need('#define HAVE_SELINUX 1' in config and '#define HAVE_SELINUX_2_3 1' in config,'SELinux support missing')
        dyn=run('readelf-dynamic',['/usr/bin/readelf','-d',str(binary)],root,baseenv).stdout
        ph=run('readelf-headers',['/usr/bin/readelf','-h','-l',str(binary)],root,baseenv).stdout
        need('BIND_NOW' in dyn and 'GNU_RELRO' in ph and 'DYN (Position-Independent Executable file)' in ph,'Ubuntu hardening missing')
        needed=set(re.findall(r'Shared library: \[(.*?)\]',dyn));need(needed=={'libselinux.so.1','libcap.so.2','libc.so.6'},'Linked library set changed')
        run('linked-libraries',['/usr/bin/ldd',str(binary)],root,baseenv);run('version',[str(binary),'--version'],root,baseenv)
        headers={}
        for dep in (build/'.deps').glob('*.Po'):
            text=dep.read_text().replace('\\\n',' ');first=text.split('\n',1)[0].split(':',1)[1]
            for name in first.split():
                q=Path(name);q=q if q.is_absolute() else build/q
                if q.is_file():headers[str(q.resolve())]=pin(q.resolve())
        save(results/'compiled-inputs.json',{'files':[headers[k] for k in sorted(headers)],'config':pin(build/'config.h')})
        fixture=root/'fixture';fixture.mkdir();allowed=fixture/'allowed.txt';allowed.write_text('orbit-bwrap-cap-fixture\n');secret=fixture/'secret.txt';secret.write_text('not-visible\n');write=fixture/'writable';write.mkdir()
        def payload(count):
            args=['--unshare-user','--unshare-pid','--unshare-net','--new-session','--die-with-parent','--clearenv','--tmpfs','/','--proc','/proc','--dev','/dev','--chdir','/']
            for src,dst in [('/bin/dash','/bin/sh'),('/lib/x86_64-linux-gnu/libc.so.6','/lib/x86_64-linux-gnu/libc.so.6'),('/lib64/ld-linux-x86-64.so.2','/lib64/ld-linux-x86-64.so.2')]:args+=['--ro-bind',src,dst]
            for i in range(3317):args+=['--ro-bind',str(allowed),'/inputs/f%04d'%i]
            args+=['--bind',str(write),'/output']
            script='read v < /inputs/f0000; test "$v" = orbit-bwrap-cap-fixture || exit 11; read v < /inputs/f3316; test "$v" = orbit-bwrap-cap-fixture || exit 12; test ! -e '+str(secret)+' || exit 13; if (echo changed > /inputs/f0000) 2>/dev/null; then exit 14; fi; if (echo changed > /blocked-root) 2>/dev/null; then exit 15; fi; echo accepted > /output/accepted; echo namespace-fixture-passed'
            tail=['--remount-ro','/','--','/bin/sh','-c',script];n=count-len(args)-len(tail);need(n>=0,'Fixture count too small')
            if n%2:args+=['--new-session'];n-=1
            for i in range(n//2):args+=['--dir','/padding/d%04d'%i]
            args+=tail;need(len(args)==count,'Fixture argument count differs');return args
        def test(name,exe,args,success,reason=None):
            fd=os.memfd_create('sealed-bwrap-cap-fixture',os.MFD_ALLOW_SEALING);data=b'\0'.join(v.encode() for v in args)+b'\0';os.write(fd,data);os.lseek(fd,0,0);fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE)
            t=time.monotonic()
            try:r=subprocess.run([str(exe),'--args',str(fd)],cwd=fixture,env={},text=True,capture_output=True,pass_fds=(fd,))
            finally:os.close(fd)
            v={'name':name,'executable':pin(exe),'argument_count':len(args),'sealed_argument_sha256':hashlib.sha256(data).hexdigest(),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'elapsed_seconds':time.monotonic()-t};save(results/(name+'.json'),v)
            if success:need(r.returncode==0 and 'namespace-fixture-passed' in r.stdout,'Namespace fixture failed')
            else:need(r.returncode!=0 and reason in r.stderr,'Expected cap rejection absent')
            return v
        args=payload(p['fixture_argument_count']);test('installed-cap-rejection',Path('/usr/bin/bwrap'),args,False,'Exceeded maximum number of arguments 9000')
        test('candidate-empty-root',binary,args,True);need((write/'accepted').read_text()=='accepted\n' and allowed.read_text()=='orbit-bwrap-cap-fixture\n' and secret.read_text()=='not-visible\n','Fixture backing changed')
        test('candidate-upper-bound',binary,payload(16385),False,'Exceeded maximum number of arguments 16384')
        inventory(inputs/'source-distro',m['distro_source_inventory']);inventory(inputs/'source-candidate',m['candidate_source_inventory'])
        for row in p['host_files'].values():check(row)
        save(root/'result.json',{'schema':'orbit-poc-bwrap-cap-build-and-regression-v1','status':'passed','binary':pin(binary),'binary_mode':0o755,'capability_xattr':None,'plan':pin(a.plan),'source_manifest':pin(inputs/'provenance/source-manifest.json'),'source_delta':'MAX_ARGS 9000 -> 16384 only, after exact Ubuntu patches','commands':commands,'tests':[pin(results/(n+'.json')) for n in ('installed-cap-rejection','candidate-empty-root','candidate-upper-bound')],'scientific_changes':False,'fit_attempts':0})
    except BaseException as ex:
        save(root/'failure.json',{'schema':'orbit-poc-bwrap-cap-build-failure-v1','error':repr(ex),'commands':commands,'fit_attempts':0});raise

if __name__=='__main__':main()
