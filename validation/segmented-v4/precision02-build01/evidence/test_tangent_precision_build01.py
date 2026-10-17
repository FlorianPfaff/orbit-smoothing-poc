from pathlib import Path
import json,importlib.util
import pytest
C=Path(__file__).parent
s=importlib.util.spec_from_file_location('b',C/'build_tangent_precision01.py');b=importlib.util.module_from_spec(s);s.loader.exec_module(b)
OLD=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/groops-source');NEW=Path('/fresh/native')
def record():return json.loads((C/'tangent-precision-recipes01.json').read_text())
def test_all27_dependencies_compile():
 r=record();commands,link=b.recipes(r,OLD,NEW);assert len(commands)==27
 for target,command in commands.items():assert target in link and command[command.index('-o')+1]==target and str(NEW)in command[command.index('-c')+1] and '-O3'in command
@pytest.mark.parametrize('which',['missing_command','missing_dependency','duplicate_dependency','invalid_dependency','foreign_header','wrong_source','shell','link_target','compiler'])
def test_changed_dependency_recipe_rejected(which):
 r=record();key=next(iter(r['selected_compile_commands']))
 if which=='missing_command':del r['selected_compile_commands'][key]
 if which=='missing_dependency':r['header_dependency_blocks'].pop()
 if which=='duplicate_dependency':r['header_dependency_blocks'][-1]=r['header_dependency_blocks'][0]
 if which=='invalid_dependency':r['header_dependency_blocks'][0]=r['header_dependency_blocks'][0].replace('(VALID)','(STALE)')
 if which=='foreign_header':r['header_dependency_blocks'][0]=r['header_dependency_blocks'][0].replace('sixStateTangent.h','other.h')
 if which=='wrong_source':r['selected_compile_commands'][key]=r['selected_compile_commands'][key].replace(str(OLD/'source/base'),'/foreign/base')
 if which=='shell':r['selected_compile_commands'][key]+=' ;'
 if which=='link_target':r['link_command']=r['link_command'].replace(' -o groops ',' -o other ')
 if which=='compiler':r['selected_compile_commands'][key]=r['selected_compile_commands'][key].replace('x86_64-conda-linux-gnu-c++','g++')
 with pytest.raises((ValueError,AssertionError)):b.recipes(r,OLD,NEW)
