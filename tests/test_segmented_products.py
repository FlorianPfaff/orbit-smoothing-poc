"""Product stitching is audited without changing any model or daily product."""
from datetime import datetime,timedelta
import gzip,json
from pathlib import Path

import numpy as np
import pytest

from orbit_poc.segmented.products import audit_daily_products,read_attitudes,ROLES
from orbit_poc.comparison.data import artifact
from test_comparison_data import _osb_file


def daily_inputs(root,*,compressed=False):
    start=datetime(2024,4,24);daily={role:[] for role in ROLES}
    for day in range(2):
        date=(start+timedelta(days=day)).date().isoformat()
        epochs=[start+timedelta(seconds=s) for s in ([86370,86400] if day==0 else [86400,86430])]
        for role in ROLES:
            path=root/(date+"-"+role)
            if role=="gnss_biases":_osb_file(path,[("C1C",1.+day),("L1C",4.+day)])
            else:
                rows=[]
                for time in epochs:
                    stamp=time.strftime("%Y %m %d %H %M %S.000000")
                    if role=="gnss_orbits":rows += ["*  "+stamp,"PG01"+"".join(f"{v:14.6f}" for v in (20000.+day,10000.,15000.,0.))]
                    if role=="gnss_clocks":rows += ["AS G01 "+stamp+f" 1 {day*1e-9:.12E}"]
                    if role=="gnss_attitudes":rows += ["## "+stamp+" 1",f"ATT G01 4 {1 if day==0 else -1} 0 0 0"]
                path.write_text("\n".join(rows)+"\n")
            if compressed:
                encoded=Path(str(path)+".gz")
                with gzip.open(encoded,"wb") as stream:stream.write(path.read_bytes())
                path=encoded
            daily[role].append(artifact(path,role,date=date))
    return daily


@pytest.mark.parametrize("compressed",[False,True])
def test_all_actual_overlaps_bias_changes_and_boundary_gaps_are_retained(tmp_path,compressed):
    inputs=daily_inputs(tmp_path,compressed=compressed)
    before={p["path"]:Path(p["path"]).read_bytes() for entries in inputs.values() for p in entries}
    result=audit_daily_products(inputs,tmp_path/"audit")
    summary=json.loads(Path(result["summary"]["path"]).read_text())
    events=[json.loads(x) for x in Path(result["events"]["path"]).read_text().splitlines()]
    assert summary["counts"]=={"overlap_disagreements":3,"boundary_sample_pairs":3,
                               "missing_boundary_sides":0,"satellite_membership_changes":0,"bias_changes":2,"overlap_samples":3}
    overlap=[x for x in events if x["kind"]=="same_epoch_product_disagreement"]
    assert next(x for x in overlap if x["role"]=="gnss_orbits")["position_difference_norm_m"]==1000.
    assert next(x for x in overlap if x["role"]=="gnss_clocks")["clock_difference_seconds"]==1e-9
    attitude=next(x for x in overlap if x["role"]=="gnss_attitudes")
    assert attitude["rotation_difference_rad"]==0. and attitude["quaternion_sign_equivalent"] is True
    assert all(x["sample_gap_seconds"]==30 for x in events if x["kind"]=="boundary_samples")
    assert all(x["applied_to_synthetic_data"] is False for x in events if x["kind"]=="daily_bias_change")
    assert summary["products_modified"] is False and summary["ambiguity_resets_inserted"] is False
    assert all(Path(path).read_bytes()==raw for path,raw in before.items())
    with pytest.raises(ValueError,match="Preserve"):
        audit_daily_products(inputs,tmp_path/"audit")


def test_audit_rejects_changed_product_bytes_and_mismatched_day_lists(tmp_path):
    inputs=daily_inputs(tmp_path)
    inputs["gnss_orbits"][1]["date"]="2024-04-26"
    with pytest.raises(ValueError,match="shared"):
        audit_daily_products(inputs,tmp_path/"dates")
    inputs["gnss_orbits"][1]["date"]="2024-04-25"
    Path(inputs["gnss_clocks"][0]["path"]).write_text("modified")
    with pytest.raises(ValueError,match="hash changed"):
        audit_daily_products(inputs,tmp_path/"bytes")


def test_invalid_or_repeated_product_epochs_are_not_hidden(tmp_path):
    inputs=daily_inputs(tmp_path)
    item=inputs["gnss_clocks"][0];path=Path(item["path"])
    path.write_text(path.read_text()+path.read_text().splitlines()[-1]+"\n")
    inputs["gnss_clocks"][0]=artifact(path,"gnss_clocks",date=item["date"])
    with pytest.raises(ValueError,match="unique"):
        audit_daily_products(inputs,tmp_path/"duplicate")
    assert (tmp_path/"duplicate/product-boundary-events.jsonl").exists()
    assert not (tmp_path/"duplicate/product-boundaries.json").exists()


def test_orbex_gps_quaternions_require_an_epoch_and_four_components(tmp_path):
    path=tmp_path/"invalid.obx";path.write_text("ATT G01 4 1 0 0 0\n")
    with pytest.raises(ValueError,match="quaternion"):
        read_attitudes(path)


def test_missing_midnight_side_is_explicit_in_audit(tmp_path):
    inputs=daily_inputs(tmp_path)
    item=inputs["gnss_clocks"][1];path=Path(item["path"])
    path.write_text(path.read_text().replace("2024 04 25", "2024 04 24"))
    inputs["gnss_clocks"][1]=artifact(path,"gnss_clocks",date=item["date"])
    result=audit_daily_products(inputs,tmp_path/"coverage")
    summary=json.loads(Path(result["summary"]["path"]).read_text())
    events=[json.loads(x) for x in Path(result["events"]["path"]).read_text().splitlines()]
    missing=[x for x in events if x["kind"]=="boundary_samples_unavailable"]
    assert summary["counts"]["missing_boundary_sides"]==1 and len(missing)==1
    assert missing[0]["earlier_side_available"] is True and missing[0]["later_side_available"] is False
    assert "Native-selected GPS OSB" in summary["bias_audit_scope"]
