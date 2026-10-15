#!/usr/bin/env python3
"""Seal a bounded independent summary of the verified D02 diagnostic trace."""
from pathlib import Path
from decimal import Decimal as D, localcontext
from datetime import datetime, timezone
import hashlib
import json
from collections import Counter

BASE = Path(__file__).parent


def artifact(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def main():
    source = BASE / "row-trace07-analysis-03/analyze_row_trace.py"
    actual_path = BASE / "row-trace-d02-decimal-actual-01.json"
    search_path = BASE / "row-trace-d02-generation8-line-search.json"
    assert artifact(source)["sha256"] == "70f6647197ed0850c66d9382cdece5c5eac9677c12d35534e7ff5dc542cd8bc8"
    assert artifact(actual_path)["sha256"] == "bbc92c1e4b9d057c17948e59aefdb588c36f12ac8dbf3ccc8681aca7f0a94db4"
    data, search = json.loads(actual_path.read_text()), json.loads(search_path.read_text())
    assert data["equivalence_receipt"]["sha256"] == "c375380bd4d5984b51065cabfec078b9125bcc57ef74325f16520d6c655c8bf9"
    equations = data["equations"]
    assert all(eq["complete"] and eq["native_replay_all_match"] for eq in equations)
    assert all(update.get("native_rounding_match", update.get("native_separate_operations_match", False)) for update in data["updates"])
    assert all("unavailable_reason" not in pair for pair in data["paired_selected_rows"])
    maxima = {}
    for equation in equations:
        for stage in equation["stages"] + equation["stec_operations"]:
            error = abs(D(stage["observed_minus_precise"]))
            if stage["stage"] not in maxima or error > D(maxima[stage["stage"]]["absolute_error"]):
                maxima[stage["stage"]] = {"absolute_error": str(error), **{key: equation[key] for key in
                                          ("file", "stem", "evaluation", "phase", "alpha", "block", "row")}}
    chosen = next(pair for pair in data["paired_selected_rows"] if pair["stem"].endswith(".8") and
                  pair["audit_mode"] == "0" and pair["alpha"] == "0.03125" and pair["block"] == [0,9,113])
    baseline = next(eq for eq in equations if eq["stem"] == chosen["stem"] and eq["phase"] == "linearization"
                    and eq["has_retained_original_row"] and eq["block"] == chosen["block"])
    trial = next(eq for eq in equations if eq["file"] == chosen["file"] and eq["evaluation"] == chosen["evaluation"]
                 and eq["block"] == chosen["block"])
    baseline_stages = {stage["stage"]: stage for stage in baseline["stages"] + baseline["stec_operations"]}
    trial_stages = {stage["stage"]: stage for stage in trial["stages"] + trial["stec_operations"]}
    selected_stages = ["range_narrowed", "after_receiver_antenna", "after_transmitter_antenna", "ambiguity_operand",
                       "after_ambiguity", "stec_operation_1_after", "stec_operation_2_after", "stec_operation_3_after",
                       "stec_operation_4_after", "before_homogenize", "after_homogenize"]
    stage_changes = []
    for stage in selected_stages:
        before = D(baseline_stages[stage]["observed_minus_precise"])
        after = D(trial_stages[stage]["observed_minus_precise"])
        stage_changes.append({"stage": stage, "baseline_native_minus_precise": str(before),
                              "trial_native_minus_precise": str(after), "error_change": str(after-before)})
    update_maxima = {}
    for update in data["updates"]:
        state = update["state"]
        if state not in update_maxima or abs(D(update["stored_minus_ideal"])) > abs(D(update_maxima[state]["stored_minus_ideal"])):
            update_maxima[state] = update
    final_pairs = [pair for pair in data["paired_selected_rows"] if pair["stem"].endswith(".8") and pair["audit_mode"] == "0" and D(pair["alpha"]) > 0]
    sign_reversals = [pair for pair in final_pairs if D(pair["native_row_actual_reduction"]) * D(pair["precise_row_actual_reduction_at_stored_states"]) < 0]
    final_reduction_error = max(abs(D(pair["native_minus_precise_reduction"])) for pair in final_pairs)
    result = {"schema": "orbit-poc-row-trace-d02-independent-scientific-diagnostic-v1",
              "reviewer": "@AGENT_ROOT@/v31_recovery_review", "created_at": datetime.now(timezone.utc).isoformat(),
              "diagnostic_only": True, "scientific_status": "v3.1 correctness remains failed",
              "source": artifact(source), "analysis": artifact(actual_path), "generation8_search": artifact(search_path),
              "equivalence": data["equivalence_receipt"], "trace_file_count": len(data["trace_artifacts"]),
              "counts": {"all_records": data["record_count"], "excluded_initialization_records": data["excluded_initialization_record_count"],
                         "complete_equations": len(equations), "retained_equations": sum(eq["has_retained_original_row"] for eq in equations),
                         "paired_selected_rows": len(data["paired_selected_rows"]), "checked_updates": len(data["updates"]),
                         "native_arithmetic_replay_mismatches": 0, "final_ordinary_row_sign_reversals": len(sign_reversals)},
              "stage_maxima": maxima, "representative_row_sign_reversal": chosen,
              "representative_row_stage_error_changes": stage_changes,
              "maximum_update_rounding_by_state_TECU": update_maxima,
              "generation8": {"native_full_step_prediction": str(search["full_step_prediction"]),
                              "undamped_maximum_update_m": str(search["undamped_maximum_update_m"]),
                              "accepted": search["accepted"], "floor_limited": search["nuisance_floor_limited"],
                              "maximum_selected_row_reduction_error": str(final_reduction_error),
                              "sign_reversal_rows": sign_reversals},
              "conclusions": [
                  "Residual-evaluation rounding is directly demonstrated at fixed actual stored nuisance states; native arithmetic and observed stage values agree in every reconstructed case.",
                  "The representative row's ambiguity composition rounding changes by 2.51249526e-16 m between baseline and trial and dominates its accumulated residual-error swing. Retaining only the range low part would leave this demonstrated error.",
                  "A coherent high/low path through active antenna, signal-bias, ambiguity, STEC, weighting and original objective rows is justified as a numerical correction with unchanged statistical models and stored parameter states.",
                  "Five selected rows cannot prove that this correction restores descent or stationarity for the complete nuisance objective. The unchanged required correctness suite must be rerun after any source change.",
                  "Local STEC/VTEC stored-update rounding is measured separately; ideal clock, shared-bias and ambiguity update arithmetic is unavailable in this probe. No conclusion that parameter representability is negligible for the complete objective is justified.",
                  "No convergence tolerance, objective floor, covariance rule, observation support, weighting, gauge, scientific acceptance gate or production campaign is changed."],
              "execution": {"transport": "@WINDOWS_MOUNT@/Windows/System32/OpenSSH/ssh.exe gpuserver4090 python3 -",
                            "remote_writes": False, "native_fits_run_by_reviewer": 0,
                            "analyzer_tests": {"passed":34,"failed":0,"errors":0,"skipped":0},
                            "preserved_analysis_guard_failure": artifact(BASE / "row-trace-d02-decimal-execution-failed-02.json")}}
    output = BASE / "row-trace-d02-independent-summary-01.json"
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"output": artifact(output), "counts": result["counts"], "maximum_final_row_reduction_error": str(final_reduction_error)}, indent=2))


if __name__ == "__main__":
    with localcontext() as context:
        context.prec = 110
        main()
