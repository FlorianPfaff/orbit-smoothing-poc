import importlib.util,os
from pathlib import Path
p=Path(__file__).with_name('capture_campaign_live03.py');s=importlib.util.spec_from_file_location('snap',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_environment_is_allowlisted():
 assert m.filtered_environment(b'HOME=/x\0SECRET=hidden\0OMP_NUM_THREADS=1\0TOKEN=secret\0')=={'HOME':'/x','OMP_NUM_THREADS':'1'}
def test_values_can_contain_equals():
 assert m.filtered_environment(b'HOME=/x=y\0INVALID\0')=={'HOME':'/x=y'}
def test_lock_exact_device_and_inode():
 text='1: FLOCK ADVISORY WRITE 123 08:00:41 0 EOF\n2: FLOCK ADVISORY WRITE 456 08:01:41 0 EOF\n3: -> FLOCK ADVISORY WRITE 789 08:00:41 0 EOF'
 rows=m.lock_records(text,os.makedev(8,0),41);assert [r['owner_pid'] for r in rows]==[123,789] and rows[1]['waiting']
def test_reused_pid_is_not_same():
 assert not m.same_identity({'pid':4,'start_ticks':8},{'pid':4,'start_ticks':9})
def test_zombie_is_not_live():
 assert not m.live_identity({'state':'Z'}) and not m.live_identity(None) and m.live_identity({'state':'S'})
def test_absent_optional_receipt(tmp_path):
 assert m.json_file(tmp_path/'none')['present'] is False
def test_no_arbitrary_env_in_output(tmp_path):
 import ast
 source=ast.parse(p.read_text())
 assert not any(isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr in {'kill','killpg','sched_setaffinity','Popen','run'} for x in ast.walk(source))

def test_large_request_content_excluded():
 assert m.pin_only({'path':'/x','sha256':'a','content':{'private':'not exported'}})=={'path':'/x','sha256':'a'}
