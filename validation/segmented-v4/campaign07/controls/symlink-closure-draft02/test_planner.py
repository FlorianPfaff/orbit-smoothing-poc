from pathlib import Path
import copy,fcntl,hashlib,importlib.util,json,os,stat
import pytest
HERE=Path(__file__).parent
def load(name,file):
 s=importlib.util.spec_from_file_location(name,(HERE/file if (HERE/file).exists() else HERE.parent/file));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('mount_planner01','plan_segmented_fit_namespace02.py')
f=load('allowlist02_fixture','test_prepare_segmented_fit_allowlist02.py')
a=f.m

def dp(p):
 s=p.stat();return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
def save(p,v):
 p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n');return m.host_pin(str(p))
def fixture(t,edit=None):
 old,_=f.fixture(t)
 if edit:edit(old,t)
 allow=a.build(old);ap=save(t/'allow.json',allow)
 symlinks={x['path']:x['link_target'] for x in allow['files'] if x['link_target'] is not None}
 for tree in allow['verified_safe_trees']:
  inv=json.loads(Path(tree['inventory']['path']).read_bytes())
  for e in inv['entries']:
   if e['link_target'] is not None:symlinks[inv['root']+'/'+e['relative']]=e['link_target']
 for inv in allow['native_data_inventories']:
  for e in inv['entries']:
   if e['link_target'] is not None:symlinks[inv['root']+'/'+e['relative']]=e['link_target']
 ex=save(t/'execution.json',{'read_only_bindings':[]})
 mapping={'schema':m.MAP_SCHEMA,'allowlist_sha256':ap['sha256'],'execution':ex,'canonical_symlinks':[{'path':p,'target':v} for p,v in sorted(symlinks.items())],'files':[{'canonical':p,'backing':m.host_pin(p)} for p in sorted({x['resolved'] for x in allow['files']})],'inventories':[{'canonical':x['inventory']['path'],'backing':m.host_pin(x['inventory']['path'])} for x in allow['verified_safe_trees']],'safe_trees':[{'canonical':x['root'],'backing':dp(Path(x['root']))} for x in allow['verified_safe_trees']],'writable':{'attempts':dp(Path(allow['writable']['attempts'])),'temporary':dp(Path(allow['writable']['temporary'])),'lock':m.host_pin(allow['writable']['lock']['path'])}}
 (t/'run-skeleton').mkdir();mapping['run_skeleton']=dp(t/'run-skeleton');mp=save(t/'mapping.json',mapping);p={'schema':m.SCHEMA,'allowlist':ap,'mapping':mp};fill_skeleton(p);return p
def fill_skeleton(plan):
 spec=m.skeleton_spec(plan)['skeleton'];root=Path(spec['backing']['path'])
 for e in sorted(spec['entries'],key=lambda x:(len(Path(x['relative']).parts),x['relative'])):
  p=root/e['relative'];p.parent.mkdir(parents=True,exist_ok=True)
  if e['kind']=='directory':p.mkdir(exist_ok=True)
  elif e['kind']=='symlink':p.symlink_to(e['link_target'])
  else:p.touch()
def change(plan,key,fn):
 p=Path(plan[key]['path']);v=json.loads(p.read_bytes());fn(v);plan[key]=save(p,v);return v
def rehash_allow(plan,fn):
 def edit(v):fn(v);v['allowlist_hash']=m.canonical({k:x for k,x in v.items() if k!='allowlist_hash'})
 change(plan,'allowlist',edit);change(plan,'mapping',lambda v:v.update(allowlist_sha256=plan['allowlist']['sha256']))
def test_valid_plan_is_conditional_empty_root_and_exact_write_set(tmp_path):
 p=fixture(tmp_path);v=m.build(p);args=v['mount_args'];assert args[:5]==['--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts'];assert ['--tmpfs','/']==args[args.index('--tmpfs'):args.index('--tmpfs')+2];assert args[-2:]==['--remount-ro','/'];assert {x['kind'] for x in v['writable_mounts']}=={'attempts','temporary','lock'};assert not v['fit_execution_authorized'];assert '--dev-bind' not in args and '--bind-try' not in args;assert all(x['source']!='/' for x in v['readonly_mounts']);assert len(v['verified_safe_trees'])==3

