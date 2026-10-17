#!/usr/bin/env python3
"""Owned full serial native build; no object reuse in the candidate build."""
from pathlib import Path
import argparse, collections, hashlib, importlib.util, json, os, re, shlex, shutil, subprocess, sys

INPUT_KEYS={'baseline_result','source_delta','recipe_inventory','link_inventory','dependency_inventory','utility','installation_helper','installation_request','toolchain','fixture_inventory'}

def require(ok,message):
    if not ok: raise ValueError(message)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p): return {'path':str(p),'sha256':sha(p)}
def check(p):
    require(isinstance(p,dict) and set(p)=={'path','sha256'},'Exact pin required')
    path=Path(p['path']); require(path.is_absolute() and '..' not in path.parts and path.is_file() and sha(path)==p['sha256'],'Changed input pin')
    return path
def write(p,value):
    with Path(p).open('x') as f: json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def normalize(command,roots):
    words=shlex.split(command) if isinstance(command,str) else list(command)
    require(all(Path(root).is_absolute() and '..' not in Path(root).parts for root in roots),'Bad normalization roots')
    for root,label in sorted(roots.items(),key=lambda x:-len(x[0])):
        require(label in ('<SOURCE>','<BUILD>'),'Unknown normalization label')
        words=[word.replace(root,label) for word in words]
    return words

def classify(commands):
    result={'cpp':{},'fortran':{},'preprocess':{},'link':[],'dyndep':[]}
    for index,text in enumerate(commands):
        argv=shlex.split(text)
        if '-E' in argv and '-o' in argv:
            target=argv[argv.index('-o')+1];kind='preprocess'
        elif '-c' in argv and '-o' in argv:
            target=argv[argv.index('-o')+1];kind='fortran' if '-fpreprocessed' in argv else 'cpp'
        elif '-o' in argv and argv[argv.index('-o')+1]=='groops':result['link'].append({'index':index,'argv':argv,'text':text});continue
        elif 'cmake_ninja_dyndep' in argv:result['dyndep'].append({'index':index,'argv':argv,'text':text});continue
        else:raise ValueError('Unsupported generated native command')
        require(target not in result[kind] and not Path(target).is_absolute() and '..' not in Path(target).parts,'Duplicate/unsafe command target')
        result[kind][target]={'index':index,'argv':argv,'text':text}
    require(len(result['cpp'])==591 and len(result['fortran'])==20 and len(result['preprocess'])==20 and len(result['link'])==1 and len(result['dyndep'])==1,'Native command inventory is not 591+20+20+1+1')
    objects=[x for x in result['link'][0]['argv'] if x.endswith('.o')]
    require(len(objects)==611 and len(set(objects))==611 and set(objects)==set(result['cpp'])|set(result['fortran']),'Complete linked-object set differs')
    return result

def compare_commands(old,new,old_roots,new_roots):
    a=classify(old);b=classify(new)
    aa=collections.Counter(json.dumps(normalize(x,old_roots))for x in old)
    bb=collections.Counter(json.dumps(normalize(x,new_roots))for x in new)
    require(aa==bb,'Normalized compiler/preprocessor/link commands changed')
    return a,b

def parse_log(text):
    lines=text.splitlines();require(lines and lines[0]=='# ninja log v5','Unknown Ninja log')
    rows={}
    for index,line in enumerate(lines[1:],1):
        f=line.split('\t');require(len(f)==5,'Malformed Ninja log')
        start,end,stamp=int(f[0]),int(f[1]),int(f[2]);require(0<=start<=end and stamp>0,'Invalid Ninja timing')
        require(f[3] not in rows,'Repeated Ninja target in fresh build')
        rows[f[3]]={'line':index,'raw':line,'start_ms':start,'end_ms':end,'mtime':stamp,'command_hash':f[4]}
    return rows

