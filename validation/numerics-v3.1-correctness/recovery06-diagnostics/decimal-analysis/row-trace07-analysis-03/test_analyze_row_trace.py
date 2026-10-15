import importlib.util
import json
from decimal import Decimal, localcontext
from pathlib import Path
import struct
import sys

import pytest

spec = importlib.util.spec_from_file_location("independent_row_arithmetic", Path(__file__).with_name("analyze_row_trace.py"))
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)
D = Decimal


def record(stage, value, row=5, index=0, component="", event=1, phase="linearization", evaluation=1, kind="double"):
    value = value if isinstance(value, D) else D.from_float(float(value))
    return audit.Record("row-trace-100.tsv", event, "/trace-on/qr.1", phase, D(0), (0, 13, 30), row,
                        component, stage, kind, index, value, "-", evaluation, event, "0")


def complete_equation(phase="linearization", evaluation=1, stec=3.0):
    rows = []
    def put(stage, value, row=5, index=0, component="", kind="double"):
        rows.append(record(stage, value, row, index, component, len(rows)+1, phase, evaluation, kind))
    put("observed", 2e7)
    put("range_twofold_high", D(10), kind="long_double")
    put("range_twofold_low", D("1e-18"), kind="long_double")
    put("range_narrowed", 10)
    for stage in ["receiver_clock_seconds", "transmitter_clock_seconds"]:
        put(stage, 0, 0)
    put("transmitter_scale", 1, 0)
    for component, native in [("receiver", 1.25), ("transmitter", 0.5)]:
        put("signal_bias_operand", native, 5, 0, component)
        put("antenna_pattern_operand", 0, 5, 0, component)
        put(component+"_antenna_operand", native, 5, 0, component)
    put("signal_composition", 1, 5, 5)
    put("after_receiver_antenna", 8.75)
    put("transmitter_composed_operand", 0.5)
    put("after_transmitter_antenna", 8.25)
    put("ambiguity_native_coordinates", 2, 0)
    put("ambiguity_composition", 1, 2, 0)
    put("ambiguity_type_mapping", 2)
    put("ambiguity_operand", 2)
    put("after_ambiguity", 6.25)
    put("STEC", stec, 0)
    put("dSTEC", .1, 0)
    put("sigmaSTEC", 40, 0)
    for stage in ["apply1stOrder", "apply2ndOrder", "apply3rdOrder", "applyBending"]:
        put(stage, 1, 0)
    primitives = {key: D.from_float(value) for key, value in
                  {"f2":16.,"f3":64.,"f4":256.,"Ap":2.,"s":3.,"r":4.,"bending":.5}.items()}
    for name, value in primitives.items():
        put("ionosphere_"+name, value)
    native = D("6.25")
    for number in range(1, 5):
        _, _, product = audit.stored_stec_term(number, primitives, D.from_float(stec))
        put(f"stec_operation_{number}_before", native)
        native = audit.rounded64(native-product)
        put(f"stec_operation_{number}_after", native)
    put("before_homogenize", native)
    put("homogenize_sigma", .003)
    put("after_homogenize", audit.rounded64(native * audit.rounded64(D(1)/D.from_float(.003))))
    put("retained_original_rows", audit.rounded64(native * audit.rounded64(D(1)/D.from_float(.003))))
    put("STEC_prior_row", audit.rounded64(-D.from_float(.1)/40), 7)
    return rows


@pytest.mark.parametrize("text,expected", [("-0x0p+0", D("-0")), ("0x1p+0", D(1)),
                                         ("0xa.000000000000001p-3", D("1.250000000000000000108420217248550443400745280086994171142578125")),
                                         ("0x1p-1074", D.from_float(float.fromhex("0x1p-1074")))])
def test_exact_hex(text, expected):
    value = audit.exact_hex(text)
    assert value == expected
    assert value.is_signed() == expected.is_signed()


@pytest.mark.parametrize("text", ["nan", "inf", "1.0", "0x1p-20001"])
def test_reject_invalid_hex(text):
    with pytest.raises(ValueError):
        audit.exact_hex(text)


def line(value=-0.0, event=1, kind="double", bits=None):
    if bits is None:
        bits = struct.pack(">d", value).hex()
    return "\t".join(["/trace-on/qr.1","trial","0x1p-1","0","13","30","5","receiver","observed",kind,"0",value.hex(),bits,"7",str(event),"0"])+"\n"


def test_parse_exact_bits_and_events(tmp_path):
    path = tmp_path/"row-trace-100.tsv"
    path.write_text(line()+line(float.fromhex("0x1p-1074"), 2))
    result = audit.parse_trace(path)
    assert result[0].value.is_signed()
    assert result[1].value == D.from_float(float.fromhex("0x1p-1074"))


