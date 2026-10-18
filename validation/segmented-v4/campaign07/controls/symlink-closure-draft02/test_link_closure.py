from pathlib import Path
import importlib.util
import json
import pytest

D=Path(__file__).parent
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('closure_planner',D/'plan_segmented_fit_namespace02.py')
s=load('closure_sealer',D/'seal_direct_fit_inputs04.py')
f=load('closure_planner_fixtures',D/'test_planner.py')

def minimal(paths):
 return {'files':[{'path':str(p)} for p in paths],'directories':[], 'verified_safe_trees':[],'native_data_inventories':[]}

@pytest.mark.parametrize('absolute',[False,True])
def test_actual_parent_rewrite_discovers_child_link_and_emits_once(tmp_path,absolute):
 real=tmp_path/'actual';(real/'lib64').mkdir(parents=True);(real/'lib').mkdir();target=real/'lib/loader';target.write_text('frozen payload')
 child=real/'lib64/loader';child.symlink_to(target if absolute else '../lib/loader')
 parent=tmp_path/'alias';parent.symlink_to('actual/lib64')
 name=parent/'loader';links={r['path']:r['target'] for r in s.link_inventory(minimal([name]))}
 assert links[str(name)]==links[str(child)]
 assert m.links_resolve(str(name),links)==str(target)
 placements=m.symlink_placements(links)
 assert str(name) not in placements and placements[str(child)]==links[str(child)]
 assert len(placements)==2

def test_intermediate_absolute_and_relative_target_links_are_closed(tmp_path):
 (tmp_path/'data').write_text('payload');(tmp_path/'third').symlink_to('data');(tmp_path/'second').symlink_to(tmp_path/'third');(tmp_path/'first').symlink_to('second')
 links={r['path']:r['target'] for r in s.link_inventory(minimal([tmp_path/'first']))}
 assert set(links)=={str(tmp_path/x) for x in ('first','second','third')}
 used=set();assert m.links_resolve(str(tmp_path/'first'),links,used)==str(tmp_path/'data') and used==set(links)

def test_actual_cycle_fails_explicitly(tmp_path):
 (tmp_path/'a').symlink_to('b');(tmp_path/'b').symlink_to('a')
 with pytest.raises(ValueError,match='cycle'):s.link_inventory(minimal([tmp_path/'a']))

def test_conflicting_aliased_link_text_rejected():
 links={'/alias':'real','/alias/leaf':'one','/real/leaf':'two'}
 with pytest.raises(ValueError,match='Conflicting'):m.symlink_placements(links)

def test_alias_missing_canonical_child_rejected():
 links={'/alias':'real','/alias/leaf':'/target'}
 with pytest.raises(ValueError,match='closure'):m.symlink_placements(links)

@pytest.mark.parametrize('absolute',[False,True])
def test_full_planner_preserves_alias_ledger_but_places_child_once(tmp_path,absolute):
 p=f.fixture(tmp_path);back=tmp_path/'loader-payload';back.write_text('pinned loader fixture')
 q=m.host_pin(str(back));target='/usr/lib/example/loader';child='/usr/lib64/loader';name='/lib64/loader';text=target if absolute else '../lib/example/loader'
 row={**q,'path':name,'resolved':target,'link_target':text,'reasons':['required system dependency']}
 f.rehash_allow(p,lambda v:v['files'].append(row))
 def edit(v):
  v['files'].append({'canonical':target,'backing':q})
  v['canonical_symlinks'] += [{'path':'/lib64','target':'usr/lib64'},{'path':name,'target':text},{'path':child,'target':text}]
  v['execution']=f.save(tmp_path/'execution.json',{'read_only_bindings':[{'source':str(back),'target':target}]})
 f.change(p,'mapping',edit);v=m.build(p);args=v['mount_args']
 emitted=[args[i+1:i+3] for i,x in enumerate(args) if x=='--symlink']
 assert [text,child] in emitted and [text,name] not in emitted
 assert len([r for r in emitted if r[0]==text])==1
 assert [str(x) for x in v['canonical_symlinks'] if x['path'] in (name,child)]
 assert any(args[i:i+2]==['--dir','/usr/lib64'] for i in range(len(args)-1))
 assert v['fit_execution_authorized'] is False

def test_unrelated_added_symlink_remains_rejected(tmp_path):
 p=f.fixture(tmp_path)
 f.change(p,'mapping',lambda v:v['canonical_symlinks'].append({'path':'/unused','target':'/elsewhere'}))
 with pytest.raises(ValueError,match='Unused'):m.build(p)

def test_closed_ledger_does_not_normalize_away_conflicting_alias_text():
 links={'/alias':'real','/alias/leaf':'/target','/real/leaf':'../target'}
 with pytest.raises(ValueError,match='Conflicting'):m.symlink_placements(links)

def test_normalized_safe_tree_link_is_not_separately_emitted(tmp_path):
 def add(old,t):
  tree=t/'source/src';(tree/'real').mkdir();(tree/'real/data').write_text('fixture');(tree/'real/link').symlink_to('data');(tree/'alias').symlink_to('real')
  old['safe_trees'][0]['inventory']=f.f.save(Path(old['safe_trees'][0]['inventory']['path']),f.a.inventory(t/'source'))
 p=f.fixture(tmp_path,add);v=m.build(p);args=v['mount_args']
 assert not any(args[i]=='--symlink' and args[i+2].startswith(str(tmp_path/'source')+'/') for i in range(len(args)-2))