def compile_evidence(commands,logtext,verbose,build,baseline_build):
    groups=classify(commands);logs=parse_log(logtext)
    actual=[]
    for line in verbose.splitlines():
        m=re.match(r'^\[\d+/\d+\] (.*)$',line)
        if m: actual.append(m.group(1))
    counts=collections.Counter(actual);require(counts==collections.Counter(commands),'Actual verbose invocations do not match complete final command inventory')
    out={}
    for language in ('cpp','fortran','preprocess'):
        rows={}
        for target,record in groups[language].items():
            require(target in logs,'Successful command lacks Ninja target record')
            path=build/target;require(path.is_file() and not path.is_symlink(),'Missing fresh native object/output')
            st=path.stat();old=baseline_build/target
            if old.exists():require((st.st_dev,st.st_ino)!=(old.stat().st_dev,old.stat().st_ino),'Candidate object aliases baseline')
            rows[target]={'path':str(path),'sha256':sha(path),'bytes':st.st_size,'device':st.st_dev,'inode':st.st_ino,'command_index':record['index'],'verbose_index':actual.index(record['text']),'ninja_log':logs[target]}
        out[language]=rows
    require('groops' in logs,'Candidate link missing successful log')
    out['linked_objects']=sorted(set(groups['cpp'])|set(groups['fortran']));out['link']={'command_index':groups['link'][0]['index'],'verbose_index':actual.index(groups['link'][0]['text']),'ninja_log':logs['groops']}
    return out

def external_dependencies(blocks,source):
    names=set()
    for block in blocks:
        lines=block.splitlines()
        require(lines and ': #deps ' in lines[0] and lines[0].endswith('(VALID)'),'Invalid dependency record')
        if lines[0].startswith('groops:'):continue
        deps=[x.strip() for x in lines[1:] if x.strip()]
        require(len(deps)==int(lines[0].split(': #deps ',1)[1].split(',',1)[0]),'Incomplete dependency record')
        for name in deps:
            require(Path(name).is_absolute(),'Relative compiler dependency')
            if not Path(name).is_relative_to(source):names.add(name)
    return names

def check_cmake_tools(cache,tool):
    values={line.split('=',1)[0].split(':',1)[0]:line.split('=',1)[1] for line in cache.splitlines() if '=' in line and not line.startswith(('//','#'))}
    require('CMAKE_C_COMPILER' not in values,'Unexpected C compiler for frozen CXX/Fortran-only project')
    for key,name in (('CMAKE_MAKE_PROGRAM','ninja'),('CMAKE_CXX_COMPILER','cxx'),('CMAKE_Fortran_COMPILER','fc')):
        require(key in values and Path(values[key]).resolve()==Path(tool[name]['path']).resolve() and sha(values[key])==tool[name]['sha256'],'Configured toolchain differs: '+key)
    require(values.get('CMAKE_BUILD_TYPE')=='Release' and values.get('CMAKE_DISABLE_FIND_PACKAGE_MPI')=='ON','Configured build/MPI mode differs')