def add_external(old,t,directory=False):
 target=t/'outside';target.mkdir();(target/'data.so').write_text('allowed external library');source=t/'source/src';link=source/('external' if directory else 'external.so');link.symlink_to(target if directory else target/'data.so',target_is_directory=directory)
 ip=Path(old['safe_trees'][0]['inventory']['path']);old['safe_trees'][0]['inventory']=f.save(ip,a.inventory(t/'source'))
@pytest.mark.parametrize('directory',[False,True])
def test_safe_tree_external_symlink_targets_are_individual_files(tmp_path,directory):
 p=fixture(tmp_path,lambda old,t:add_external(old,t,directory));v=m.build(p);out=str(tmp_path/'outside/data.so');assert any(x['target']==out and x['kind']=='file' for x in v['readonly_mounts']);assert not any(x['target']==str(tmp_path/'outside') for x in v['readonly_mounts']);assert not any('--ro-bind'==v['mount_args'][i] and v['mount_args'][i+1]==str(tmp_path/'outside') for i in range(len(v['mount_args'])-1))
def test_explicit_parent_alias_uses_overlay_not_host_libc(tmp_path):
 p=fixture(tmp_path);lib=tmp_path/'overlay-libc';lib.write_text('pinned isolated libc');q=m.host_pin(str(lib));row={**q,'path':'/lib/test.so','resolved':'/usr/lib/test.so','link_target':None,'reasons':['required system dependency']}
 rehash_allow(p,lambda v:v['files'].append(row))
 def edit(v):
  v['files'].append({'canonical':'/usr/lib/test.so','backing':q});v['canonical_symlinks'].append({'path':'/lib','target':'usr/lib'});v['execution']=save(tmp_path/'execution.json',{'read_only_bindings':[{'source':str(lib),'target':'/lib/test.so'}]})
 change(p,'mapping',edit);v=m.build(p);assert any(x['source']==str(lib) and x['target']=='/usr/lib/test.so' for x in v['readonly_mounts']);assert not any(x['source']=='/usr/lib/test.so' for x in v['readonly_mounts']);assert ['--symlink','usr/lib','/lib'] in [v['mount_args'][i:i+3] for i in range(len(v['mount_args'])-2)]
@pytest.mark.parametrize('mutation',['missing','extra','duplicate'])
def test_file_map_exact_membership(tmp_path,mutation):
 p=fixture(tmp_path)
 def edit(v):
  if mutation=='missing':v['files'].pop()
  elif mutation=='extra':v['files'].append({'canonical':'/extra','backing':v['files'][0]['backing']})
  else:v['files'].append(v['files'][0])
 change(p,'mapping',edit)
 with pytest.raises(ValueError,match='membership|Duplicate'):m.build(p)
@pytest.mark.parametrize('key',['allowlist','mapping'])
def test_input_byte_tamper_rejected(tmp_path,key):
 p=fixture(tmp_path);Path(p[key]['path']).write_text('{}')
 with pytest.raises(ValueError,match='Pinned backing'):m.build(p)
def test_unknown_mapping_field_rejected(tmp_path):
 p=fixture(tmp_path);change(p,'mapping',lambda v:v.update(host_root='/'))
 with pytest.raises(ValueError,match='schema/fields'):m.build(p)
def test_safe_tree_extra_file_rejected_even_when_inputs_unchanged(tmp_path):
 p=fixture(tmp_path);(tmp_path/'source/unlisted').write_text('extra')
 with pytest.raises(ValueError,match='membership'):m.build(p)
def test_safe_tree_extra_empty_directory_rejected(tmp_path):
 p=fixture(tmp_path);(tmp_path/'source/unlisted').mkdir()
 with pytest.raises(ValueError,match='membership'):m.build(p)
def test_changed_file_content_rejected(tmp_path):
 p=fixture(tmp_path);(tmp_path/'source/src/a.py').write_text('changed')
 with pytest.raises(ValueError,match='Pinned backing'):m.build(p)
def test_changed_inode_with_same_bytes_rejected(tmp_path):
 p=fixture(tmp_path);q=tmp_path/'source/src/a.py';b=q.read_bytes();q.rename(tmp_path/'old-file');q.write_bytes(b)
 with pytest.raises(ValueError,match='identity'):m.build(p)
def test_physical_tree_special_file_rejected(tmp_path):
 p=fixture(tmp_path);os.mkfifo(tmp_path/'source/fifo')
 with pytest.raises(ValueError,match='Special file'):m.build(p)
