from pathlib import Path
import argparse,collections,errno,fcntl,hashlib,importlib.util,json,os,re,stat,subprocess,time

def need(v,m):
    if not v:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def check(p):need(sha(p['path'])==p['sha256'],'Changed pin '+p['path'])
def save(p,x):
    with Path(p).open('x') as f:json.dump(x,f,indent=2,sort_keys=True);f.write('\n')
def dependency_inventory(build,make_text):
    objects=re.findall(r'-MT (bwrap-[a-z-]+\.o)\b',make_text)
    required={'bwrap-bubblewrap.o','bwrap-bind-mount.o','bwrap-network.o','bwrap-utils.o'}
    need(set(objects)==required and len(objects)==4,'Unexpected actual compiled object coverage')
    active={v[:-2]+'.Po':v for v in objects};dummy={'utils.Po','test-utils.Po','try-syscall.Po'}
    need({q.name for q in (build/'.deps').glob('*.Po')}==set(active)|dummy,'Unexpected dependency membership')
    sources={};inputs={};unused=[]
    for name in sorted(dummy):
        q=build/'.deps'/name;need(q.read_bytes()==b'# dummy\n','Unused dependency placeholder changed');unused.append(pin(q))
    for name,obj in sorted(active.items()):
        q=build/'.deps'/name;text=q.read_text().replace('\\\n',' ');first=text.split('\n',1)[0];need(':' in first,'Active dependency is missing');target,rest=first.split(':',1);need(target.strip()==obj,'Active dependency target differs');need((build/obj).is_file(),'Actual compiled object absent')
        deps=[]
        for word in rest.split():
            f=Path(word);f=f if f.is_absolute() else build/f;need(f.is_file(),'Compiled dependency missing');deps.append(str(f.resolve()));inputs[str(f.resolve())]=pin(f.resolve())
        need(any(f.endswith('/'+obj[len('bwrap-'):-2]+'.c') for f in deps),'Compiled source absent from dependency closure')
        sources[obj]={'object':pin(build/obj),'dependency_file':pin(q),'dependencies':deps}
    return {'compiled_objects':sources,'unused_automake_placeholders':unused,'files':[inputs[k] for k in sorted(inputs)],'config':pin(build/'config.h')}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--plan',required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args();need(sha(a.plan)==a.sha256,'Validation plan changed');request=json.loads(Path(a.plan).read_text());root=Path(request['root']);results=root/'results';results.mkdir();need(set(os.sched_getaffinity(0))=={32},'Validation CPU changed')
    for key in ('original_plan','original_failure','original_execution','original_capture','binary'):check(request[key])
    capture=json.loads(Path(request['original_capture']['path']).read_text())
    def originals():
        for row in capture['files']:check(row)
        for row in capture['links']:need(os.readlink(row['path'])==row['target'],'Original link changed')
    originals();p=json.loads(Path(request['original_plan']['path']).read_text());binary=Path(request['binary']['path']);oldroot=Path(p['root']);build=oldroot/'build';failure=json.loads(Path(request['original_failure']['path']).read_text());execution=json.loads(Path(request['original_execution']['path']).read_text());need(failure['error']=="IndexError('list index out of range')" and execution['status']=='failed' and execution['cleanup']['verified'] and not execution['cleanup']['live_owned_processes'],'Exact preserved failed metadata stage required');need(all(x['returncode']==0 for x in failure['commands']),'Original compile/configure command failed')
    compiled=dependency_inventory(build,(oldroot/'logs/make.stdout').read_text());save(results/'compiled-inputs.json',compiled)
    for row in p['host_files'].values():check(row)
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
    originals()
    for row in p['host_files'].values():check(row)
    save(root/'result.json',{'schema':'orbit-poc-bwrap-cap-validation-continuation-v1','status':'passed','binary':pin(binary),'plan':pin(a.plan),'preserved_build_failure':request['original_failure'],'preserved_build_execution':request['original_execution'],'prior_build_capture':request['original_capture'],'compiled_inputs':pin(results/'compiled-inputs.json'),'tests':[pin(results/(n+'.json')) for n in ('installed-cap-rejection','candidate-empty-root','candidate-upper-bound')],'source_or_binary_changed':False,'build_repeated':False,'fit_attempts':0})
if __name__=='__main__':
    try:main()
    except BaseException as ex:
        import sys
        # The owned controller preserves exception output and all partial files.
        raise