@pytest.mark.parametrize("text", [line(bits="0000000000000000"), line(1., bits="4000000000000000"), line()+line(event=1), line().replace("\t13\t", "\t999\t")])
def test_parse_rejects_corruption(tmp_path, text):
    path = tmp_path/"row-trace-100.tsv"; path.write_text(text)
    with pytest.raises(ValueError):
        audit.parse_trace(path)


def test_complete_chain_and_native_replay():
    with localcontext() as context:
        context.prec = audit.PRECISION
        result = audit.analyze_equation(complete_equation())
    assert result["complete"], result
    assert result["native_replay_all_match"]
    assert D(result["stages"][0]["observed_minus_precise"]) == D("-1e-18")
    assert result["stec_prior"]["stage"] == "STEC_prior_row"
    assert len(result["stec_operations"]) == 4


def test_missing_or_duplicate_operand_fails_closed():
    for transform in [lambda rows: [r for r in rows if r.stage != "ambiguity_composition"],
                      lambda rows: rows+[next(r for r in rows if r.stage == "signal_composition")]]:
        result = audit.analyze_equation(transform(complete_equation()))
        assert not result["complete"]
        assert result["unavailable_reason"]


def test_unknown_nonzero_model_fails_closed():
    rows = complete_equation()+[record("before_model:UnknownModel", 1), record("after_model:UnknownModel", 2)]
    result = audit.analyze_equation(rows)
    assert not result["complete"]
    assert "Unreconstructed" in result["unavailable_reason"]


def test_separate_evaluations_and_equation_repeats():
    rows = [record("observed", 1,event=1), record("range_narrowed", 1,event=2),
            record("observed", 2,event=3), record("range_narrowed", 2,event=4),
            record("observed", 3,event=5,evaluation=2)]
    groups = audit.segments(rows)
    assert [len(group) for group in groups] == [2,2,1]


def test_explicit_local_update_rounding():
    rows = [record("local_STEC_before", 2**53,row=0,event=1),
            record("local_dSTEC_before", 1,row=0,event=2),
            record("local_STEC_delta", 1,row=0,event=3),
            record("local_STEC_after", 2**53,row=0,event=4),
            record("local_dSTEC_after", 2,row=0,event=5)]
    result = audit.update_checks(rows)
    assert result[0]["stored_minus_ideal"] == "-1"
    assert result[0]["native_rounding_match"]
    assert result[1]["stored_minus_ideal"] == "0"


def test_vtec_shadow_update_preserves_stored_state_distinction():
    values = {"STEC_before": 2**53, "delta":1,"gradient_x_delta":0,"gradient_y_delta":0,
              "elevation":1,"azimuth":0,"STEC_after":2**53,"mapping_shadow":1,"cos_shadow":1,"sin_shadow":0}
    rows = [record("VTEC_"+stage,value,row=0,event=i+1) for i,(stage,value) in enumerate(values.items())]
    result = audit.update_checks(rows)[0]
    assert result["stored_minus_ideal"] == "-1"
    assert result["native_separate_operations_match"]


def test_paired_rows_uses_stored_state_precision_not_ideal_update():
    with localcontext() as context:
        context.prec = audit.PRECISION
        base = audit.analyze_equation(complete_equation())
        trial = audit.analyze_equation(complete_equation("trial", 2, 3.000000000000001))
        result = audit.paired_rows([base, trial])[0]
        b, t = (D(x["precise_weighted_row_at_stored_state"]) for x in (base, trial))
        assert D(result["precise_row_actual_reduction_at_stored_states"]) == (b-t)*(b+t)/2
        duplicate = audit.paired_rows([base, base, trial])[0]
        assert duplicate["unavailable_reason"] == "Need one baseline; found 2"


def test_equivalence_missing_or_empty_fails_closed(tmp_path):
    path = tmp_path/"equivalence.json"
    for data in [{"passed":False}, {"passed":True,"schema":"orbit-poc-diagnostic-row-trace-equivalence-v1","checks":[]}]:
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError):
            audit.analyze([],path)


def test_equivalence_tampered_artifact_fails_closed(tmp_path):
    raw = tmp_path/"rows.tsv"; raw.write_text("raw\n")
    identity = audit.artifact(raw)
    proof = tmp_path/"proof.json"
    proof.write_text(json.dumps({"passed":True,"schema":"orbit-poc-diagnostic-row-trace-equivalence-v1","checks":[{"files":[identity]}]}))
    raw.write_text("changed\n")
    with pytest.raises(ValueError, match="absent or changed"):
        audit.analyze([],proof)


def test_equivalence_binds_trace_stem_to_verified_on_directory(tmp_path):
    raw = tmp_path/"rows.tsv"; raw.write_text("raw\n")
    identity = audit.artifact(raw)
    proof = tmp_path/"proof.json"
    proof.write_text(json.dumps({"passed":True,"schema":"orbit-poc-diagnostic-row-trace-equivalence-v1",
                                "directories":["/original","/off","/different-on"],"checks":[{"files":[identity]}]}))
    trace = tmp_path/"row-trace-100.tsv"; trace.write_text(line())
    with pytest.raises(ValueError, match="outside verified"):
        audit.analyze([trace],proof)


