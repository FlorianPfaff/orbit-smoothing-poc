from pathlib import Path
import importlib.util,pytest
s=importlib.util.spec_from_file_location('rows',Path(__file__).with_name('audit_shifted_rows01.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def fixture(tmp_path):
 p=tmp_path/'input.rows';p.write_text('SEGMENTED_QR_V1\n2 1 2 2 0\n0 1 1 0\n1 0 1 1\n0 0 0 2 0 1 1 -1\n1 0 3 1 0 1\n2 1 4 1 1 1\n0 0 1 0\n1 1 0 1\n');return p
def test_independent_original_row_energy_and_equality(tmp_path):
 g=m.read(fixture(tmp_path));e,f=m.evaluate(g,{'variable_ids':[0,1],'step':[3.5,3.5]});assert e==0 and f==.5
 g['equalities'][0][3][1]=(1,-.5);assert m.evaluate(g,{'variable_ids':[0,1],'step':[3.5,3.5]})[0]==pytest.approx(1/3)
def test_ledger_identity_preserves_coefficients_but_not_group_order(tmp_path):
 g=m.read(fixture(tmp_path));i=m.identities(g);g['groups'].reverse();assert m.identities(g)==i;g['stochastic_text'][0]+='0';assert m.identities(g)!=i
@pytest.mark.parametrize('bad',['duplicate','missing','query'])
def test_parser_fail_closed(tmp_path,bad):
 p=fixture(tmp_path);s=p.read_text();s=s.replace('1 1 0 1','1 1 0 0') if bad=='duplicate' else s.replace('1 1 0 1\n','') if bad=='missing' else s+'1 0 1\n';p.write_text(s)
 with pytest.raises(AssertionError):m.read(p)
def test_variable_order_must_match_native_ids(tmp_path):
 p=fixture(tmp_path);p.write_text(p.read_text().replace('0 1 1 0','2 1 1 0'))
 with pytest.raises(AssertionError):m.read(p)