def test_setid_file_rejected(tmp_path):
 p=fixture(tmp_path);q=tmp_path/'source/src/a.py';q.chmod(q.stat().st_mode|stat.S_ISUID)
 with pytest.raises(ValueError,match='set-id|Set-id'):m.build(p)
@pytest.mark.parametrize('kind',['attempts','temporary'])
def test_nonempty_writable_directory_rejected(tmp_path,kind):
 p=fixture(tmp_path);d=json.loads(Path(p['mapping']['path']).read_bytes());(Path(d['writable'][kind]['path'])/'secret').write_text('no')
 with pytest.raises(ValueError,match='empty'):m.build(p)
def test_replaced_lock_inode_rejected(tmp_path):
 p=fixture(tmp_path);q=tmp_path/'run/.segmented.lock';q.rename(tmp_path/'old-lock');q.touch()
 with pytest.raises(ValueError,match='identity'):m.build(p)
def test_wrong_execution_binding_rejected(tmp_path):
 p=fixture(tmp_path)
 def edit(v):v['execution']=save(tmp_path/'execution.json',{'read_only_bindings':[{'source':str(tmp_path/'different'),'target':str(tmp_path/'source')}]})
 change(p,'mapping',edit)
 with pytest.raises(ValueError,match='execution binding'):m.build(p)
def test_host_lookup_never_silently_substitutes_an_unpinned_file(tmp_path):
 p=fixture(tmp_path);fake=tmp_path/'fake';fake.write_text('other')
 change(p,'mapping',lambda v:v['files'][0].update(backing=m.host_pin(str(fake))))
 with pytest.raises(ValueError,match='execution binding|identity'):m.build(p)
@pytest.mark.parametrize('path',['/','/proc/self/root/file','/dev/fd/9','/sys/a','/a/../b'])
def test_host_root_kernel_and_noncanonical_paths_rejected(path):
 with pytest.raises(ValueError):m.absolute(path)
def test_extra_coarse_tree_mapping_rejected(tmp_path):
 p=fixture(tmp_path);change(p,'mapping',lambda v:v['safe_trees'].append({'canonical':'/extra','backing':dp(tmp_path)}))
 with pytest.raises(ValueError,match='membership'):m.build(p)
def test_inventory_map_missing_rejected(tmp_path):
 p=fixture(tmp_path);change(p,'mapping',lambda v:v['inventories'].pop())
 with pytest.raises(ValueError,match='inventory map'):m.build(p)
def test_unknown_symlink_alias_rejected(tmp_path):
 p=fixture(tmp_path);change(p,'mapping',lambda v:v['canonical_symlinks'].append({'path':'/unused','target':'/host'}))
 with pytest.raises(ValueError,match='Unused'):m.build(p)
def test_wrong_file_symlink_rejected(tmp_path):
 p=fixture(tmp_path,add_external);change(p,'mapping',lambda v:v['canonical_symlinks'][0].update(target='/wrong'))
 with pytest.raises(ValueError,match='topology|symlink'):m.build(p)
def test_symlink_cycles_rejected():
 with pytest.raises(ValueError,match='cycle'):m.links_resolve('/a/file',{'/a':'/b','/b':'/a'})
def test_symlink_cannot_target_kernel_or_host_root():
 with pytest.raises(ValueError):m.links_resolve('/a',{'/a':'/proc/self/root'})
 with pytest.raises(ValueError):m.links_resolve('/a',{'/a':'/'})
def test_readable_sensitive_content_copy_rejected(tmp_path):
 p=fixture(tmp_path);allow=json.loads(Path(p['allowlist']['path']).read_bytes());truth=next(x for x in allow['denied_files'] if x['content_sensitive']);q=tmp_path/'source/src/a.py';q.write_bytes(Path(truth['path']).read_bytes())
 def edit(v):
  for r in v['files']:
   if r['canonical']==str(q):r['backing']=m.host_pin(str(q))
 change(p,'mapping',edit)
 with pytest.raises(ValueError,match='Denied'):m.build(p)
def test_sealed_memfd_preserves_large_exact_args_and_rejects_mutation():
 args=['--dir','/a path/with spaces']*20000;fd=m.sealed_args_fd(args)
 try:
  assert os.get_inheritable(fd) is False;assert os.read(fd,len(m.args_bytes(args))+1)==m.args_bytes(args)
  with pytest.raises(OSError):os.write(fd,b'x')
  with pytest.raises(OSError):os.ftruncate(fd,0)
 finally:os.close(fd)
