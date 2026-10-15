from pathlib import Path
import importlib.util
import xml.etree.ElementTree as ET
import pytest
C=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('partial',C/'audit_terminal09_partial_independent.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
RAW=(C.parent/'remote-recovery-09-terminal-01/validation-09/native-tests.xml').read_bytes()
def test_actual_junit():
 r=m.junit(ET.fromstring(RAW));assert (r['passed'],r['failures'],r['skipped'])==(104,2,0)
@pytest.mark.parametrize('kind',['duplicate','missing','skip','extra_failure','wrong_name','wrong_message','wrong_total'])
def test_reject_changed_evidence(kind):
 root=ET.fromstring(RAW);suite=next(root.iter('testsuite'));cases=list(root.iter('testcase'));failed=next(c for c in cases if c.find('failure') is not None);passed=next(c for c in cases if c.find('failure') is None)
 if kind=='duplicate':passed.set('classname',failed.get('classname'));passed.set('name',failed.get('name'))
 elif kind=='missing':suite.remove(passed)
 elif kind=='skip':ET.SubElement(passed,'skipped')
 elif kind=='extra_failure':ET.SubElement(passed,'failure')
 elif kind=='wrong_name':failed.set('name','unexpected')
 elif kind=='wrong_message':failed.find('failure').set('message','unexpected')
 elif kind=='wrong_total':suite.set('tests','105')
 with pytest.raises(AssertionError):m.junit(root)
