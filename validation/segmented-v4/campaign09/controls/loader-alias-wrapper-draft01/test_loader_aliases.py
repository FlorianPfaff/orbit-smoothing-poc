from pathlib import Path
import copy,importlib.util,json
import pytest
from test_wrapper import fixture,m,run,write

FROZEN=dict(m.FROZEN_SYSTEM_LIBRARIES)
C=Path('/mnt/d/orbit-segmented-v4/control')

def test_production_alias_set_is_exact_measured_six():
 d=json.loads((C/'frozen-loader-search-audit01/diagnosis.json').read_text())
 assert FROZEN=={Path(r['destination']).name:r['existing_backing']['sha256'] for r in d['exact_proposed_symlinks']}
 assert len(FROZEN)==6

@pytest.mark.parametrize('kind',['missing_library','wrong_library_hash','loader_hash','default_directory','loader_alias','destination_file','destination_dir','destination_symlink','mounted_parent','root_boundary','multiple_root_boundary'])
def test_alias_fail_closed_before_exec(fixture,kind,monkeypatch):
 p,mount,files,cfg,inner,fresh,probe=fixture
 source='/usr/lib/x86_64-linux-gnu/libc.so.6';dest='/usr/lib64/libc.so.6'
 if kind=='missing_library':del files[source]
 if kind=='wrong_library_hash':monkeypatch.setitem(m.FROZEN_SYSTEM_LIBRARIES,'libc.so.6','0'*64)
 if kind=='loader_hash':monkeypatch.setattr(m,'FROZEN_LOADER_SHA256','0'*64)
 if kind=='default_directory':mount['canonical_symlinks'][0]['target']='wrong'
 if kind=='loader_alias':mount['canonical_symlinks'][1]['target']='/wrong/loader'
 if kind=='destination_file':files[dest]=copy.deepcopy(files[source])
 if kind=='destination_dir':mount['mount_args'][2:2]=['--dir',dest]
 if kind=='destination_symlink':mount['canonical_symlinks'].append({'path':dest,'target':source})
 if kind=='mounted_parent':mount['readonly_mounts'].append({'target':'/usr/lib64'})
 if kind=='root_boundary':mount['mount_args']=mount['mount_args'][:-2]
 if kind=='multiple_root_boundary':mount['mount_args']+=['--remount-ro','/']
 p['mount_plan']=write(Path(p['mount_plan']['path']),mount)
 with pytest.raises(RuntimeError):run(fixture)


def test_actual_mount_adds_exact_six_links_without_changing_existing_vector():
 mount=json.loads((C/'direct-sealing05-terminal01/sealed/mount-plan.json').read_text())
 old=copy.deepcopy(mount)
 s=importlib.util.spec_from_file_location('planner',Path(__file__).with_name('plan_segmented_fit_namespace01.py'));fresh=importlib.util.module_from_spec(s);s.loader.exec_module(fresh)
 checked=[]
 def backing(pin):
  assert mount['verified_file_backings'][pin['path']]['sha256']==pin['sha256'];checked.append(pin)
 args,aliases=m.add_loader_aliases(mount,mount,fresh,backing)
 assert len(aliases)==6 and len(checked)==7
 extra=[v for row in aliases for v in ('--symlink',row['target'],row['path'])]
 assert args==old['mount_args'][:-2]+extra+old['mount_args'][-2:]
 assert mount==old
 links={x['path']:x['target'] for x in mount['canonical_symlinks']}
 links.update({r['path']:r['target'] for r in aliases})
 for row in aliases:
  assert fresh.links_resolve(row['path'],links)==row['target']
  assert fresh.links_resolve(row['path'].replace('/usr/lib64/','/lib64/'),links)==row['target']
 assert fresh.links_resolve('/lib64/ld-linux-x86-64.so.2',links)=='/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