def test_embedded_nul_args_rejected():
 with pytest.raises(ValueError):m.args_bytes(['--dir','/a\0--bind'])
def test_no_command_is_embedded_in_mount_plan(tmp_path):
 v=m.build(fixture(tmp_path));assert not v['policy']['command_included'];assert '--' not in v['mount_args'];assert v['mount_args_payload']['sha256']==m.digest(m.args_bytes(v['mount_args']))

def test_home_and_caches_remain_inside_exact_private_temp(tmp_path):
 v=m.build(fixture(tmp_path));temp=next(x['target'] for x in v['writable_mounts'] if x['kind']=='temporary');env=v['policy']['required_environment'];assert env['TMPDIR']==temp and env['HOME']==temp+'/home' and env['XDG_CACHE_HOME']==temp+'/cache';assert not any(x['target']=='/home' for x in v['readonly_mounts'])

def test_nonempty_run_skeleton_file_rejected(tmp_path):
 p=fixture(tmp_path);q=next(x for x in (tmp_path/'run-skeleton').rglob('*') if x.is_file() and not x.is_symlink());q.write_text('hidden truth')
 with pytest.raises(ValueError,match='skeleton exact'):m.build(p)
def test_extra_run_skeleton_file_rejected(tmp_path):
 p=fixture(tmp_path);(tmp_path/'run-skeleton/secret').write_text('hidden truth')
 with pytest.raises(ValueError,match='skeleton exact'):m.build(p)
def test_skeleton_filesystem_mismatch_rejected(tmp_path):
 p=fixture(tmp_path);change(p,'mapping',lambda v:v['run_skeleton'].update(device=v['run_skeleton']['device']+1))
 with pytest.raises(ValueError,match='Directory backing identity|filesystem'):m.build(p)
def test_skeleton_spec_does_not_claim_sealed_plan_or_launch(tmp_path):
 p=fixture(tmp_path);s=m.skeleton_spec(p);assert s['schema']=='orbit-poc-segmented-fit-run-skeleton-request-v1';assert 'mount_args' not in s;assert not s['fit_execution_authorized'];v=m.build(p);args=v['mount_args'];assert v['run_skeleton_verified'];assert args.index(str(tmp_path/'run-skeleton'))<args.index(str(tmp_path/'run/attempts'))

@pytest.mark.parametrize('directory',[False,True])
def test_native_data_file_and_directory_symlinks_preserve_exact_targets(tmp_path,directory):
 def edit(old,t):
  outside=t/'external-products';outside.mkdir();(outside/'gps.G01.dat').write_text('GNSS product');link=t/'prepared/data/gps';link.symlink_to(outside if directory else outside/'gps.G01.dat',target_is_directory=directory);f.update_preparation(old,t,[])
 p=fixture(tmp_path,edit);v=m.build(p);assert any(x['target']==str(tmp_path/'external-products/gps.G01.dat') and x['kind']=='file' for x in v['readonly_mounts']);assert not any(x['target']==str(tmp_path/'external-products') for x in v['readonly_mounts'])
def test_run_skeleton_keeps_declared_symlink_not_host_directory(tmp_path):
 def edit(old,t):
  link=t/'run/metadata/alias';link.parent.mkdir();link.symlink_to('../../prepared/data/orbit.dat');support=json.loads(Path(old['support_inventory']['path']).read_bytes());support['files'].append(a.pin(link));old['support_inventory']=f.save(Path(old['support_inventory']['path']),support)
 p=fixture(tmp_path,edit);v=m.build(p);assert (tmp_path/'run-skeleton/metadata/alias').is_symlink();assert os.readlink(tmp_path/'run-skeleton/metadata/alias')=='../../prepared/data/orbit.dat';assert ['--chdir',str(tmp_path/'run')] in [v['mount_args'][i:i+2] for i in range(len(v['mount_args'])-1)]
 q=tmp_path/'run-skeleton/metadata/alias';q.unlink();q.symlink_to('/proc/1/root')
 with pytest.raises(ValueError,match='skeleton exact'):m.build(p)

def test_declared_private_environment_is_in_sealed_args(tmp_path):
 v=m.build(fixture(tmp_path));args=v['mount_args'];declared={args[i+1]:args[i+2] for i,a in enumerate(args) if a=='--setenv'};assert declared==v['policy']['required_environment'];assert declared['PWD']==str(tmp_path/'run');assert '--clearenv' in args
