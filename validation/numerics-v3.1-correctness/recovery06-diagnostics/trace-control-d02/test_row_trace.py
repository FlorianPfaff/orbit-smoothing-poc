"""Small diagnostic lifecycle/representation fixtures; no orbit fits or builds."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import textwrap

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("trace_installer", HERE / "install_row_trace.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
spec2 = importlib.util.spec_from_file_location("trace_equivalence", HERE / "verify_trace_equivalence.py")
equivalence = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(equivalence)


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("row-trace-probe")
    source = directory / "probe.cpp"
    source.write_text(r'''
#include "rowArithmeticTrace.h"
#include <sys/wait.h>
#include <iostream>
#include <vector>
struct Matrix {
  size_t rows()const{return 2;}size_t columns()const{return 2;}
  double operator()(size_t i,size_t j)const{return 10*i+j;}
};
struct Vector: public Matrix {
  std::vector<double> data;static int copies;
  Vector(std::initializer_list<double> x):data(x){}
  Vector(const Vector &x):data(x.data){copies++;}
  size_t rows()const{return data.size();}size_t columns()const{return 1;}
  // Match GROOPS exactly: this overload hides Matrix::operator()(row,column).
  double operator()(size_t i)const{return data.at(i);}
};
int Vector::copies=0;
int main(int argc,char **argv){
  const std::string mode=argv[1];
  orbitPocTrace::begin("/frozen/point/qr.8","trial",0x1p-16);
  orbitPocTrace::Equation scope(0,9,113);orbitPocTrace::row(5);
  if(mode=="simple"){
    orbitPocTrace::selected("negative_zero",-0.0);
    orbitPocTrace::selected("subnormal",std::numeric_limits<double>::denorm_min());
    orbitPocTrace::selectedExtended("low_part",0x1p-100L);
    Vector x{0,1,2,3,4,5.25};
    const auto &y=orbitPocTrace::operand("operand",x);
    if(&x!=&y||Vector::copies)return 3;
  }else if(mode=="filter"){
    orbitPocTrace::row(4);orbitPocTrace::selected("excluded",1.);
    orbitPocTrace::Equation nested(1,9,113);orbitPocTrace::row(5);orbitPocTrace::selected("excluded",2.);
  }else if(mode=="restore"){
    {orbitPocTrace::Equation nested(1,9,113);orbitPocTrace::row(0);}
    orbitPocTrace::selected("restored",3.);
  }else if(mode=="environment"){
    errno=EDOM;std::feraiseexcept(FE_INVALID);const int before=std::fetestexcept(FE_ALL_EXCEPT);
    orbitPocTrace::selected("env",1.2345678901234567);
    if(errno!=EDOM||std::fetestexcept(FE_ALL_EXCEPT)!=before)return 4;
  }else if(mode=="fork"){
    orbitPocTrace::selected("parent",1.);
    const auto pid=fork();if(pid<0)return 5;
    if(!pid){orbitPocTrace::selected("child",2.);_exit(0);}
    int status;waitpid(pid,&status,0);if(status)return 6;
  }else if(mode=="registry"){
    int object;orbitPocTrace::registerObservation(&object,0,9,113);
    {orbitPocTrace::Observation entry(&object);orbitPocTrace::scalar("registered",4.,0);}
    int unknown;{orbitPocTrace::Observation entry(&unknown);orbitPocTrace::scalar("unknown",5.,0);}
  }else if(mode=="blocks"){
    unsigned long long cases[][3]={{13,30,5},{4,115,1},{16,8,4},{9,114,4},{9,113,5}};
    for(const auto &c:cases){orbitPocTrace::Equation selected(0,c[0],c[1]);orbitPocTrace::row(c[2]);orbitPocTrace::selected("selected",1.);}
  }else if(mode=="operands"){
    Vector x{0,1,2,3,4,5.25};orbitPocTrace::allVector("all",x);
    orbitPocTrace::array("array",x.data);
  }else if(mode=="matrix"){
    Matrix x;orbitPocTrace::allVector("matrix",x);
    if(orbitPocTrace::element(x,1,1,0)!=11)return 8;
  }else if(mode=="wrong_vector_column"){
    Vector x{0,1};
    try{(void)orbitPocTrace::element(x,0,1,0);return 9;}
    catch(const std::runtime_error &error){if(std::string(error.what()).find("multiple columns")==std::string::npos)return 10;}
  }else return 7;
  return 0;
}
''')
    binary = directory / "probe"
    subprocess.run(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-I", str(HERE), str(source), "-o", str(binary)], check=True, capture_output=True, text=True)
    return binary


def run(probe, directory, mode, enabled=True):
    env = os.environ.copy()
    env.pop("ORBIT_POC_ROW_TRACE_DIRECTORY", None)
    if enabled:
        env["ORBIT_POC_ROW_TRACE_DIRECTORY"] = str(directory)
    result = subprocess.run([str(probe), mode], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    files = sorted(directory.glob("row-trace-*.tsv"))
    rows = [line.split("\t") for file in files for line in file.read_text().splitlines()]
    assert all(len(row) == 16 for row in rows)
    return files, rows


def test_disabled_does_not_write(probe, tmp_path):
    assert run(probe, tmp_path, "simple", False) == ([], [])


def test_native_double_and_extended_bits(probe, tmp_path):
    files, rows = run(probe, tmp_path, "simple")
    assert len(files) == 1
    values = {row[8]: row for row in rows}
    assert values["negative_zero"][12] == "8000000000000000"
    assert values["subnormal"][12] == "0000000000000001"
    assert float.fromhex(values["low_part"][11]) == 2.0 ** -100
    assert values["low_part"][12] == "-"
    assert values["operand"][12] == struct.pack(">d", 5.25).hex()
    assert all(row[0:3] == ["/frozen/point/qr.8", "trial", "0x1p-16"] for row in rows)


def test_unselected_rows_and_receivers_do_not_write(probe, tmp_path):
    assert run(probe, tmp_path, "filter") == ([], [])


def test_equation_scope_restores_selected_context(probe, tmp_path):
    _, rows = run(probe, tmp_path, "restore")
    assert [r[8] for r in rows] == ["restored"]


def test_formatter_preserves_floating_environment_and_errno(probe, tmp_path):
    _, rows = run(probe, tmp_path, "environment")
    assert len(rows) == 1


def test_fork_child_opens_distinct_owned_file(probe, tmp_path):
    files, rows = run(probe, tmp_path, "fork")
    assert len(files) == 2
    assert {r[8] for r in rows} == {"parent", "child"}


def test_registered_local_observation_and_unknown_pointer(probe, tmp_path):
    _, rows = run(probe, tmp_path, "registry")
    assert [r[8] for r in rows] == ["registered"]
    assert rows[0][3:6] == ["0", "9", "113"]


def test_exact_five_approved_row_filters(probe, tmp_path):
    _, rows = run(probe, tmp_path, "blocks")
    assert {(int(r[4]), int(r[5]), int(r[6])) for r in rows} == {(13,30,5),(4,115,1),(16,8,4),(9,114,4),(9,113,5)}


def test_raw_operand_vectors_keep_all_components(probe, tmp_path):
    _, rows = run(probe, tmp_path, "operands")
    assert len(rows) == 12


def test_native_hidden_vector_overload_and_true_matrix_access(probe, tmp_path):
    _, rows=run(probe,tmp_path,"matrix")
    assert {(int(r[6]),int(r[10]),float.fromhex(r[11])) for r in rows} == {(0,0,0.0),(0,1,1.0),(1,0,10.0),(1,1,11.0)}


def test_vector_fallback_rejects_nonzero_column(probe,tmp_path):
    assert run(probe,tmp_path,"wrong_vector_column") == ([],[])


def test_original_direct_accessor_fails_with_native_hidden_overload(tmp_path):
    source=tmp_path / "old_accessor.cpp"
    source.write_text('''
#include <cstddef>
struct Matrix {double operator()(std::size_t,std::size_t)const{return 0;}};
struct Vector: public Matrix {double operator()(std::size_t)const{return 0;}};
template<class V> double old_accessor(const V &value){return value(0,0);}
int main(){Vector value;return old_accessor(value);}
''')
    result=subprocess.run(["g++","-std=c++17","-fsyntax-only",str(source)],text=True,capture_output=True)
    assert result.returncode!=0
    assert "no match for call" in result.stderr


def test_invalid_directory_fails_closed(probe, tmp_path):
    env = dict(os.environ, ORBIT_POC_ROW_TRACE_DIRECTORY=str(tmp_path / "missing"))
    result = subprocess.run([str(probe), "simple"], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "must already exist" in result.stderr


def test_unique_anchor_rejects_missing_or_duplicate():
    for content in ["", "anchoranchor"]:
        with pytest.raises(ValueError, match="exactly one"):
            installer.replace_once(content, "anchor", "new")


def test_unique_anchor_preserves_surrounding_bytes():
    assert installer.replace_once("before\nanchor\nafter\n", "anchor", "new") == "before\nnew\nafter\n"


def test_installer_validates_all_anchors_before_writes(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    (tree / "source").mkdir(parents=True)
    def fail(_):
        raise ValueError("late anchor failure")
    monkeypatch.setattr(installer, "patched_files", fail)
    with pytest.raises(ValueError, match="late anchor"):
        installer.install(tree, tmp_path / "receipt.json")
    assert list((tree / "source").iterdir()) == []


def test_installer_pins_before_after_and_refuses_repeat(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    source = tree / "source"
    (source / "misc/orbitPoc").mkdir(parents=True)
    (source / "one.cpp").write_text("before")
    monkeypatch.setattr(installer, "patched_files", lambda _: {"one.cpp": "after"})
    receipt = tmp_path / "receipt.json"
    result = installer.install(tree, receipt)
    assert result["files"]["one.cpp"] == {"before":installer.digest(b"before"), "after":installer.digest(b"after")}
    assert result["diagnostic_only"] is True
    assert json.loads(receipt.read_text()) == result
    with pytest.raises(ValueError, match="already exists"):
        installer.install(tree, receipt)


@pytest.fixture
def replays(tmp_path):
    roots = [tmp_path / name for name in ["reference","off","on"]]
    for root in roots:
        root.mkdir()
        for suffix in equivalence.EXACT_SUFFIXES:
            (root / f"qr.1.{suffix}").write_bytes(b"same bytes\n")
        (root / "qr.1.rows.tsv").write_bytes(b"original row\n")
        (root / "qr.1.factor.json").write_text(json.dumps({"spool_directory":str(root / "spool"),"scales":[1.0],"orthogonal_energy":3.0}))
        (root / "qr.1.nuisance_line_search.json").write_text(json.dumps({"accepted":False,"full_step_prediction":1e-16,"trials":[{"cost":4.0,"child_user_seconds":float(len(str(root))),"peak_child_rss_bytes":100}]}))
    return roots


def test_exact_equivalence_excludes_only_declared_operational_fields(replays):
    assert equivalence.verify(replays,1)["passed"]


@pytest.mark.parametrize("name", ["R.bin","z.bin","delta.tsv","parameters.tsv","profile.json","nuisance_coordinates.tsv"])
def test_equivalence_rejects_changed_numerical_bytes(replays, name):
    (replays[-1] / f"qr.1.{name}").write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="Numerical bytes differ"):
        equivalence.verify(replays,1)


def test_equivalence_rejects_changed_trial_reduction(replays):
    path = replays[-1] / "qr.1.nuisance_line_search.json"
    value=json.loads(path.read_text());value["full_step_prediction"]=2e-16;path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Numerical metadata differ"):
        equivalence.verify(replays,1)


def test_equivalence_rejects_changed_factor_scale(replays):
    path = replays[-1] / "qr.1.factor.json"
    value=json.loads(path.read_text());value["scales"]=[2.0];path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Numerical metadata differ"):
        equivalence.verify(replays,1)


def test_equivalence_accepts_lossless_row_compression(replays):
    import gzip
    path=replays[-1] / "qr.1.rows.tsv"
    path.with_suffix(".tsv.gz").write_bytes(gzip.compress(path.read_bytes()));path.unlink()
    assert equivalence.verify(replays,1)["passed"]


def test_equivalence_rejects_row_and_generation_changes(replays):
    (replays[-1] / "qr.1.rows.tsv").write_bytes(b"changed row\n")
    with pytest.raises(ValueError, match="Original observation rows differ"):
        equivalence.verify(replays,1)
    with pytest.raises(ValueError, match="Unexpected or missing replay generations"):
        equivalence.verify(replays,2)


def test_original_factor_retention_receipt_is_checked(replays):
    root=replays[0];path=root / "qr.1.R.bin"
    path.write_bytes(b"original binary bytes longer than header")
    identity=equivalence.artifact(path)
    value={"schema":"orbit-poc-native-factor-retention-v1","status":"completed","artifacts":[dict(identity,role="superseded_triangular_factor")]}
    receipt=root / "qr.1.retention.json";receipt.write_text(json.dumps(value));path.unlink()
    meta=root / "qr.1.factor.json";metadata=json.loads(meta.read_text());metadata["keep_intermediate_factors"]=False;meta.write_text(json.dumps(metadata))
    assert equivalence.factor_identity(root,1,"R.bin",2)["sha256"] == identity["sha256"]
    with pytest.raises(ValueError,match="absent"):
        equivalence.factor_identity(root,1,"R.bin",1)
    value["artifacts"][0]["path"]="/different/qr.1.R.bin";receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError,match="wrong retired-factor"):
        equivalence.factor_identity(root,1,"R.bin",2)


def test_retired_factor_requires_matching_false_retention_policy(replays):
    root=replays[0];path=root / "qr.1.R.bin";path.write_bytes(b"original binary bytes longer than header")
    identity=equivalence.artifact(path)
    (root / "qr.1.retention.json").write_text(json.dumps({"schema":"orbit-poc-native-factor-retention-v1","status":"completed","artifacts":[dict(identity,role="superseded_triangular_factor")]}));path.unlink()
    with pytest.raises(ValueError,match="retention policy"):
        equivalence.factor_identity(root,1,"R.bin",2)
