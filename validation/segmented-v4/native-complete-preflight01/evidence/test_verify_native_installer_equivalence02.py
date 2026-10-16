"""Pure source fixtures: mock Git reads, real Python stub patchers, no native work."""
from pathlib import Path
import hashlib,importlib.util,io,json,os,sys,tarfile,tempfile,unittest,subprocess
from unittest import mock
P=Path(__file__).with_name('verify_native_installer_equivalence02.py')
S=importlib.util.spec_from_file_location('installer_equivalence',P);m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
class Equivalence(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.repo=self.root/'repository';self.ext=self.repo/'groops/extension';self.ext.mkdir(parents=True);(self.repo/'scripts').mkdir();(self.repo/'scripts/build_groops.py').write_text('# never executed\n')
  self.upstream=self.root/'genuine-metadata-fixture';self.gitdir=self.upstream/'.git';self.gitdir.mkdir(parents=True);(self.gitdir/'HEAD').write_text(m.COMMIT+'\n')
  self.initial={f'base/file-{i:04}.txt':f'original{i}\n'.encode()for i in range(1131)};self.baseline={'source_after':{k:m.sha(v)for k,v in self.initial.items()}}
  self.archive=self.root/'upstream-source.tar';self.make_archive()
  self.baseline_file=self.root/'baseline.json';self.write(self.baseline_file,self.baseline)
  changes=[];self.new={}
  for i in range(7):
   name=f'base/file-{i:04}.txt'if i<4 else f'new/added-{i}.h';data=f'updated{i}\n'.encode();self.new[name]=data;f=self.root/f'payload-{i}.txt';f.write_bytes(data)
   changes.append(dict(relative=name,action='replace'if i<4 else'add',old_sha256=self.baseline['source_after'].get(name),new_file=m.pin(f)))
  self.delta=dict(schema='orbit-poc-native-source-delta-v1',baseline_result=m.pin(self.baseline_file),base_source_sha256=m.sha(m.canonical_json(self.baseline['source_after'])),changes=changes)
  self.delta_file=self.root/'delta.json';self.write(self.delta_file,self.delta)
  self.script('apply_extension.py',"import sys\nassert sys.argv[2:]==['--numerics']\n")
  self.script('native_segmented.py','print("fixture segmented installer")\n')
  self.script('native_tangent_wide.py','from pathlib import Path\nimport sys\nroot=Path(sys.argv[1])/"source"\nvalues='+repr(self.new)+'\nfor name,data in values.items():\n p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)\n')
  self.inventory_file=self.root/'repository-inventory.json';self.refresh_inventory()
  self.git=Path('/usr/bin/git');self.python=Path(sys.executable).resolve()
  self.provenance=dict(schema='orbit-poc-pristine-native-source-archive-v1',repository=str(self.upstream),commit=m.COMMIT,archive=m.pin(self.archive),git_sha256=m.pin(self.git)['sha256'],uses_git_object_content_not_worktree=True)
  self.provenance_file=self.root/'archive-provenance.json';self.write(self.provenance_file,self.provenance)
  self.request=dict(schema=m.SCHEMA,archive=m.pin(self.archive),archive_provenance=m.pin(self.provenance_file),python=m.pin(self.python),git=m.pin(self.git),git_head=m.pin(self.gitdir/'HEAD'),git_dir=str(self.gitdir),repository_inventory=m.pin(self.inventory_file),baseline_result=m.pin(self.baseline_file),source_delta=m.pin(self.delta_file),output=str(self.root/'result'))
  self.request_file=self.root/'request.json';self.git_head_override=None;self.git_dir_override=None;self.real_run=subprocess.run;self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def write(self,p,v):p.write_text(json.dumps(v)+'\n')
 def script(self,name,text): (self.ext/name).write_text(text)
 def refresh_inventory(self):self.write(self.inventory_file,dict(schema='orbit-poc-native-installer-repository-inventory-v1',root=str(self.repo),files=m.repository_map(self.repo)))
 def refresh_repo(self):self.refresh_inventory();self.request['repository_inventory']=m.pin(self.inventory_file)
 def make_archive(self,extra=None,pax=True):
  with tarfile.open(self.archive,'w',format=tarfile.PAX_FORMAT,pax_headers={'comment':m.COMMIT}if pax else{})as tar:
   for name,data in self.initial.items():
    info=tarfile.TarInfo('source/'+name);info.size=len(data);info.mode=0o644;tar.addfile(info,io.BytesIO(data))
   if extra:
    info,data=extra;tar.addfile(info,io.BytesIO(data)if data is not None else None)
 def repin_archive(self):
  self.provenance['archive']=m.pin(self.archive);self.write(self.provenance_file,self.provenance);self.request['archive']=m.pin(self.archive);self.request['archive_provenance']=m.pin(self.provenance_file)
 def runner(self,argv,**kwargs):
  self.calls.append(argv)
  if argv[0]==str(self.git):
   value=(self.git_dir_override or str(self.gitdir))if argv[-1]=='--absolute-git-dir'else(self.git_head_override or m.COMMIT)
   kwargs['stdout'].write((value+'\n').encode());return subprocess.CompletedProcess(argv,0)
  return self.real_run(argv,**kwargs)
 def run_helper(self):
  self.write(self.request_file,self.request)
  with mock.patch.object(m.subprocess,'run',side_effect=self.runner):return m.execute(self.request_file,m.pin(self.request_file)['sha256'])
 def test_exact_full_tree_and_source_preservation(self):
  before=m.repository_map(self.repo);result=self.run_helper();self.assertTrue(result['passed'],result);self.assertEqual(len(result['source_after']),1134);self.assertEqual(m.repository_map(self.repo),before)
  self.assertTrue(result['repository_preserved']and result['git_head_preserved']);self.assertFalse(result['compiled']);self.assertEqual(result['native_launches'],0)
  installers=[x['argv']for x in result['commands']if x['argv'][0]==str(self.python)];self.assertEqual([Path(x[1]).name for x in installers],['apply_extension.py','native_segmented.py','native_tangent_wide.py']);self.assertEqual(installers[0][-1],'--numerics');self.assertTrue(result['archive_metadata']['pax_commit_present'])
 def test_no_pax_commit_never_invented(self):
  self.make_archive(pax=False);self.repin_archive();r=self.run_helper();self.assertTrue(r['passed']);self.assertIsNone(r['archive_metadata']['pax_commit'])
 def test_wrong_request_hash_rejected_before_output(self):
  self.write(self.request_file,self.request)
  with self.assertRaises(ValueError):m.execute(self.request_file,'0'*64)
  self.assertFalse(Path(self.request['output']).exists())
 def test_altered_archive_rejected(self):
  with self.archive.open('ab')as stream:stream.write(b'changed')
  r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_altered_repo_payload_rejected_before_patcher(self):
  self.script('native_segmented.py','raise RuntimeError("modified")\n');r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_extra_repository_member_rejected(self):
  (self.ext/'unexpected.py').write_text('');r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_missing_repository_member_rejected(self):
  (self.ext/'native_segmented.py').unlink();r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_extra_installed_source_retained_and_fails(self):
  p=self.ext/'native_tangent_wide.py';p.write_text(p.read_text()+'(root/"extra").write_text("x")\n');self.refresh_repo();r=self.run_helper();self.assertFalse(r['passed']);self.assertEqual(r['comparison']['extra'],['extra']);self.assertIn('extra',r['source_after'])
 def test_missing_installed_source_retained_and_fails(self):
  p=self.ext/'native_tangent_wide.py';p.write_text(p.read_text()+'(root/"base/file-1000.txt").unlink()\n');self.refresh_repo();r=self.run_helper();self.assertFalse(r['passed']);self.assertEqual(r['comparison']['missing'],['base/file-1000.txt'])
 def test_different_installed_source_fails(self):
  p=self.ext/'native_tangent_wide.py';p.write_text(p.read_text()+'(root/"base/file-1000.txt").write_text("wrong")\n');self.refresh_repo();r=self.run_helper();self.assertFalse(r['passed']);self.assertEqual(r['comparison']['different'],['base/file-1000.txt'])
 def test_failed_patcher_retains_logs_and_partial_tree(self):
  self.script('native_segmented.py','import sys\nprint("preserved stdout")\nprint("preserved stderr",file=sys.stderr)\nsys.exit(9)\n');self.refresh_repo();r=self.run_helper();self.assertFalse(r['passed']);self.assertEqual(len(r['source_after']),1131);self.assertIn('preserved stderr',(Path(self.request['output'])/'installer-02-native_segmented.py.stderr').read_text());self.assertEqual([Path(x[1]).name for x in self.calls if x[0]==str(self.python)],['apply_extension.py','native_segmented.py'])
 def test_repository_write_detected(self):
  self.script('native_segmented.py','from pathlib import Path\nPath(__file__).write_text("changed")\n');self.refresh_repo();r=self.run_helper();self.assertFalse(r['passed']);self.assertIn('repository mutated',r['preservation_error']['message'])
 def test_wrong_actual_git_head_fails(self):
  self.git_head_override='0'*40;r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(any(x[0]==str(self.python)for x in self.calls))
 def test_wrong_actual_git_directory_fails(self):
  self.git_dir_override=str(self.root);r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(any(x[0]==str(self.python)for x in self.calls))
 def test_output_inside_preserved_repository_rejected(self):
  self.request['output']=str(self.repo/'bad-output')
  with self.assertRaises(ValueError):self.run_helper()
  self.assertFalse((self.repo/'bad-output').exists())
 def test_existing_output_not_reused(self):
  Path(self.request['output']).mkdir()
  with self.assertRaises(ValueError):self.run_helper()
 def unsafe(self,name,kind=tarfile.REGTYPE,link=''):
  info=tarfile.TarInfo(name);info.type=kind;info.linkname=link;data=b'x'if kind==tarfile.REGTYPE else None;info.size=1 if data else 0;self.make_archive((info,data));self.repin_archive();r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(any(x[0]==str(self.python)for x in self.calls))
 def test_archive_escape_rejected(self):self.unsafe('source/../escape')
 def test_archive_absolute_rejected(self):self.unsafe('/source/absolute')
 def test_archive_other_root_rejected(self):self.unsafe('other/file')
 def test_archive_duplicate_rejected(self):self.unsafe('source/base/file-0000.txt')
 def test_archive_symlink_rejected(self):self.unsafe('source/link',tarfile.SYMTYPE,'../../elsewhere')
 def test_archive_hardlink_rejected(self):self.unsafe('source/link',tarfile.LNKTYPE,'source/base/file-0000.txt')
 def test_archive_device_rejected(self):self.unsafe('source/device',tarfile.CHRTYPE)
 def test_archive_fifo_rejected(self):self.unsafe('source/fifo',tarfile.FIFOTYPE)
 def test_archive_wrong_pax_commit_rejected(self):
  info=tarfile.TarInfo('source/extra');info.size=1;info.pax_headers={'comment':'0'*40};self.make_archive((info,b'x'));self.repin_archive();r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(any(x[0]==str(self.python)for x in self.calls))
 def test_delta_wrong_baseline_refused(self):
  self.delta['base_source_sha256']='0'*64;self.write(self.delta_file,self.delta);self.request['source_delta']=m.pin(self.delta_file);r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_delta_changed_payload_refused(self):
  (self.root/'payload-0.txt').write_text('changed');r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_delta_missing_change_refused(self):
  self.delta['changes'].pop();self.write(self.delta_file,self.delta);self.request['source_delta']=m.pin(self.delta_file);r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_wrong_python_identity_refused(self):
  fake=self.root/'not-current-python';fake.write_bytes(self.python.read_bytes());fake.chmod(0o755);self.request['python']=m.pin(fake);r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)
 def test_pin_symlink_rejected(self):
  alias=self.root/'archive-link';alias.symlink_to(self.archive);self.request['archive']['path']=str(alias)
  with self.assertRaises(ValueError):self.run_helper()
 def test_delta_payload_mutation_after_start_detected(self):
  payload=self.root/'payload-0.txt';self.script('native_segmented.py','from pathlib import Path\nPath('+repr(str(payload))+').write_text("changed")\n');self.refresh_repo();r=self.run_helper();self.assertFalse(r['passed']);self.assertIn('Input hash/size changed',r['preservation_error']['message'])
 def test_unknown_request_field_rejected(self):
  self.request['skip_comparison']=True
  with self.assertRaises(ValueError):self.run_helper()
  self.assertFalse(Path(self.request['output']).exists())
 def test_duplicate_json_request_key_rejected(self):
  self.write(self.request_file,self.request);data=self.request_file.read_text().rstrip();data=data[:-1]+',"schema":"other"}';self.request_file.write_text(data)
  with self.assertRaises(ValueError):m.execute(self.request_file,m.pin(self.request_file)['sha256'])
 def test_linked_repository_directory_rejected(self):
  actual=self.repo/'actual';self.ext.rename(actual);self.ext.symlink_to(actual,target_is_directory=True)
  with self.assertRaises(ValueError):m.repository_map(self.repo)
 def test_delta_duplicate_change_rejected(self):
  self.delta['changes'][-1]=self.delta['changes'][0];self.write(self.delta_file,self.delta);self.request['source_delta']=m.pin(self.delta_file);r=self.run_helper();self.assertFalse(r['passed']);self.assertFalse(self.calls)

if __name__=='__main__':unittest.main()
