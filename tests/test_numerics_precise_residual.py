"""Independent Decimal checks of coherent original GNSS residual arithmetic."""
from decimal import Decimal as D, localcontext
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/"groops/extension"


def load_installer():
    spec=importlib.util.spec_from_file_location("precise_residual_installer",EXT/"native_precise_residual.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture(scope="module")
def arithmetic(tmp_path_factory):
    compiler=shutil.which("c++")
    if compiler is None:pytest.fail("Precise residual checks require a C++ compiler")
    root=tmp_path_factory.mktemp("precise-residual");include=root/"misc/orbitPoc";include.mkdir(parents=True)
    for name in ["preciseObservationResidual.h","twofoldGeometry.h"]:shutil.copyfile(EXT/name,include/name)
    executable=root/"probe"
    subprocess.run([compiler,"-std=c++17","-O2","-fno-fast-math","-ffp-contract=off","-I",str(root),str(ROOT/"tests/fixtures/precise_residual_probe.cpp"),"-o",str(executable)],check=True,capture_output=True,text=True)
    return executable


def run_chain(arithmetic,inputs):
    text="".join(f"{state:.17g} {low}\n" for state,low in inputs)
    result=subprocess.run([str(arithmetic),"chain"],input=text,check=True,capture_output=True,text=True,timeout=10)
    return [list(map(D,line.split())) for line in result.stdout.splitlines()]


def decimal_reference(state,low):
    f=D.from_float
    value=D(10)+low-(f(.6037960671066858)+f(.0003141592653589793))
    value-=f(.25)*(f(.125)+f(.000021))+f(.75)*(f(.25)+f(-.000071))
    value-=f(.19029367279836487)*f(3.25)+f(.24421021342456825)*f(-2.125)
    coefficients=[-.16237244751199473,-.000123456789012345,-.000000134567890123,3.45678901234e-9]
    for index,coefficient in enumerate(coefficients):value-=f(coefficient)*state**(1 if index<2 else 2)
    return value*f(1./.003)


def test_complete_chain_matches_independent_decimal_at_native_inputs(arithmetic):
    inputs=[(state,low) for state in [.21878423306452444,.21878423306452444+1e-14,-.3477136290463035,0.,20.,1e-7] for low in ["-1e-18","0","1e-18"]]
    rows=run_chain(arithmetic,inputs)
    with localcontext() as context:
        context.prec=110
        for state,low,high,small,rounded,legacy,prior_high,prior_low in rows:
            expected=decimal_reference(state,low)
            assert abs(high+small-expected)<D("1e-28")
            assert rounded==D.from_float(float(expected))
            assert abs(prior_high+prior_low+state/D(40))<D("1e-33")
        assert max(abs(row[5]-decimal_reference(row[0],row[1])) for row in rows)>D("1e-13")


def test_sub_double_residual_changes_survive_until_objective_boundary(arithmetic):
    a,b=run_chain(arithmetic,[(.21878423306452444,"-1e-18"),(.21878423306452444,"1e-18")])
    with localcontext() as context:
        context.prec=110
        change=(b[2]+b[3])-(a[2]+a[3])
        expected=decimal_reference(b[0],b[1])-decimal_reference(a[0],a[1])
        assert change!=0 and abs(change-expected)<D("1e-28")
        assert a[5]==b[5]  # The former repeatedly narrowed path loses this change.


def test_original_row_validation_and_native_container_guards(arithmetic):
    result=subprocess.run([str(arithmetic),"guards"],check=True,capture_output=True,text=True,timeout=10)
    assert result.stdout.strip()=="12"


def test_installer_rejects_missing_or_duplicate_anchor():
    module=load_installer()
    for text in ["", "needle needle"]:
        with pytest.raises(ValueError,match="anchor mismatch"):module.once(text,"needle","replacement")


def fixture_tree(tmp_path,installed=False):
    module=load_installer()
    targets=["gnss/gnssObservation.h","gnss/gnssObservation.cpp","gnss/gnssTransceiver.h","gnss/gnssReceiver.h","gnss/gnssReceiver.cpp",
             "gnss/gnssParametrization/gnssParametrizationAmbiguities.h","gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp",
             "gnss/gnssParametrization/gnssParametrizationIonosphereSTEC.cpp","gnss/gnssParametrization/gnssParametrization.cpp",
             "gnss/gnssParametrization/gnssParametrizationTemporalBias.cpp","gnss/gnssParametrization/gnssParametrizationTroposphere.cpp"]
    for name in targets:
        path=tmp_path/"source"/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text((module.MARKER+"\n"+(module.PRECISE_CAPTURE+"\n" if name=="gnss/gnssObservation.cpp" else "")) if installed else "unmodified\n")
    include=tmp_path/"source/misc/orbitPoc";include.mkdir(parents=True)
    (include/"gnssRangeResidual.h").write_text("stableRangeResidualExpansion")
    return module,targets,include


def test_installer_checks_every_anchor_before_writing(tmp_path,monkeypatch):
    module,targets,include=fixture_tree(tmp_path)
    def broken(source):raise ValueError("last anchor failed")
    monkeypatch.setattr(module,"patches",broken)
    with pytest.raises(ValueError,match="last anchor"):module.apply(tmp_path)
    assert not (include/"preciseObservationResidual.h").exists()
    assert all((tmp_path/"source"/name).read_text()=="unmodified\n" for name in targets)


def test_installer_rejects_partial_or_changed_header_and_is_idempotent(tmp_path):
    module,targets,include=fixture_tree(tmp_path,installed=True)
    header=include/"preciseObservationResidual.h";header.write_bytes((EXT/header.name).read_bytes())
    before={p:p.read_bytes() for p in (tmp_path/"source").rglob("*") if p.is_file()}
    module.apply(tmp_path)
    assert all(p.read_bytes()==value for p,value in before.items())
    header.write_text("different")
    with pytest.raises(ValueError,match="header changed"):module.apply(tmp_path)
    (tmp_path/"source"/targets[0]).write_text("unmodified")
    with pytest.raises(ValueError,match="Partially"):module.apply(tmp_path)


def test_installer_requires_expansion_api_before_mutation(tmp_path):
    module,_,include=fixture_tree(tmp_path)
    (include/"gnssRangeResidual.h").write_text("old Double-only range")
    with pytest.raises(ValueError,match="expansion-return"):module.apply(tmp_path)
    assert not (include/"preciseObservationResidual.h").exists()


def test_legacy_range_api_remains_explicitly_once_rounded():
    text=(EXT/"gnssRangeResidual.h").read_text()
    assert "inline TwofoldGeometry stableRangeResidualExpansion(" in text
    assert "inline Double stableRangeResidual(" in text
    assert "static_cast<Double>(stableRangeResidualExpansion(" in text
    assert "receiverClock,transmitterClock,scale,receiverRemainder,transmitterRemainder).rounded());" in text


def test_measured_ambiguity_rounding_change_is_removed(arithmetic):
    records=json.loads((ROOT/"tests/fixtures/precise_residual_ambiguity.json").read_text())
    inputs=[];references=[];native=[]
    with localcontext() as context:
        context.prec=110
        for record in records:
            assert record["block"]==[0,9,113]
            operands={(item["stage"],item["row"],item["index"]):float.fromhex(item["hex"]) for item in record["operands"]}
            matrix=[operands[("ambiguity_composition",i,j)] for i in range(2) for j in range(2)]
            state=[operands[("ambiguity_native_coordinates",i,0)] for i in range(2)]
            assert operands[("ambiguity_type_mapping",5,0)]==1
            inputs.append(" ".join(format(value,".17g") for value in matrix+state)+"\n")
            references.append(sum(D.from_float(matrix[2+j])*D.from_float(state[j]) for j in range(2)))
            native.append(D.from_float(operands[("ambiguity_operand",5,0)]))
        result=subprocess.run([str(arithmetic),"ambiguity"],input="".join(inputs),check=True,capture_output=True,text=True,timeout=10)
        precise=[sum(map(D,line.split())) for line in result.stdout.splitlines()]
        assert len(precise)==2
        assert all(abs(actual-expected)<D("1e-35") for actual,expected in zip(precise,references))
        true_change=references[1]-references[0]
        assert abs((precise[1]-precise[0])-true_change)<D("1e-35")
        # Actual failed-fit operands expose a 0.25 femtometre rounding change.
        assert D("2.51e-16")<abs((native[1]-native[0])-true_change)<D("2.52e-16")


def test_repeated_complete_install_removes_only_reintroduced_legacy_capture(tmp_path):
    module,_,include=fixture_tree(tmp_path,installed=True)
    (include/"preciseObservationResidual.h").write_bytes((EXT/"preciseObservationResidual.h").read_bytes())
    observation=tmp_path/"source/gnss/gnssObservation.cpp"
    original=observation.read_text()
    observation.write_text(original+module.LEGACY_CAPTURE+"\n")
    module.apply(tmp_path)
    assert observation.read_text()==original
    module.apply(tmp_path)
    assert observation.read_text()==original
    observation.write_text(original+module.LEGACY_CAPTURE+"\n"+module.LEGACY_CAPTURE+"\n")
    with pytest.raises(ValueError,match="capture changed"):module.apply(tmp_path)
    observation.write_text(module.MARKER+"\n"+module.LEGACY_CAPTURE+"\n")
    with pytest.raises(ValueError,match="capture changed"):module.apply(tmp_path)
