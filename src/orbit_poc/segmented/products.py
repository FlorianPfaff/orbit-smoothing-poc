"""Read-only audit of precise transmitter products crossing GPS midnight.

Overlap disagreements are measured at identical epochs. Changes between two
different epochs are reported as boundary samples, not inferred physical jumps.
No product, observation, ambiguity arc or bias datum is changed here.
"""
from datetime import datetime
import gzip
import json
from pathlib import Path

import numpy as np

from orbit_poc.comparison.data import artifact,read_sp3,read_clock,read_gps_osb,sha256_file,write_json


ROLES=("gnss_orbits","gnss_clocks","gnss_attitudes","gnss_biases")
ORIGIN=datetime(2000,1,1,12)


def read_attitudes(path):
    rows={};epoch=None
    opener=gzip.open if str(path).endswith(".gz") else open
    with opener(path,"rt",encoding="latin1") as stream:
        for line in stream:
            if line.startswith("##"):
                fields=line[2:].split()
                epoch=(datetime(*map(int,fields[:5]))-ORIGIN).total_seconds()+float(fields[5])
            else:
                fields=line.split()
                if len(fields)>=2 and fields[0]=="ATT" and fields[1].startswith("G"):
                    if epoch is None or len(fields)!=7 or fields[2]!="4":
                        raise ValueError("Invalid GPS ORBEX quaternion record")
                    q=[float(x.replace("D","E")) for x in fields[3:]]
                    rows.setdefault(fields[1],[]).append([epoch,*q])
    return {sat:np.asarray(values,dtype=float) for sat,values in rows.items()}


def _samples(role,path):
    rows={"gnss_orbits":read_sp3,"gnss_clocks":read_clock,
          "gnss_attitudes":read_attitudes}[role](path)
    if not rows:raise ValueError("No GPS samples in transmitter product")
    for sat,values in rows.items():
        # Precise clock products provide the clock model; SP3 clocks do not
        # enter this position audit and may carry a missing-clock sentinel.
        if role=="gnss_orbits":values=values[:,:4]
        if (values.ndim!=2 or len(values)<2 or not np.isfinite(values).all()
                or np.any(np.diff(values[:,0])<=0)):
            raise ValueError("Transmitter epochs must be finite, unique and increasing")
        if role=="gnss_attitudes" and np.any(np.linalg.norm(values[:,1:],axis=1)==0):
            raise ValueError("Zero transmitter quaternion")
        rows[sat]=values
    return rows


def _difference(role,before,after):
    if role=="gnss_attitudes":
        a,b=before/np.linalg.norm(before),after/np.linalg.norm(after)
        sign=1. if np.dot(a,b)>=0 else -1.
        return {"rotation_difference_rad":float(4*np.arcsin(min(1.,np.linalg.norm(a-sign*b)/2))),
                "raw_quaternion_difference":(after-before).tolist(),
                "quaternion_sign_equivalent":bool(np.array_equal(a,sign*b))}
    delta=after-before
    return {"difference_m":delta.tolist(),"position_difference_norm_m":float(np.linalg.norm(delta))} if role=="gnss_orbits" else {"clock_difference_seconds":float(delta[0])}


