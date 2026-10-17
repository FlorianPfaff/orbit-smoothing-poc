from pathlib import Path
import ast,base64,hashlib,importlib.util,json
import pytest
C=Path(__file__).parent
s=importlib.util.spec_from_file_location('strict_v7',C/'validation07_provenance03.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def test_exact_measured_original_log():
 p=C/'native-complete-original-ninja-log01.json'
 assert hashlib.sha256(p.read_bytes()).hexdigest()=='07ac52bc1bf9684d0fc5bed59996f97766c69dbedf44b200bec4baf6cf0b4490'
 row=json.loads(p.read_bytes())['logs'][0];b=base64.b64decode(row['base64'],validate=True)
 assert hashlib.sha256(b).hexdigest()==row['sha256']=='f0d7a525c88313a23d83a90f5b82e298dfe3b27e101de1162b84e13a95ecb844'
 assert len(b)==row['bytes'];records=m.ninja_records(b.decode())
 assert len(records)==665 and sum(k.endswith('.o')for k in records)==611 and 'groops'in records
 for target,entry in records.items():
  fields=entry['raw'].split('\t');assert len(fields)==5 and fields[3]==target
  assert entry['start_ms']==int(fields[0])and entry['end_ms']==int(fields[1])and entry['mtime']==int(fields[2])and entry['command_hash']==fields[4]

def test_only_measured_header_changed():
 old=(C/'validation07_provenance02.py').read_text();new=(C/'validation07_provenance03.py').read_text()
 assert new==old.replace("lines[0]=='# ninja log v5'","lines[0]=='# ninja log v7'")
 before=ast.parse(old);after=ast.parse(new)
 for a,b in zip(before.body,after.body):
  if isinstance(a,ast.FunctionDef)and a.name=='ninja_records':continue
  assert ast.dump(a)==ast.dump(b)

@pytest.mark.parametrize('header',['# ninja log v5','# ninja log v6','# ninja log v8','# ninja log v70',''])
def test_unknown_or_old_version_rejected(header):
 with pytest.raises(RuntimeError):m.ninja_records(header+'\n1\t2\t3\ta.o\tabc\n')

@pytest.mark.parametrize('row',['1\t2\t3\ta.o','1\t2\t3\ta.o\tabc\textra','-1\t2\t3\ta.o\tabc','2\t1\t3\ta.o\tabc','1\t2\t0\ta.o\tabc'])
def test_original_field_and_time_guards_retained(row):
 with pytest.raises(RuntimeError):m.ninja_records('# ninja log v7\n'+row+'\n')

def test_repeated_target_rejected():
 with pytest.raises(RuntimeError):m.ninja_records('# ninja log v7\n1\t2\t3\ta.o\tabc\n2\t3\t4\ta.o\tdef\n')
