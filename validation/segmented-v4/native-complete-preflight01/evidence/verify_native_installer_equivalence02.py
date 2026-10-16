#!/usr/bin/env python3
"""Source-only, pinned upstream archive -> exact installed-source equivalence.

Runs only three pinned Python installer entrypoints. No configure, compiler,
checkout, repository mutation or native executable is launched. An admitted
outer namespace must expose all inputs and genuine Git metadata read-only.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
import time

COMMIT='7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'
SCHEMA='orbit-poc-native-installer-equivalence-request-v1'


def require(value,message):
    if not value:raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def canonical_json(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def safe_path(value,kind=None,absent=False):
    require(isinstance(value,str)and value,'Empty path')
    p=Path(value)
    require(p.is_absolute()and'..'not in p.parts and str(p)==value,'Noncanonical path')
    for q in(p,*p.parents):require(not q.is_symlink(),'Symlink path: '+str(q))
    if absent:require(not p.exists(),'Output already exists')
    elif kind=='file':require(p.is_file()and stat.S_ISREG(p.stat().st_mode),'Nonregular file')
    elif kind=='directory':require(p.is_dir(),'Missing directory')
    return p


def relative(value):
    require(isinstance(value,str)and value and '\\'not in value,'Invalid relative member')
    p=PurePosixPath(value)
    require(not p.is_absolute()and'..'not in p.parts and str(p)==value and str(p)!='.','Unsafe relative member')
    return p


def pin(path):
    p=Path(path);data=p.read_bytes();return dict(path=str(p),sha256=sha(data),bytes=len(data))


def checked(record):
    require(isinstance(record,dict)and set(record)<= {'path','sha256','bytes'}and{'path','sha256'}<=set(record),'Invalid input pin')
    p=safe_path(record['path'],'file');data=p.read_bytes()
    require(sha(data)==record['sha256']and('bytes'not in record or len(data)==record['bytes']),'Input hash/size changed: '+str(p))
    return data


def decode(data):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    return json.loads(data,object_pairs_hook=pairs)


def file_map(root):
    require(root.is_dir()and not root.is_symlink(),'Invalid inventory root')
    result={}
    for folder,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:
            p=Path(folder)/name;require(not p.is_symlink(),'Linked directory in source tree')
        for name in files:
            p=Path(folder)/name;safe_path(str(p),'file');result[str(p.relative_to(root))]=sha(p.read_bytes())
    return dict(sorted(result.items()))


def repository_map(root):
    groops=file_map(root/'groops');result={'groops/'+name:digest for name,digest in groops.items()}
    script=root/'scripts/build_groops.py';safe_path(str(script),'file');result['scripts/build_groops.py']=sha(script.read_bytes())
    return dict(sorted(result.items()))


def expected_source(baseline,delta):
    before=baseline.get('source_after')
    require(isinstance(before,dict)and len(before)==1131,'Expected exact1131-file baseline')
    for name,digest in before.items():relative(name);require(isinstance(digest,str)and len(digest)==64,'Invalid baseline digest')
    require(delta.get('schema')=='orbit-poc-native-source-delta-v1','Unknown source delta')
    require(delta.get('base_source_sha256')==sha(canonical_json(before)),'Baseline map digest differs')
    changes=delta.get('changes');require(isinstance(changes,list)and len(changes)==7,'Expected seven source changes')
    after=dict(before);seen=set();actions=[]
    for item in changes:
        require(set(item)=={'relative','action','old_sha256','new_file'},'Unknown source delta fields')
        name=str(relative(item['relative']));require(name not in seen,'Repeated source delta');seen.add(name)
        data=checked(item['new_file']);action=item['action'];actions.append(action)
        if action=='replace':require(name in before and item['old_sha256']==before[name],'Wrong replacement baseline')
        elif action=='add':require(name not in before and item['old_sha256']is None,'Wrong addition baseline')
        else:raise ValueError('Unsupported source delta action')
        after[name]=sha(data)
    require(actions.count('replace')==4 and actions.count('add')==3,'Expected four replacements and three additions')
    return dict(sorted(after.items()))


def inspect_archive(archive):
    """Validate every resolved tar member before creating extracted paths."""
    records=[];seen=set();comments=[]
    with tarfile.open(archive,'r:')as tar:
        for headers in(tar.pax_headers,):
            if 'comment'in headers:comments.append(headers['comment'])
        for item in tar:
            name=item.name.rstrip('/') if item.isdir() else item.name
            p=relative(name)
            require(p.parts[0]=='source'and(p.parts!=('source',)or item.isdir()),'Archive member outside source/')
            require(name not in seen,'Duplicate archive member');seen.add(name)
            require(item.isfile()or item.isdir(),'Link/device/special archive member')
            require(not getattr(item,'sparse',None),'Sparse archive member')
            require(not item.linkname,'Archive link target')
            if 'comment'in item.pax_headers:comments.append(item.pax_headers['comment'])
            if item.isfile():
                data=tar.extractfile(item).read();require(len(data)==item.size,'Truncated archive member')
                records.append(dict(path=name,kind='file',bytes=item.size,sha256=sha(data)))
            else:records.append(dict(path=name,kind='directory'))
    require(records and any(x['kind']=='file'for x in records),'Empty upstream source archive')
    require(all(x==COMMIT for x in comments),'Git archive pax commit mismatch')
    return records,{'pax_commit_present':bool(comments),'pax_commit':COMMIT if comments else None,'commit_attribution':'Verified exact archive receipt and genuine read-only Git HEAD; pax comment verified only if present.'}


def extract_archive(archive,checkout,records):
    expected={x['path']:x for x in records}
    with tarfile.open(archive,'r:')as tar:
        for item in tar:
            name=item.name.rstrip('/')if item.isdir()else item.name;record=expected[name];out=checkout/name
            if item.isdir():out.mkdir(parents=True,exist_ok=True);continue
            out.parent.mkdir(parents=True,exist_ok=True);data=tar.extractfile(item).read()
            require(sha(data)==record['sha256']and len(data)==record['bytes'],'Archive changed during extraction')
            with out.open('xb')as stream:stream.write(data)
            out.chmod(item.mode&0o777&~0o022)
    result=file_map(checkout/'source');want={r['path'][len('source/'):]:r['sha256']for r in records if r['kind']=='file'}
    require(result==dict(sorted(want.items())),'Pristine archive extraction membership differs')
    return result


def write_json(path,value):
    with path.open('x')as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def execute(request_path,request_hash):
    request_pin={'path':str(request_path),'sha256':request_hash};request=decode(checked(request_pin))
    fields={'schema','archive','archive_provenance','python','git','git_head','git_dir','repository_inventory','baseline_result','source_delta','output'}
    require(set(request)==fields and request['schema']==SCHEMA,'Unknown installer-equivalence request')
    output=safe_path(request['output'],absent=True);require(output.parent.is_dir(),'Output parent must exist')
    inputs=[safe_path(request[key]['path'],'file')for key in fields-{'schema','output','git_dir'}]
    require(all(not p.is_relative_to(output)and not output.is_relative_to(p)for p in inputs),'Output overlaps an input')
    early_repo=safe_path(decode(checked(request['repository_inventory']))['root'],'directory')
    early_upstream=safe_path(decode(checked(request['archive_provenance']))['repository'],'directory')
    for tree in(early_repo,early_upstream,safe_path(request['git_dir'],'directory')):
        require(not output.is_relative_to(tree)and not tree.is_relative_to(output),'Output overlaps preserved source/Git input')
    output.mkdir();started=time.monotonic();result={'schema':'orbit-poc-native-installer-equivalence-result-v1','status':'running','passed':False,'request':request_pin,'commands':[],'compiled':False,'native_launches':0,'git_mutations':0,'inputs':{key:request[key]for key in fields-{'schema','output'}},'helper':pin(Path(__file__).resolve())}
    original_repo=None;git_head=None;repo=None;environment=None;delta=None
    def command(argv,label,env):
        stdout=output/(label+'.stdout');stderr=output/(label+'.stderr');start=time.monotonic()
        with stdout.open('xb')as out,stderr.open('xb')as err:
            process=subprocess.run([str(x)for x in argv],env=env,stdout=out,stderr=err,check=False)
        record={'argv':[str(x)for x in argv],'returncode':process.returncode,'elapsed_seconds':time.monotonic()-start,'stdout':pin(stdout),'stderr':pin(stderr)}
        result['commands'].append(record);require(process.returncode==0,'Source-only command failed: '+label)
        return stdout.read_text().strip()
    try:
        contents={key:checked(request[key])for key in fields-{'schema','output','git_dir'}}
        require(Path(sys.executable).resolve()==Path(request['python']['path']),'Helper is not running under pinned Python')
        provenance=decode(contents['archive_provenance']);inventory=decode(contents['repository_inventory']);baseline=decode(contents['baseline_result']);delta=decode(contents['source_delta'])
        require(provenance.get('schema')=='orbit-poc-pristine-native-source-archive-v1'and provenance.get('commit')==COMMIT and provenance.get('uses_git_object_content_not_worktree')is True,'Invalid pristine archive attribution')
        require(provenance.get('archive')==request['archive']and provenance.get('git_sha256')==request['git']['sha256'],'Archive/Git provenance differs')
        require(delta.get('baseline_result')==request['baseline_result'],'Source delta baseline receipt differs')
        after_expected=expected_source(baseline,delta)
        result['expected_source_sha256']=sha(canonical_json(after_expected))
        require(inventory.get('schema')=='orbit-poc-native-installer-repository-inventory-v1'and set(inventory)=={'schema','root','files'},'Unknown repository inventory')
        repo=safe_path(inventory['root'],'directory');gitdir=safe_path(request['git_dir'],'directory')
        require(not output.is_relative_to(repo)and not repo.is_relative_to(output)and not output.is_relative_to(gitdir)and not gitdir.is_relative_to(output),'Output overlaps repository or Git metadata')
        original_repo=repository_map(repo);require(original_repo==inventory['files'],'Installer repository membership/content changed')
        require(Path(request['git']['path']).name=='git','Pinned Git command must be named git')
        require(Path(request['git_head']['path'])==gitdir/'HEAD','Wrong Git HEAD pin')
        git_head=contents['git_head'];checkout=output/'checkout'
        environment={k:v for k,v in os.environ.items()if not k.startswith('GIT_')and k not in('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','PYTHONINSPECT')}
        environment.update(PATH=str(Path(request['git']['path']).parent),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_TERMINAL_PROMPT='0')
        upstream=safe_path(provenance['repository'],'directory')
        actual_dir=command([request['git']['path'],'-C',upstream,'rev-parse','--absolute-git-dir'],'git-directory-before',environment)
        require(actual_dir==str(gitdir),'Actual upstream Git metadata directory differs')
        environment.update(GIT_DIR=str(gitdir),GIT_WORK_TREE=str(checkout))
        head=command([request['git']['path'],'-C',upstream,'rev-parse','HEAD'],'git-head-before',environment);require(head==COMMIT,'Actual Git HEAD differs')
        members,pax=inspect_archive(request['archive']['path']);result['archive_provenance']=request['archive_provenance'];result['archive_metadata']=pax
        write_json(output/'archive-members.json',{'schema':'orbit-poc-upstream-archive-members-v1','archive':request['archive'],'members':members})
        result['archive_member_inventory']=pin(output/'archive-members.json')
        checkout.mkdir();result['pristine_source']=extract_archive(request['archive']['path'],checkout,members)
        for index,(script,extra)in enumerate((('apply_extension.py',['--numerics']),('native_segmented.py',[]),('native_tangent_wide.py',[])),1):
            path=repo/'groops/extension'/script
            require('groops/extension/'+script in original_repo,'Installer entrypoint absent from exact inventory')
            command([request['python']['path'],path,checkout,*extra],f'installer-{index:02d}-{script}',environment)
        source_after=file_map(checkout/'source');result['source_after']=source_after
        missing=sorted(set(after_expected)-set(source_after));extra=sorted(set(source_after)-set(after_expected));different=sorted(k for k in set(after_expected)&set(source_after)if after_expected[k]!=source_after[k])
        result['comparison']={'expected_files':len(after_expected),'actual_files':len(source_after),'missing':missing,'extra':extra,'different':different}
        require(not(missing or extra or different),'Complete installed source differs from pinned baseline plus delta')
        result.update(status='passed',passed=True,baseline_result=request['baseline_result'],source_delta=request['source_delta'],repository_inventory=request['repository_inventory'],source_after_sha256=sha(canonical_json(source_after)),installed_checkout=str(checkout),archive=request['archive'])
    except Exception as error:
        result.update(status='failed',passed=False,error={'type':type(error).__name__,'message':str(error)})
    finally:
        partial=output/'checkout/source'
        if partial.is_dir() and 'source_after'not in result:
            try:result['source_after']=file_map(partial)
            except Exception as error:result['partial_inventory_error']=str(error)
        try:
            checked(request_pin)
            if delta is not None:
                for item in delta.get('changes',[]):checked(item['new_file'])
            if original_repo is not None:require(repository_map(repo)==original_repo,'Installer repository mutated');result['repository_preserved']=True
            if git_head is not None:
                require(checked(request['git_head'])==git_head,'Original Git HEAD changed')
                head=command([request['git']['path'],'-C',Path(request['git_dir']).parent,'rev-parse','HEAD'],'git-head-after',environment)
                require(head==COMMIT,'Final actual Git HEAD differs');result['git_head_preserved']=True
            for key in fields-{'schema','output','git_dir'}:checked(request[key])
            result['pinned_inputs_preserved']=True
        except Exception as error:result.update(status='failed',passed=False,preservation_error={'type':type(error).__name__,'message':str(error)})
        result['elapsed_seconds']=time.monotonic()-started
        write_json(output/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',type=Path,required=True);parser.add_argument('--sha256',required=True);args=parser.parse_args()
    try:result=execute(args.request,args.sha256)
    except Exception as error:
        print(json.dumps({'status':'failed_before_owned_output','passed':False,'error':str(error)}));return 1
    print(json.dumps({'status':result['status'],'passed':result['passed']}))
    return 0 if result['passed']else 1
if __name__=='__main__':sys.exit(main())
