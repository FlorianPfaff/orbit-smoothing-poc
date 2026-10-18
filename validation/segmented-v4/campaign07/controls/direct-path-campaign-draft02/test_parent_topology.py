from pathlib import Path
import importlib.util
import os
import pytest

P=Path(__file__).with_name('with_completed_preparation_direct02.py')
spec=importlib.util.spec_from_file_location('parent_topology',P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_missing_final_targets_and_nested_roots(tmp_path):
    a=tmp_path/'outer';a.mkdir();b=a/'inner';b.mkdir()
    old=b/'old';old.write_text('preserved')
    pairs=[(str(old),str(a/'missing/deep/file')),(str(old),str(b/'missing_file'))]
    t=m.capture_topology(pairs)
    assert [x['directory']['path'] for x in t['roots']]==[str(a),str(b)]
    assert t['missing_parents']==[str(a/'missing'),str(a/'missing/deep')]
    args=m.topology_args(t)
    assert ['--ro-bind',str(b),str(b)] not in [args[i:i+3] for i in range(len(args)-2)]
    assert ['--dir',str(b)] in [args[i:i+2] for i in range(len(args)-1)]
    assert ['--ro-bind',str(old),str(old)] in [args[i:i+3] for i in range(len(args)-2)]
    assert not (a/'missing').exists() and not (b/'missing_file').exists()

def test_existing_targets_need_no_overlay(tmp_path):
    q=tmp_path/'old';q.write_text('x')
    assert m.capture_topology([(str(q),str(q))])['roots']==[]

def test_membership_identity_changes_detected(tmp_path):
    target=tmp_path/'absent';q=tmp_path/'original';q.write_text('x')
    pairs=[(str(q),str(target))];before=m.capture_topology(pairs)
    q.rename(tmp_path/'renamed')
    assert m.capture_topology(pairs)!=before

def test_mutable_file_size_is_not_topology(tmp_path):
    q=tmp_path/'original';q.write_text('x');pairs=[(str(q),str(tmp_path/'absent'))]
    before=m.capture_topology(pairs);q.write_text('new content')
    assert m.capture_topology(pairs)==before

def test_symlink_member_restored_as_link(tmp_path):
    q=tmp_path/'original';q.mkdir();link=tmp_path/'link';link.symlink_to('original')
    t=m.capture_topology([(str(q),str(tmp_path/'absent'))]);args=m.topology_args(t)
    assert ['--symlink','original',str(link)] in [args[i:i+3] for i in range(len(args)-2)]

def test_missing_target_below_symlink_parent_rejected(tmp_path):
    q=tmp_path/'original';q.mkdir();link=tmp_path/'link';link.symlink_to(q)
    with pytest.raises(RuntimeError,match='canonical'):m.capture_topology([(str(q),str(link/'absent'))])

def test_special_member_rejected(tmp_path):
    os.mkfifo(tmp_path/'pipe')
    with pytest.raises(RuntimeError,match='Unsupported'):m.capture_topology([('unused',str(tmp_path/'absent'))])

def test_root_overlay_rejected():
    with pytest.raises(RuntimeError,match='Unsupported alias parent'):m.capture_topology([('/tmp','/orbit-poc-parent-test-absent')])
