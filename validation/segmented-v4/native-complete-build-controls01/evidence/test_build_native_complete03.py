from pathlib import Path
import importlib.util,json,copy
import pytest
P=Path(__file__).with_name('build_native_complete03.py');sp=importlib.util.spec_from_file_location('full',P);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
@pytest.fixture(scope='module')
def commands():return json.loads(P.with_name('native-source-delta01-recipe-inspection01.json').read_text())['all_commands']
def test_actual_inventory(commands):
 r=m.classify(commands);assert(len(r['cpp']),len(r['fortran']),len(r['preprocess']),len(r['link']),len(r['dyndep']))==(591,20,20,1,1)
@pytest.mark.parametrize('change',['omit','duplicate','unknown','object','preprocess'])
def test_inventory_rejects(commands,change):
 c=list(commands)
 if change=='omit':c.pop(0)
 if change=='duplicate':c.append(c[0])
 if change=='unknown':c.append('echo unexpected')
 if change=='object':c[-1]=c[-1].replace('CMakeFiles/groopscore.dir/base/constants.cpp.o','CMakeFiles/missing.o',1)
 if change=='preprocess':c=[v for v in c if '-E 'not in v]
 with pytest.raises(ValueError):m.classify(c)
def test_normalization_only_roots():assert m.normalize('cc -I/a/source /a/source/x.cpp -o /b/build/x.o',{'/a/source':'<SOURCE>','/b/build':'<BUILD>'})==['cc','-I<SOURCE>','<SOURCE>/x.cpp','-o','<BUILD>/x.o']
@pytest.mark.parametrize('roots',[{'relative':'<SOURCE>'},{'/a/../b':'<SOURCE>'},{'/a':'<OTHER>'}])
def test_bad_roots(roots):
 with pytest.raises(ValueError):m.normalize(['cc'],roots)
def test_all_commands_path_equivalence(commands):
 old='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02';new='/fresh'
 c=[x.replace(old,new)for x in commands]
 m.compare_commands(commands,c,{old+'/groops-source/source':'<SOURCE>',old+'/build':'<BUILD>'},{new+'/groops-source/source':'<SOURCE>',new+'/build':'<BUILD>'})
@pytest.mark.parametrize('mutation',['optimization','serial','extra','compiler'])
def test_changed_commands_reject(commands,mutation):
 c=list(commands)
 if mutation=='optimization':c[0]=c[0].replace('-O3','-O2')
 if mutation=='serial':c[-1]+=' -pthread'
 if mutation=='extra':c[0]+=' -DOTHER'
 if mutation=='compiler':c[0]=c[0].replace('x86_64-conda-linux-gnu-c++','different-c++')
 with pytest.raises(ValueError):m.compare_commands(commands,c,{}, {})
def test_log_actual_shape():assert m.parse_log('# ninja log v7\n0\t2\t123\ta.o\tabc\n')['a.o']['line']==1
@pytest.mark.parametrize('text',['','other\n','# ninja log v7\n0\t-1\t123\ta.o\tabc\n','# ninja log v7\n0\t1\t0\ta.o\tabc\n','# ninja log v7\n0\t1\t1\ta.o\tabc\n0\t2\t2\ta.o\tdef\n','# ninja log v7\nbad\n'])
def test_bad_log(text):
 with pytest.raises(ValueError):m.parse_log(text)
def test_changed_pin(tmp_path):
 p=tmp_path/'x';p.write_text('a');pin=m.pin(p);p.write_text('b')
 with pytest.raises(ValueError):m.check(pin)
def test_exclusive_result(tmp_path):
 p=tmp_path/'x';m.write(p,{'passed':False})
 with pytest.raises(FileExistsError):m.write(p,{'passed':True})
def test_roundtrip(tmp_path):
 d=Path('/mnt/d/orbit-segmented-v4/source/src/orbit_poc/segmented/tangent_export.py')
 rows=[{'mode':'exact','derivative':0,'anchor':None,'terms':[[3,'0x1p+0','0x0p+0']]},{'mode':'anchored_twofold','derivative':0,'anchor':1,'terms':[[4,'0x1p-1','0x1p-70'],[1,'0x1p-1','0x0p+0']]}]
 assert m.decode_roundtrip(d,'\n'.join(json.dumps(x)for x in rows))['passed']
 rows[1]['terms'][0][2]='0x0p+0'
 with pytest.raises(ValueError):m.decode_roundtrip(d,'\n'.join(json.dumps(x)for x in rows))
