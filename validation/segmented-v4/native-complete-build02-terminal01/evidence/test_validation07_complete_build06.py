"""Pure 611-object receipt reconstruction fixtures; no compiler or native work."""
from pathlib import Path
from types import SimpleNamespace
import collections,copy,hashlib,importlib.util,json,shlex
import pytest
C=Path(__file__).parent
s=importlib.util.spec_from_file_location('complete02',C/'validation07_provenance04.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def fixture(monkeypatch):
 raw={};inodes={};docs={};next_inode=[1]
 def blob(path,data):
  if isinstance(data,str):data=data.encode()
  raw[path]=data
  if path not in inodes:inodes[path]=next_inode[0];next_inode[0]+=1
  return {'path':path,'sha256':hashlib.sha256(data).hexdigest()}
 def doc(name,value):
  p='/fixture/records/'+name+'.json';docs[p]=value;return blob(p,json.dumps(value))
 def read_artifact(pin,checked):checked(pin);return json.loads(raw[pin['path']])
 def checked(pin):
  assert set(pin)=={'path','sha256'}
  assert hashlib.sha256(raw[pin['path']]).hexdigest()==pin['sha256']
 def artifact(pin,checked):
  checked({k:pin[k]for k in ('path','sha256')})
  if 'bytes'in pin:assert len(raw[pin['path']])==pin['bytes']
  return pin
 oldread=Path.read_text;oldstat=Path.stat
 monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:raw[str(p)].decode()if str(p).startswith('/fixture/')else oldread(p,*a,**k))
 monkeypatch.setattr(Path,'stat',lambda p,*a,**k:SimpleNamespace(st_dev=1,st_ino=inodes[str(p)],st_size=len(raw[str(p)]))if str(p).startswith('/fixture/')else oldstat(p,*a,**k))
 monkeypatch.setattr(m,'read_artifact',read_artifact);monkeypatch.setattr(m,'artifact',artifact)
 monkeypatch.setattr(m,'verify_installation',lambda *a:True);monkeypatch.setattr(m,'verify_baseline_relink',lambda *a:True)
 old_source='/fixture/original/source';old_build='/fixture/original/build';candidate_source='/fixture/candidate/native_source/candidate/source';buildroot='/fixture/candidate/build';repo='/fixture/repository';prefix='/fixture/prefix'
 tool={'schema':'orbit-poc-native-complete-toolchain-v1',**{k:blob('/fixture/tool/'+k,k)for k in ('python','cmake','ninja','cxx','cc','fc','git')}}
 cpp={f'obj/c{i}.o':f'c{i}.cpp'for i in range(591)};fort={f'obj/f{i}.o':f'f{i}.f'for i in range(20)}
 objects=list(cpp)+list(fort)
 def command_list(root):
  out=[shlex.join([tool['cxx']['path'],'-I'+root,'-O3','-DNDEBUG','-std=gnu++17','-o',o,'-c',root+'/'+source])for o,source in cpp.items()]
  out +=[shlex.join([tool['fc']['path'],'-cpp','-I'+root,'-E',root+'/'+source,'-o',o+'.pp'])for o,source in fort.items()]
  out +=[shlex.join([tool['fc']['path'],'-I'+root,'-fpreprocessed','-o',o,'-c',o+'.pp'])for o in fort]
  out +=[shlex.join([tool['cmake']['path'],'-E','cmake_ninja_dyndep'])]
  out +=[': && '+shlex.join([tool['cxx']['path'],*objects,'-o','groops','/fixture/lib.so'])+' && :']
  return out
 original_commands=command_list(old_source);commands=command_list(candidate_source);groups=m.command_inventory(commands)
 source={name:hashlib.sha256(name.encode()).hexdigest()for name in [*cpp.values(),*fort.values()]}
 baseline_pin=blob('/fixture/base/run/build-result/result.json','base result')
 delta_pin=blob('/fixture/delta.json','source delta')
 original_manifest={'build_command':[tool['cmake']['path'],'-S',old_source,'-B',old_build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_DISABLE_FIND_PACKAGE_MPI=ON','-DCMAKE_PREFIX_PATH='+prefix]}
 base={'native':blob('/fixture/base/binaries/groops','baseline25661'),'link_command':m.clean_link(m.command_inventory(original_commands)['link'][0][1]),'original_build_manifest':doc('old-build-manifest',original_manifest)}
 receipt={'build_base_result':baseline_pin,'native_source_delta':delta_pin,'candidate_native_source_root':candidate_source,'installed_source_mapping':{name:'payload/'+name for name in list(source)[:7]}}
 recipes={'schema':'orbit-poc-native-source-delta-recipe-inspection-v1','observed_at':'2026-10-16T00:00:00Z','baseline_result':baseline_pin,'original_build_manifest':base['original_build_manifest'],'native':base['native'],'ninja':tool['ninja'],'all_commands':original_commands,'all_dependency_blocks':[],'native_compilations':0,'native_propagations':0}
 execution={'paths':{'native_source':'/fixture/candidate/native_source','build':buildroot,'prefix':prefix}}
 inventory={'root':repo}
 request={'repository_inventory':doc('repo-inventory',inventory)}
 install={'request':doc('install-request',request),'helper':blob('/fixture/helper.py','helper')}
 inputs={'baseline_result':baseline_pin,'source_delta':delta_pin,'recipe_inventory':doc('recipes',recipes),'toolchain':doc('toolchain',tool),'installation_request':install['request'],'installation_helper':install['helper']}
 receipt['original_recipe_inventory']=inputs['recipe_inventory']
 fixture_pin=blob('/fixture/fixtures.json','supplemental fixtures')
 relink={'passed':True};receipt['baseline_relink']=doc('relink',relink);receipt['installation_equivalence']=doc('installation',install)
 preflight={'status':'prepared_complete_build','inputs':dict(inputs),'baseline_relink':receipt['baseline_relink'],'installation_equivalence':receipt['installation_equivalence'],'supplemental_fixtures':fixture_pin,'source_after':source}
 inputs['preflight_result']=doc('preflight',preflight)
 audit={'passed':True,'preflight_result':inputs['preflight_result'],**{k:preflight[k]for k in ('baseline_relink','installation_equivalence','supplemental_fixtures')}}
 inputs['preflight_audit']=doc('audit',audit)
 plan={'phase':'build','inputs':inputs,'native':base['native'],'execution':doc('execution',execution)}
 candidate_commands={'schema':'orbit-poc-complete-native-command-inventory-v1','commands':commands,'raw':blob('/fixture/output/candidate-command-inventory.stdout','\n'.join(commands)+'\n')}
 command_pin=doc('commands',candidate_commands)
 actual='\n'.join(f'[{i+1}/{len(commands)}] {x}'for i,x in enumerate(commands))+'\n'
 log='# ninja log v7\n';targets=[]
 for x in commands:
  w=shlex.split(x);targets.append(w[w.index('-o')+1]if '-o'in w else'Fortran.dd')
 for i,target in enumerate(targets):log+=f'{i}\t{i+1}\t100\t{target}\t1234abcd\n'
 logpin=blob(buildroot+'/.ninja_log',log);verbosepin=blob('/fixture/output/complete-build.stdout',actual)
 logs=m.ninja_records(log);evidence={}
 for kind in ('cpp','fortran','preprocess'):
  evidence[kind]={}
  for target,(index,argv,text)in groups[kind].items():
   p=blob(buildroot+'/'+target,'fresh '+target);st=Path(p['path']).stat()
   evidence[kind][target]={**p,'bytes':st.st_size,'device':st.st_dev,'inode':st.st_ino,'command_index':index,'verbose_index':commands.index(text),'ninja_log':logs[target]}
   if kind in ('cpp','fortran'):blob('/fixture/base/build/'+target,'old '+target)
 link=groups['link'][0];evidence.update(linked_objects=sorted(objects),link={'command_index':link[0],'verbose_index':commands.index(link[2]),'ninja_log':logs['groops']},schema='orbit-poc-native-complete-compile-evidence-v1',candidate_commands=command_pin,ninja_log=logpin,verbose_stdout=verbosepin,reused_object_count=0)
 calls=[[tool['python']['path'],repo+'/groops/extension/'+name,'/fixture/candidate/native_source/candidate']+(['--numerics']if i==0 else[])for i,name in enumerate(('apply_extension.py','native_segmented.py','native_tangent_wide.py'))]
 configure=list(original_manifest['build_command']);configure[configure.index('-S')+1]=candidate_source;configure[configure.index('-B')+1]=buildroot
 calls +=[configure,[tool['cmake']['path'],'--build',buildroot,'--parallel','1'],[buildroot+'/groops','--help']]
 stages=[]
 for i,(label,argv)in enumerate(zip(['public-installer-0','public-installer-1','public-installer-2','configure','complete-build','native-help'],calls)):
  stages.append({'label':label,'argv':argv+(['--verbose']if i==4 else[]),'returncode':0,'stdout':verbosepin if i==4 else blob('/fixture/output/'+label+'.stdout',''),'stderr':blob('/fixture/output/'+label+'.stderr','')})
 stages.append({'label':'candidate-command-inventory','argv':[tool['ninja']['path'],'-C',buildroot,'-t','commands','groops'],'returncode':0,'stdout':candidate_commands['raw'],'stderr':blob('/fixture/output/candidate-command-inventory.stderr','')})
 deps=blob('/fixture/output/candidate-dependency-inventory.stdout','dependencies')
 stages.append({'label':'candidate-dependency-inventory','argv':[tool['ninja']['path'],'-C',buildroot,'-t','deps'],'returncode':0,'stdout':deps,'stderr':blob('/fixture/output/candidate-dependency-inventory.stderr','')})
 evidence['build_stage']=stages[4]
 oldroots={old_source:'<SOURCE>',old_build:'<BUILD>'};newroots={candidate_source:'<SOURCE>',buildroot:'<BUILD>'}
 norm={'schema':'orbit-poc-native-complete-normalized-configuration-v1','rule':'shlex tokens; replace only declared absolute source/build roots; preserve every remaining token and command multiplicity','original_roots':oldroots,'candidate_roots':newroots,'original_recipe_inventory':receipt['original_recipe_inventory'],'candidate_commands':command_pin,'public_script_argv':[repo+'/scripts/build_groops.py','--source-dir','/fixture/candidate/native_source/candidate','--build-dir',buildroot,'--prefix',prefix,'--jobs','1','--numerics','--segmented','--wide-tangent-candidate','--cmake-executable',tool['cmake']['path']],'public_run_calls':calls,'verbose_only_build_argument':'--verbose','serial_jobs':1,'compiler_pins':inputs['toolchain'],'normalized_commands':[m.normalized_command(x,newroots)for x in commands]}
 native=blob('/fixture/candidate/binaries/native','native');cache=blob(buildroot+'/CMakeCache.txt','cache')
 repo_map={'scripts/build_groops.py':'a'*64,'groops/extension/wide_tangent/manifest.json':'b'*64}
 wrapped={'source/'+k:v for k,v in source.items()};manifest={'executable_sha256':native['sha256'],'cmake_cache_sha256':cache['sha256'],'mpi':False,'upstream_commit':m.UPSTREAM_COMMIT,'build_command':calls[3],'build_script_sha256':repo_map['scripts/build_groops.py'],'wide_tangent_extension':{'schema':'orbit-poc-wide-tangent-install-v1','candidate_only':True,'changed_files':7,'source_hashes':{name:source[name]for name in receipt['installed_source_mapping']},'manifest_sha256':repo_map['groops/extension/wide_tangent/manifest.json'],'compiled':False},'patched_source':{'files':wrapped,'sha256':m.digest(wrapped)}}
 build={'schema':'orbit-poc-native-complete-build-v1','status':'built_complete_candidate','baseline_result':baseline_pin,'source_delta':delta_pin,'original_recipe_inventory':receipt['original_recipe_inventory'],'baseline_relink':receipt['baseline_relink'],'installation_equivalence':receipt['installation_equivalence'],'supplemental_fixtures':fixture_pin,'compiled_object_count':611,'preprocessing_count':20,'reused_object_count':0,'fit_attempts':0,'release_evidence':False,'plan':doc('plan',plan),'source_after':source,'stages':stages,'native':native,'build_manifest':doc('build-manifest',manifest),'cmake_cache':cache,'candidate_dependencies':deps}
 documents={'build_base_result':base,'original_recipe_inventory':recipes,'normalized_configuration':norm,'complete_compile_evidence':evidence,'baseline_relink':relink,'installation_equivalence':install}
 def seal():
  for key in ('normalized_configuration','complete_compile_evidence'):
   receipt[key]=doc(key,documents[key]);build[key]=receipt[key]
  build['plan']=doc('plan',plan)
  # Re-sign the complete DAG after each semantic mutation. A rejected case
  # therefore cannot pass merely because its child JSON retained a stale hash.
  def rebind(value,seen):
   if id(value)in seen:return
   seen.add(id(value))
   if isinstance(value,dict):
    if {'path','sha256'}<=set(value)and value['path']in docs:
     value['sha256']=hashlib.sha256(json.dumps(docs[value['path']]).encode()).hexdigest()
    for item in value.values():rebind(item,seen)
   elif isinstance(value,list):
    for item in value:rebind(item,seen)
  for _ in range(12):
   rebind([*docs.values(),receipt,build,documents],set())
  for name,value in list(docs.items()):blob(name,json.dumps(value))
 seal()
 return dict(build=build,receipt=receipt,documents=documents,repo=repo_map,checked=checked,seal=seal,raw=raw,blob=blob,docs=docs,norm=norm,evidence=evidence,plan=plan,preflight=preflight,audit=audit,commands=candidate_commands,manifest=manifest,run=lambda:m.verify_complete_build(build,receipt,documents,repo_map,checked))

@pytest.fixture
def f(monkeypatch):return fixture(monkeypatch)

def test_full633_recipe611_object_receipt_passes(f):assert f['run']()

@pytest.mark.parametrize('case',['status','count','preprocess_count','reuse','release','baseline_pin','recipe_pin','norm_pin','preflight_failed','audit_failed','preflight_changed','preflight_artifact','plan_phase','source_root','normalization_rule','normalized_value','multiplicity','missing_recipe','compile_flag','missing_object','object_index','verbose_index','log_record','object_inode','object_hash','link_record','serial','stage_order','stage_failed','build_stage','toolchain','public_flag','configure_flag','dependency_pin','manifest_source','manifest_digest','manifest_native','manifest_script','manifest_mpi','missing_wide','native_help'])
def test_complete_build_mutation_rejected(f,case):
 b=f['build'];n=f['norm'];e=f['evidence'];p=f['plan'];target=next(iter(e['cpp']))
 if case=='status':b['status']='prepared_complete_build'
 elif case=='count':b['compiled_object_count']=610
 elif case=='preprocess_count':b['preprocessing_count']=19
 elif case=='reuse':b['reused_object_count']=1
 elif case=='release':b['release_evidence']=True
 elif case=='baseline_pin':b['baseline_result']={'path':'/wrong','sha256':'0'*64}
 elif case=='recipe_pin':b['original_recipe_inventory']={'path':'/wrong','sha256':'0'*64}
 elif case=='preflight_failed':f['preflight']['status']='failed'
 elif case=='audit_failed':f['audit']['passed']=False
 elif case=='preflight_changed':f['preflight']['source_after']={}
 elif case=='preflight_artifact':f['audit']['supplemental_fixtures']={'path':'/wrong','sha256':'0'*64}
 elif case=='plan_phase':p['phase']='prepare'
 elif case=='source_root':f['receipt']['candidate_native_source_root']='/wrong'
 elif case=='normalization_rule':n['rule']='drop flags'
 elif case=='normalized_value':n['normalized_commands'][0].append('-ffast-math')
 elif case=='multiplicity':f['documents']['original_recipe_inventory']['all_commands'][1]=f['documents']['original_recipe_inventory']['all_commands'][0]
 elif case=='missing_recipe':f['commands']['commands'].pop()
 elif case=='compile_flag':f['commands']['commands'][0]+=' -ffast-math'
 elif case=='missing_object':e['cpp'].pop(target)
 elif case=='object_index':e['cpp'][target]['command_index']=1
 elif case=='verbose_index':e['cpp'][target]['verbose_index']=1
 elif case=='log_record':e['cpp'][target]['ninja_log']=dict(e['cpp'][target]['ninja_log'],start_ms=999)
 elif case=='object_inode':e['cpp'][target]['inode']+=1000
 elif case=='object_hash':e['cpp'][target]['sha256']='0'*64
 elif case=='link_record':e['link']['command_index']=0
 elif case=='serial':n['serial_jobs']=2
 elif case=='stage_order':b['stages'][0],b['stages'][1]=b['stages'][1],b['stages'][0]
 elif case=='stage_failed':b['stages'][4]['returncode']=1
 elif case=='build_stage':e['build_stage']=copy.deepcopy(e['build_stage']);e['build_stage']['argv'].append('extra')
 elif case=='toolchain':n['compiler_pins']={'path':'/wrong','sha256':'0'*64}
 elif case=='public_flag':n['public_script_argv'].remove('--wide-tangent-candidate')
 elif case=='configure_flag':n['public_run_calls'][3]=n['public_run_calls'][3]+['-DOTHER=ON']
 elif case=='dependency_pin':b['candidate_dependencies']={'path':'/wrong','sha256':'0'*64}
 elif case=='manifest_source':f['manifest']['patched_source']['files']['source/extra']='0'*64
 elif case=='manifest_digest':f['manifest']['patched_source']['sha256']='0'*64
 elif case=='manifest_native':f['manifest']['executable_sha256']='0'*64
 elif case=='manifest_script':f['manifest']['build_script_sha256']='0'*64
 elif case=='manifest_mpi':f['manifest']['mpi']=True
 elif case=='missing_wide':f['manifest'].pop('wide_tangent_extension')
 elif case=='native_help':n['public_run_calls'][5]=['/different','--help']
 f['seal']()
 if case=='norm_pin':b['normalized_configuration']={'path':'/wrong','sha256':'0'*64}
 with pytest.raises((RuntimeError,KeyError,AssertionError)):f['run']()