def audit_daily_products(daily,output):
    """Pin all daily sources and record every adjacent-product discrepancy.

    Return summary/event artifacts for inclusion in the frozen product records.
    Raw event ledgers can be large and belong outside Git with the inputs.
    """
    if set(daily)!=set(ROLES):raise ValueError("All four daily transmitter product types are required")
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    summary_path=output/"product-boundaries.json";events_path=output/"product-boundary-events.jsonl"
    if summary_path.exists() or events_path.exists():raise ValueError("Preserve an existing product boundary audit")
    dates=None
    for role in ROLES:
        entries=daily[role];current=[x["date"] for x in entries]
        if len(entries)<2 or current!=sorted(set(current)) or dates is not None and current!=dates:
            raise ValueError("Daily product dates must be unique, ordered and shared across product types")
        dates=current
        for entry in entries:
            if sha256_file(entry["path"])!=entry["sha256"]:
                raise ValueError("Daily transmitter product hash changed")
    counts={"overlap_disagreements":0,"boundary_sample_pairs":0,"missing_boundary_sides":0,"satellite_membership_changes":0,
            "bias_changes":0,"overlap_samples":0}
    pairs=[]
    with events_path.open("x") as stream:
        def emit(value):
            stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+"\n")
        for role in ROLES:
            previous=None;previous_pin=None
            for entry in daily[role]:
                current=read_gps_osb(entry["path"]) if role=="gnss_biases" else _samples(role,entry["path"])
                if previous is not None:
                    base={"role":role,"earlier_date":previous_pin["date"],"later_date":entry["date"],
                          "earlier_sha256":previous_pin["sha256"],"later_sha256":entry["sha256"]}
                    if set(previous)!=set(current):
                        counts["satellite_membership_changes"]+=1
                        emit({**base,"kind":"satellite_membership_change","removed":sorted(set(previous)-set(current)),"added":sorted(set(current)-set(previous))})
                    boundary=(datetime.fromisoformat(entry["date"])-ORIGIN).total_seconds()
                    pair_counts={"overlap_samples":0,"overlap_disagreements":0,"boundary_sample_pairs":0,"missing_boundary_sides":0,"bias_changes":0}
                    for sat in sorted(set(previous)&set(current)):
                        a,b=previous[sat],current[sat]
                        if role=="gnss_biases":
                            for signal in sorted(set(a)|set(b)):
                                before,after=a.get(signal),b.get(signal)
                                if any(x is not None and not np.isfinite(x) for x in (before,after)):
                                    raise ValueError("Nonfinite daily OSB datum")
                                if before!=after:
                                    pair_counts["bias_changes"]+=1
                                    emit({**base,"kind":"daily_bias_change","satellite":sat,"signal":signal,
                                          "earlier_m":before,"later_m":after,
                                          "difference_m":None if before is None or after is None else after-before,
                                          "applied_to_synthetic_data":False})
                            continue
                        common,ia,ib=np.intersect1d(a[:,0],b[:,0],assume_unique=True,return_indices=True)
                        pair_counts["overlap_samples"]+=len(common)
                        for epoch,i,j in zip(common,ia,ib):
                            if not np.array_equal(a[i,1:],b[j,1:]):
                                pair_counts["overlap_disagreements"]+=1
                                emit({**base,"kind":"same_epoch_product_disagreement","satellite":sat,
                                      "gps_seconds_since_j2000":float(epoch),"earlier_values":a[i,1:].tolist(),
                                      "later_values":b[j,1:].tolist(),**_difference(role,a[i,1:],b[j,1:])})
                        before=np.flatnonzero(a[:,0]<boundary);after=np.flatnonzero(b[:,0]>=boundary)
                        if len(before) and len(after):
                            first,last=a[before[-1]],b[after[0]]
                            pair_counts["boundary_sample_pairs"]+=1
                            emit({**base,"kind":"boundary_samples","satellite":sat,
                                  "earlier_gps_seconds_since_j2000":float(first[0]),"later_gps_seconds_since_j2000":float(last[0]),
                                  "sample_gap_seconds":float(last[0]-first[0]),
                                  "earlier_native_cadence_seconds":float(np.median(np.diff(a[:,0]))),
                                  "later_native_cadence_seconds":float(np.median(np.diff(b[:,0]))),
                                  "earlier_values":first[1:].tolist(),"later_values":last[1:].tolist(),
                                  **_difference(role,first[1:],last[1:])})
                        else:
                            pair_counts["missing_boundary_sides"]+=1
                            emit({**base,"kind":"boundary_samples_unavailable","satellite":sat,
                                  "boundary_gps_seconds_since_j2000":boundary,
                                  "earlier_side_available":bool(len(before)),"later_side_available":bool(len(after)),
                                  "earlier_product_coverage_gps_seconds_since_j2000":a[[0,-1],0].tolist(),
                                  "later_product_coverage_gps_seconds_since_j2000":b[[0,-1],0].tolist(),
                                  "reason":"At least one daily product has no sample on its required side of midnight"})
                    for key,value in pair_counts.items():counts[key]+=value
                    pairs.append({**base,**pair_counts})
                previous,previous_pin=current,entry
    summary={"schema":"orbit-poc-segmented-product-boundaries-v1","daily_sources":daily,"dates":dates,
             "counts":counts,"pairs":pairs,"events":artifact(events_path,"transmitter_product_boundary_events"),
             "time_scale":"GPS seconds since J2000","overlap_policy":"Later GPS day wins, unchanged native merge",
             "bias_policy":"Synthetic generator and estimator share fixed first-day OSB; daily differences are audited only",
             "bias_audit_scope":"Native-selected GPS OSB datum: code attributes remain distinct; first phase bias per frequency. Other raw OSB attributes are not claimed as audited.",
             "boundary_difference_interpretation":"Different-epoch changes include ordinary satellite evolution; they do not by themselves establish a jump",
             "products_modified":False,"ambiguity_resets_inserted":False}
    write_json(summary_path,summary)
    return {"summary":artifact(summary_path,"transmitter_product_boundary_audit"),"events":summary["events"]}