def test_external_inventory_exact():
 assert m.external_dependencies(['a.o: #deps 2, deps mtime 1 (VALID)\n    /source/a.cpp\n    /sys/h.h'],Path('/source'))=={'/sys/h.h'}
@pytest.mark.parametrize('block',['a.o: #deps 2, deps mtime 1 (VALID)\n /sys/a','a.o: #deps 1, deps mtime 1 (STALE)\n /sys/a','a.o: #deps 1, deps mtime 1 (VALID)\n relative'])
def test_external_invalid(block):
 with pytest.raises(ValueError):m.external_dependencies([block],Path('/source'))
def test_cmake_tool_identity(tmp_path):
 tool={};lines=['CMAKE_BUILD_TYPE:STRING=Release','CMAKE_DISABLE_FIND_PACKAGE_MPI:BOOL=ON']
 for key,name in [('CMAKE_MAKE_PROGRAM','ninja'),('CMAKE_CXX_COMPILER','cxx'),('CMAKE_Fortran_COMPILER','fc')]:
  p=tmp_path/name;p.write_text(name);tool[name]=m.pin(p);lines.append(key+':FILEPATH='+str(p))
 m.check_cmake_tools('\n'.join(lines),tool)
 with pytest.raises(ValueError):m.check_cmake_tools('\n'.join(lines).replace('Release','Debug'),tool)
 (tmp_path/'ninja').write_text('changed')
 with pytest.raises(ValueError):m.check_cmake_tools('\n'.join(lines),tool)

@pytest.mark.parametrize('missing',['CMAKE_CXX_COMPILER','CMAKE_Fortran_COMPILER','CMAKE_MAKE_PROGRAM'])
def test_missing_enabled_tool_rejects(tmp_path,missing):
 tool={};lines=['CMAKE_BUILD_TYPE:STRING=Release','CMAKE_DISABLE_FIND_PACKAGE_MPI:BOOL=ON']
 for key,name in [('CMAKE_MAKE_PROGRAM','ninja'),('CMAKE_CXX_COMPILER','cxx'),('CMAKE_Fortran_COMPILER','fc')]:
  p=tmp_path/name;p.write_text(name);tool[name]=m.pin(p)
  if key!=missing:lines.append(key+':FILEPATH='+str(p))
 with pytest.raises(ValueError):m.check_cmake_tools('\n'.join(lines),tool)
def test_actual_cxx_fortran_project_cache(monkeypatch):
 import base64
 records=json.loads(P.with_name('native-complete-build01-ninja-lineage01.json').read_text())['cache_files']
 observed=json.loads(P.with_name('native-complete-build01-toolchain-readback01.json').read_text())
 tool=observed['pinned_toolchain'];tool['ninja']={'path':observed['configured']['CMAKE_MAKE_PROGRAM']['logical'],'sha256':observed['configured']['CMAKE_MAKE_PROGRAM']['sha256']}
 digests={r['path']:r['sha256']for r in tool.values()if isinstance(r,dict)}
 monkeypatch.setattr(m,'sha',lambda path:digests[str(path)])
 for item in records:
  cache=base64.b64decode(item['base64']).decode();m.check_cmake_tools(cache,tool)
  with pytest.raises(ValueError,match='Unexpected C compiler'):m.check_cmake_tools(cache+'\nCMAKE_C_COMPILER:FILEPATH=/unexpected/cc\n',tool)

def test_actual_original_v7_record():
 import base64
 r=json.loads(P.with_name('native-complete-original-ninja-log01.json').read_text())['logs'][0]
 lines=base64.b64decode(r['base64']).decode().splitlines()
 assert lines[0]=='# ninja log v7'
 record=m.parse_log('\n'.join(lines[:2])+'\n')
 assert len(record)==1 and next(iter(record.values()))['raw']==lines[1]
@pytest.mark.parametrize('version',['v5','v6','v8'])
def test_wrong_log_version_rejects(version):
 with pytest.raises(ValueError):m.parse_log('# ninja log '+version+'\n0\t1\t123\tx.o\tabc\n')