def decode_roundtrip(decoder_path,stdout):
    m=load_module('exact_native_export_decoder',decoder_path)
    from fractions import Fraction
    rows=[json.loads(x) for x in stdout.splitlines() if x.strip()];require(len(rows)==2,'Expected exactly two serializer records')
    exact,anchored=[m.decode_stencil(x,m.V2,5) for x in rows]
    require(exact.mode=='exact' and exact.indices==(3,) and exact.coefficients()==((3,Fraction(1)),),'Exact serializer roundtrip differs')
    require(anchored.mode=='anchored_twofold' and anchored.indices==(4,1) and anchored.anchor==1,'Typed anchor roundtrip differs')
    require(anchored.high==(Fraction(1,2),Fraction(1,2)) and anchored.low==(Fraction(1,2**70),Fraction(0)),'High/low dyadic serializer roundtrip differs')
    values=[Fraction(i) for i in range(5)]
    require(anchored.evaluate(values)==Fraction(5,2)+Fraction(3,2**70),'Typed branch arithmetic differs')
    return {'passed':True,'records':rows,'decoder':pin(decoder_path),'scope':'Supplemental serializer/decoder only; not native flight batch validation'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args()
    require(sha(a.plan)==a.sha256,'Plan changed');p=json.loads(a.plan.read_text());require(p['phase'] in ('prepare','build'),'Unknown full-build phase');require(set(p['inputs'])==INPUT_KEYS|({'preflight_result','preflight_audit'} if p['phase']=='build' else set()),'Unknown complete-build input inventory')
    for v in p['inputs'].values():check(v)
    u=load_module('preserved_build_utilities',check(p['inputs']['utility']))
    e=json.loads(check(p['execution']).read_text());paths={k:Path(v)for k,v in e['paths'].items()}
    base=json.loads(check(p['inputs']['baseline_result']).read_text());base_root=Path(p['inputs']['baseline_result']['path']).parents[2];base_source=base_root/'native_source/source';base_build=base_root/'build'
    require(base['status']=='built_precision_candidate' and base['native']==p['native'] and sha(base_build/'groops')==p['native']['sha256'],'Wrong current baseline')
    check(p['native']);before=u.tree(base_source);require(before==base['source_after'],'Baseline source changed')
    delta=json.loads(check(p['inputs']['source_delta']).read_text());u.validate_delta(delta,p['inputs']['baseline_result'],before)
    expected=dict(before);expected.update({r['relative']:r['new_file']['sha256']for r in delta['changes']})
    tool=json.loads(check(p['inputs']['toolchain']).read_text());require(set(tool)=={'schema','python','cmake','ninja','cxx','cc','fc','git'} and tool['schema']=='orbit-poc-native-complete-toolchain-v1','Wrong toolchain')
    for k,v in tool.items():
        if k!='schema':check(v)
    require(tool['cxx']['path']==base['link_command'][0],'C++ link compiler changed')
    root=Path(p['output']);u.disjoint([base_source,base_build,paths['native_source'],paths['build'],paths['binaries'],root]);root.mkdir(exist_ok=False)
    for key in ('native_source','build','binaries'):require(paths[key].is_dir() and not any(paths[key].iterdir()),'Candidate directory is not genuinely empty')
    stages=[];result={'schema':'orbit-poc-native-complete-build-v1','status':'running','plan':pin(a.plan),'baseline_result':p['inputs']['baseline_result'],'source_delta':p['inputs']['source_delta'],'source_before':before,'stages':stages,'fit_attempts':0,'release_evidence':False}
    env=dict(os.environ,HOME='/home/florianpfaff',PATH=str(paths['prefix']/'bin')+':/usr/bin:/bin',LD_LIBRARY_PATH=str(paths['prefix']/'lib'),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    def run(label,argv,cwd=None,environment=None):
        out=root/(label+'.stdout');err=root/(label+'.stderr');record={'label':label,'argv':[str(x)for x in argv],'cwd':str(cwd or root)};stages.append(record)
        with out.open('x')as so,err.open('x')as se:q=subprocess.run(record['argv'],cwd=cwd or root,env=environment or env,stdout=so,stderr=se)
        record.update(returncode=q.returncode,stdout=pin(out),stderr=pin(err));require(q.returncode==0,'Native complete build stage failed: '+label);return out.read_text()
    try:
        inventory=json.loads(check(p['inputs']['recipe_inventory']).read_text());require(inventory['baseline_result']==p['inputs']['baseline_result'],'Original recipe baseline differs');old_commands=inventory['all_commands'];classify(old_commands)
        original_manifest=json.loads(check(base['original_build_manifest']).read_text());old_build=Path(base['original_build_manifest']['path']).parent;old_source=Path(original_manifest['build_command'][original_manifest['build_command'].index('-S')+1])
        links=json.loads(check(p['inputs']['link_inventory']).read_text());require(links['baseline_result']==p['inputs']['baseline_result'],'Link baseline differs');link_pins=u.validate_link_inputs(links['inputs'],base,base_build)
        deps=json.loads(check(p['inputs']['dependency_inventory']).read_text());require(deps['schema']=='orbit-poc-complete-native-external-dependencies-v1' and deps['recipe_inventory']==p['inputs']['recipe_inventory'],'Wrong external dependency inventory')
        external={r['path']:r for r in deps['files']};require(len(external)==len(deps['files']),'Duplicate external dependency');require(set(external)==external_dependencies(inventory['all_dependency_blocks'],old_source),'External dependency inventory omitted or added paths')
        for name,identity in external.items():require(u.file_identity(name)==identity,'External compile dependency changed')
        request=json.loads(check(p['inputs']['installation_request']).read_text());require(request['baseline_result']==p['inputs']['baseline_result'] and request['source_delta']==p['inputs']['source_delta'],'Installation baseline/delta differs')
        repository=json.loads(check(request['repository_inventory']).read_text());repo=Path(repository['root']);buildscript=repo/'scripts/build_groops.py'
        originals={name:sha(base_build/name)for name in sorted(base['original_object_sha256'])}
        if p['phase']=='prepare':
            relink=root/'baseline-relink';relink.mkdir();objects=sorted(base['original_object_sha256']);originals={}
            for name in objects:
                old=base_build/name;new=relink/name;originals[name]=sha(old);new.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,new);require(sha(new)==originals[name] and new.stat().st_ino!=old.stat().st_ino,'Baseline object copy failed')
            run('baseline-link',base['link_command'],relink);require(sha(relink/'groops')==p['native']['sha256'],'Baseline copied-object relink did not reproduce exact executable')
            write(root/'baseline-relink.json',{'schema':'orbit-poc-native-baseline-relink-v1','passed':True,'baseline_result':p['inputs']['baseline_result'],'native':p['native'],'artifact':pin(relink/'groops'),'objects':originals,'link_command':base['link_command'],'link_inputs':p['inputs']['link_inventory'],'stage':stages[-1]});result['baseline_relink']=pin(root/'baseline-relink.json')
            request=json.loads(check(p['inputs']['installation_request']).read_text());require(request['baseline_result']==p['inputs']['baseline_result'] and request['source_delta']==p['inputs']['source_delta'],'Installation baseline/delta differs')
            require(Path(request['output']).is_relative_to(paths['native_source']),'Installation output escapes fresh source slot')
            run('installer-equivalence',[tool['python']['path'],p['inputs']['installation_helper']['path'],'--request',p['inputs']['installation_request']['path'],'--sha256',p['inputs']['installation_request']['sha256']])
            install_path=Path(request['output'])/'result.json';installed=json.loads(install_path.read_text());require(installed['status']=='passed' and installed['passed'] is True and installed['source_after']==expected,'Pristine install does not equal declared source delta');result['installation_equivalence']=pin(install_path)
            repository=json.loads(check(request['repository_inventory']).read_text());repo=Path(repository['root']);buildscript=repo/'scripts/build_groops.py'
            fixture=json.loads(check(p['inputs']['fixture_inventory']).read_text());require(set(fixture)=={'schema','interpolation','serializer','decoder'} and fixture['schema']=='orbit-poc-native-wide-supplemental-fixtures-v1','Wrong fixture inventory')
            for name in ('interpolation','serializer','decoder'):check(fixture[name])
            inc=repo/'groops/extension';fixture_results={}
            for name in ('interpolation','serializer'):
                binary=root/('fixture-'+name);run('fixture-'+name+'-compile',[tool['cxx']['path'],'-O3','-DNDEBUG','-std=gnu++17','-I'+str(inc/'wide_tangent/proposed/misc/orbitPoc'),'-I'+str(inc),fixture[name]['path'],'-o',str(binary)])
                fixture_results[name]={'binary':pin(binary),'stdout':run('fixture-'+name,[str(binary)])}
            fixture_results['roundtrip']=decode_roundtrip(fixture['decoder']['path'],fixture_results['serializer']['stdout']);write(root/'supplemental-fixtures.json',fixture_results);result['supplemental_fixtures']=pin(root/'supplemental-fixtures.json')
            result.update(status='prepared_complete_build',inputs=p['inputs'],source_after=expected,original_recipe_inventory=p['inputs']['recipe_inventory'],compiled_object_count=0,preprocessing_count=0,reused_object_count=0)
            return
        preflight=json.loads(check(p['inputs']['preflight_result']).read_text());audit=json.loads(check(p['inputs']['preflight_audit']).read_text())
        require(preflight['status']=='prepared_complete_build' and preflight['inputs']=={k:v for k,v in p['inputs'].items() if k not in ('preflight_result','preflight_audit')},'Preflight does not bind current immutable inputs')
        require(audit['passed'] is True and audit['preflight_result']==p['inputs']['preflight_result'],'Independent preflight audit differs')
        for key in ('baseline_relink','installation_equivalence','supplemental_fixtures'):
            check(preflight[key]);require(audit[key]==preflight[key],'Independent preflight artifact mismatch');result[key]=preflight[key]
        installed=json.loads(check(preflight['installation_equivalence']).read_text());require(installed['status']=='passed' and installed['passed'] is True and installed['source_after']==expected,'Audited installation differs')
        require(u.tree(Path(installed['installed_checkout'])/'source')==expected,'Audited installed tree changed')
        installer=load_module('strict_installer_helper',check(p['inputs']['installation_helper']));checkout=paths['native_source']/'candidate';checkout.mkdir();members,_=installer.inspect_archive(request['archive']['path']);installer.extract_archive(request['archive']['path'],checkout,members)
        candidate_source=checkout/'source';candidate_build=paths['build'];require(not any(candidate_build.iterdir()),'Candidate build must still be empty before configure')
        buildmodule=load_module('committed_native_build_script',buildscript)
        script_env=dict(env,GIT_DIR=request['git_dir'],GIT_WORK_TREE=str(checkout),GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_TERMINAL_PROMPT='0')
        script_argv=[str(buildscript),'--source-dir',str(checkout),'--build-dir',str(candidate_build),'--prefix',str(paths['prefix']),'--jobs','1','--numerics','--segmented','--wide-tangent-candidate','--cmake-executable',tool['cmake']['path']]
        calls=[]
        def script_run(argv,**kwargs):
            argv=[str(x)for x in argv];calls.append(argv);index=len(calls)-1
            expected_patchers=[str(repo/'groops/extension'/x)for x in ('apply_extension.py','native_segmented.py','native_tangent_wide.py')]
            if index<3:
                want=[sys.executable,expected_patchers[index],str(checkout)]+(['--numerics']if index==0 else[]);require(argv==want,'Unexpected public installer invocation');label='public-installer-'+str(index)
            elif index==3:
                require(u.tree(candidate_source)==expected,'Full public installation differs before first compiler/configure');require(not any(candidate_build.iterdir()),'Candidate build was not empty');label='configure'
                want=list(original_manifest['build_command']);want[want.index('-S')+1]=str(candidate_source);want[want.index('-B')+1]=str(candidate_build);require(argv==want and argv[0]==tool['cmake']['path'],'CMake configuration differs from pinned baseline')
            elif index==4:
                require(argv==[tool['cmake']['path'],'--build',str(candidate_build),'--parallel','1'],'Build is not complete serial public invocation');require(u.tree(candidate_source)==expected,'Source changed before compile');check_cmake_tools((candidate_build/'CMakeCache.txt').read_text(),tool);label='complete-build';argv=argv+['--verbose']
            elif index==5:require(argv==[str(candidate_build/'groops'),'--help'],'Unexpected native command');label='native-help'
            else:raise ValueError('Unexpected public build-script command')
            require(set(kwargs).issubset({'env'}),'Unexpected public run keyword');run(label,argv,root,kwargs.get('env',script_env))
        buildmodule.run=script_run;oldenv=dict(os.environ);oldargv=sys.argv
        try:os.environ.clear();os.environ.update(script_env);sys.argv=script_argv;buildmodule.main()
        finally:os.environ.clear();os.environ.update(oldenv);sys.argv=oldargv
        require(len(calls)==6,'Public build script did not finish exact sequence')
        current_commands=run('candidate-command-inventory',[tool['ninja']['path'],'-C',str(candidate_build),'-t','commands','groops']).splitlines()
        old_roots={str(old_source):'<SOURCE>',str(old_build):'<BUILD>'};new_roots={str(candidate_source):'<SOURCE>',str(candidate_build):'<BUILD>'};compare_commands(old_commands,current_commands,old_roots,new_roots)
        write(root/'candidate-command-inventory.json',{'schema':'orbit-poc-complete-native-command-inventory-v1','commands':current_commands,'raw':pin(root/'candidate-command-inventory.stdout')})
        normalized={'schema':'orbit-poc-native-complete-normalized-configuration-v1','rule':'shlex tokens; replace only declared absolute source/build roots; preserve every remaining token and command multiplicity','original_roots':old_roots,'candidate_roots':new_roots,'original_recipe_inventory':p['inputs']['recipe_inventory'],'candidate_commands':pin(root/'candidate-command-inventory.json'),'public_script_argv':script_argv,'public_run_calls':calls,'verbose_only_build_argument':'--verbose','serial_jobs':1,'compiler_pins':p['inputs']['toolchain'],'normalized_commands':[normalize(x,new_roots)for x in current_commands]};write(root/'normalized-configuration.json',normalized);result['normalized_configuration']=pin(root/'normalized-configuration.json')
        evidence=compile_evidence(current_commands,(candidate_build/'.ninja_log').read_text(),(root/'complete-build.stdout').read_text(),candidate_build,base_build);evidence.update(schema='orbit-poc-native-complete-compile-evidence-v1',candidate_commands=pin(root/'candidate-command-inventory.json'),ninja_log=pin(candidate_build/'.ninja_log'),verbose_stdout=pin(root/'complete-build.stdout'),build_stage=next(x for x in stages if x['label']=='complete-build'),reused_object_count=0);write(root/'complete-compile-evidence.json',evidence);result['complete_compile_evidence']=pin(root/'complete-compile-evidence.json')
        candidate_deps=run('candidate-dependency-inventory',[tool['ninja']['path'],'-C',str(candidate_build),'-t','deps']).strip().split('\n\n');require(external_dependencies(candidate_deps,candidate_source).issubset(external),'New unpinned external compile dependency');result['candidate_dependencies']=pin(root/'candidate-dependency-inventory.stdout')
        after=u.tree(candidate_source);require(after==expected and u.tree(base_source)==before,'Native source mutation')
        require(all(sha(base_build/name)==digest for name,digest in originals.items()),'Original objects changed')
        for name,identity in {**link_pins,**external}.items():require(u.file_identity(name)==identity,'Preserved dependency changed')
        for v in p['inputs'].values():check(v)
        u.check_payloads(delta['changes'])
        native=paths['binaries']/('groops-wide-complete-'+sha(candidate_build/'groops')[:16]);shutil.copy2(candidate_build/'groops',native);native.chmod(0o555)
        result.update(status='built_complete_candidate',source_after=after,candidate_source_sha256=u.source_digest(after),native=pin(native),original_recipe_inventory=p['inputs']['recipe_inventory'],build_manifest=pin(candidate_build/'build-manifest.json'),cmake_cache=pin(candidate_build/'CMakeCache.txt'),compiled_object_count=611,preprocessing_count=20,reused_object_count=0)
    except BaseException as error:result.update(status='failed',error=repr(error));raise
    finally:write(root/'result.json',result)
if __name__=='__main__':main()