@pytest.mark.parametrize("number,expected", [(5,D("0.375")), (6,D("0.140625")), (7,D("0.140625"))])
def test_code_stec_operations(number,expected):
    primitive = dict(Ap=D(2),s=D(3),r=D(4),bending=D('.5'),f2=D(16),f3=D(64),f4=D(256))
    _, precise, native = audit.stored_stec_term(number,primitive,D(3))
    assert precise == expected
    assert native == expected


def test_nearest_even_rounding_and_signed_zero():
    with localcontext() as context:
        context.prec=110
        assert audit.rounded64(D(1)+D(2)**-53)==1
        assert audit.rounded64(D(1)+D(3)*D(2)**-53)==D(1)+D(2)**-51
    assert audit.rounded64(D('-0')).is_signed()


def test_pairing_selects_retained_baseline_over_recovery_only_duplicate():
    with localcontext() as context:
        context.prec = audit.PRECISION
        baseline = audit.analyze_equation(complete_equation())
        recovery = audit.analyze_equation([r for r in complete_equation() if r.stage != "retained_original_rows"])
        trial = audit.analyze_equation(complete_equation("trial", 2, 3.000000000000001))
        assert recovery["complete"] and not recovery["has_retained_original_row"]
        result = audit.paired_rows([baseline,recovery,trial])[0]
        assert "unavailable_reason" not in result


def test_retained_original_row_mismatch_fails_closed():
    rows = [r for r in complete_equation() if r.stage != "retained_original_rows"]
    rows.append(record("retained_original_rows",123))
    result = audit.analyze_equation(rows)
    assert not result["complete"]
    assert "Retained original row disagrees" in result["unavailable_reason"]


def test_unretained_trial_cannot_be_paired():
    baseline = audit.analyze_equation(complete_equation())
    trial = audit.analyze_equation([r for r in complete_equation("trial",2) if r.stage != "retained_original_rows"])
    result = audit.paired_rows([baseline,trial])[0]
    assert result["unavailable_reason"] == "Trial equation does not carry a retained original row"


def test_transparent_nested_groups_are_validated():
    stages = [("before_model:24GnssParametrizationGroup", 10),
              ("before_model:24GnssParametrizationGroup", 10),
              ("before_model:34GnssParametrizationIonosphereSTEC", 10),
              ("after_model:34GnssParametrizationIonosphereSTEC", 11),
              ("after_model:24GnssParametrizationGroup", 11),
              ("before_model:UnknownZeroModel", 11),
              ("after_model:UnknownZeroModel", 11),
              ("after_model:24GnssParametrizationGroup", 11)]
    audit.validate_model_corrections([record(stage,value) for stage,value in stages], 5)


def test_group_cannot_hide_untraced_or_unknown_correction():
    for child_name, child_before, child_after in [("GnssParametrizationIonosphereSTEC",9,11),
                                                  ("UnknownNonzeroModel",10,11)]:
        rows = [record("before_model:GnssParametrizationGroup",10),
                record("before_model:"+child_name,child_before),
                record("after_model:"+child_name,child_after),
                record("after_model:GnssParametrizationGroup",11)]
        with pytest.raises(ValueError):
            audit.validate_model_corrections(rows,5)


def test_malformed_model_nesting_fails_closed():
    with pytest.raises(ValueError,match="Unbalanced"):
        audit.validate_model_corrections([record("before_model:A",1),record("after_model:B",1)],5)
    with pytest.raises(ValueError,match="Unclosed"):
        audit.validate_model_corrections([record("before_model:A",1)],5)


def test_only_explicit_initialization_context_is_excluded(tmp_path):
    raw=tmp_path/'raw'; raw.write_text('raw')
    proof=tmp_path/'proof.json'
    proof.write_text(json.dumps({'passed':True,'schema':'orbit-poc-diagnostic-row-trace-equivalence-v1',
                                'directories':['/original','/off','/trace-on'],
                                'checks':[{'files':[audit.artifact(raw)]}]}))
    trace=tmp_path/'row-trace-100.tsv'
    original=line(1.,event=1).split('\t')
    original[0]='';original[1]='unassigned';original[13]='0'
    trace.write_text('\t'.join(original)+line(1.,event=2))
    result=audit.analyze([trace],proof)
    assert result['record_count']==2
    assert result['excluded_initialization_record_count']==1
    assert result['fit_record_count']==1
    original[13]='1'
    trace.write_text('\t'.join(original)+line(1.,event=2))
    with pytest.raises(ValueError,match='outside verified'):
        audit.analyze([trace],proof)
