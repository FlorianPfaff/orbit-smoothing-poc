"""Independent native SLR validation; normal points never constrain the orbit."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from .data import (GROOPS_DATA, artifact, canonical_hash, fetch_url,
                   sha256_file, validate_flight_date, write_json)
from .groops_config import _add, _program, _rotation, _save

LRR_MANUAL = "https://ilrs.gsfc.nasa.gov/docs/2015/GFO-MA-GFZ-LR-0001_2.pdf"
CSR_STANDARD = "https://isdc-data.gfz.de/grace-fo/DOCUMENTS/Level-2/GRACE-FO_CSR_L2_Processing_Standards_Document_for_RL06.pdf"
REFLECTOR_OFFSET_SRF_M = (-.6000, -.3275, .2188)
CRD_EPOCH_MATCH_TOLERANCE_SECONDS = 1e-5


class SlrPrerequisiteError(RuntimeError):
    """A physical correction or required provenance is unavailable."""


def prism_correction(direction_srf, wavelength_m):
    """GFZ LRR manual Eq2, dominating prism, metres to ADD to observed range.

    Direction is from satellite to station in SRF (+Z nadir). The four prism
    normals have polar45deg, azimuth45+90k degrees. The second return value
    flags the published incidence-angle cutoff, independent of fit residual.
    """
    direction = np.asarray(direction_srf, dtype=float)
    direction = direction / np.linalg.norm(direction, axis=-1, keepdims=True)
    wavelengths = np.array([355., 425., 532., 850., 1064.])*1e-9
    indices = np.array([1.5329, 1.5064, 1.4853, 1.4657, 1.4624])
    index = np.argmin(abs(wavelengths-wavelength_m))
    if abs(wavelengths[index]-wavelength_m) > 1e-9:
        raise SlrPrerequisiteError("unsupported wavelength for published prism model")
    cosine = .5*(abs(direction[...,0])+abs(direction[...,1])) + np.sqrt(.5)*direction[...,2]
    correction = .0474*cosine-.028*np.sqrt(indices[index]**2-(1-cosine**2))
    return correction, cosine >= np.cos(.85)


def inspect_crd(path, output_path=None):
    """Validate correction flags and station meteorology before native use.

    Unsupported/quality-alert passes are excluded using file metadata only.
    CRD normal points are required to have station system delay applied, but
    troposphere and centre-of-mass corrections unapplied. No residual trimming.
    """
    sessions, current = [], []
    for line in Path(path).read_text().splitlines():
        if line[:2].upper() == "H1" and current:
            raise SlrPrerequisiteError("unterminated CRD session")
        current.append(line)
        if line[:2].upper() == "H8":
            sessions.append(current)
            current = []
    selected, excluded, stations, metadata = [], [], set(), []
    source_sha256 = sha256_file(path)
    for number, session in enumerate(sessions):
        records = [line.split() for line in session if line.strip()]
        def record(tag):
            return next((r for r in records if r[0].upper() == tag), None)
        h2, h3, h4, c0 = (record(tag) for tag in ("H2", "H3", "H4", "C0"))
        count = sum(r[0] == "11" for r in records)
        reasons = []
        if not all((h2,h3,h4,c0)):
            reasons.append("missing_header")
        else:
            if h3[1].lower() != "gracefo1": reasons.append("wrong_target")
            if h4[1] != "1": reasons.append("not_normal_points")
            if len(h4) < 22 or h4[15:17] != ["0","0"] or h4[18] != "1" or h4[20] != "2":
                reasons.append("unsupported_applied_correction_flags")
            if len(h4) >= 22 and h4[21] != "0": reasons.append("provider_quality_alert")
            try: prism_correction([0,0,1],float(c0[2])*1e-9)
            except (ValueError,SlrPrerequisiteError): reasons.append("unsupported_wavelength")
        met = [r for r in records if r[0] == "20"]
        if not met:
            reasons.append("missing_station_meteorology")
        else:
            try:
                if any(not (100 < float(r[2]) < 1200 and 180 < float(r[3]) < 340 and 0 <= float(r[4]) <= 100) for r in met):
                    reasons.append("invalid_station_meteorology")
            except (ValueError,IndexError): reasons.append("invalid_station_meteorology")
        if any(r[0] == "11" and r[4] not in ("0","1","2") for r in records):
            reasons.append("unsupported_epoch_event")
        if any(r[0].upper() == "C4" for r in records):
            reasons.append("transponder_configuration_not_supported")
        bounds = {}
        if h4:
            try:
                def timestamp(fields):
                    return datetime(*map(int, fields[:5]))+timedelta(seconds=float(fields[5]))
                start, end = timestamp(h4[2:8]), timestamp(h4[8:14])
                if end < start:
                    raise ValueError("reversed CRD session bounds")
                origin = datetime(start.year, start.month, start.day)
                # Match the native converter's event convention exactly, using
                # source normal-point times rather than integer-second H4 bounds.
                # Some providers' last point is a fraction of a second after H4.
                transmit = []
                for row in records:
                    if row[0] != "11": continue
                    correction = {"0": Decimal(1), "1": Decimal(".5"), "2": Decimal(0)}[row[4]]
                    transmit.append(str(Decimal(row[1])-correction*Decimal(row[2])))
                bounds = {"header_start_utc":start.isoformat(), "header_end_utc":end.isoformat(),
                    "transmit_time_origin_utc":origin.isoformat(),
                    "transmit_seconds_from_origin":transmit,
                    "transmit_start_utc":(origin+timedelta(seconds=float(min(map(Decimal, transmit))))).isoformat() if transmit else None,
                    "transmit_end_utc":(origin+timedelta(seconds=float(max(map(Decimal, transmit))))).isoformat() if transmit else None,
                    "epoch_convention":"UTC ground transmit: event0 subtracts full round-trip time, event1 half, event2 none",
                    "header_sha256":hashlib.sha256(" ".join(h4).encode()).hexdigest()}
            except (ValueError, IndexError, KeyError, ArithmeticError):
                reasons.append("invalid_session_times")
        entry = {"session":number,"station":h2[2] if h2 else None,"normal_points":count,
                 "reasons":reasons,"source_sha256":source_sha256, **bounds}
        metadata.append(entry)
        if reasons:
            excluded.append(entry)
        else:
            selected.extend(session)
            stations.add(h2[2])
    if not selected:
        raise SlrPrerequisiteError("no CRD passes meet the fixed correction/quality requirements")
    if output_path:
        Path(output_path).parent.mkdir(parents=True,exist_ok=True)
        Path(output_path).write_text("\n".join(selected)+"\nh9\n")
    return {"source_sha256":source_sha256,"stations":sorted(stations),
            "raw_normal_points":sum(s["normal_points"] for s in metadata),
            "retained_normal_points":sum(s["normal_points"] for s in metadata if not s["reasons"]),
            "sessions":metadata,"excluded_sessions":excluded,
            "selection":"provider flags, correction convention, epoch event and meteorology; no residual cuts"}


def _satellite_info(path):
    root = ET.Element("groops", {"type":"platform","version":"20200123"})
    p = _add(root,"platform")
    for tag,value in (("markerName","gracefo1"),("markerNumber","1804701"),("comment","CSR RL06 SRF LRA offset; optical prism correction in predictor")):
        _add(p,tag,value)
    position = _add(p,"approxPosition")
    for axis in "xyz": _add(position,axis,0)
    _add(p,"equipmentCount",1)
    e = _add(p,"equipment")
    for tag,value in (("type",5),("comment","GRACE-FO LRR"),("name","gracefo1"),("serial","1804701"),("timeStart",58261),("timeEnd",100000)):
        _add(e,tag,value)
    position = _add(e,"position")
    for axis,value in zip("xyz",REFLECTOR_OFFSET_SRF_M): _add(position,axis,value)
    rotation = _add(e,"platform2reflectorFrame")
    for a in "xyz":
        for b in "xyz": _add(rotation,a+b,int(a==b))
    _add(e,"dZenit",0)
    matrix = _add(e,"range")
    for tag,value in (("type",0),("rows",1),("columns",1)): _add(matrix,tag,value)
    _add(matrix,"cell",0,row="0",col="0")
    _add(p,"referencePointCount",0)
    return _save(root,path)


DHF_URL = "https://ilrs.gsfc.nasa.gov/docs/2025/ILRS_Data_Handling_File_20250513.snx"


def _slr_source_specs(stations):
    """Every external file read by the SLR predictor, including shared physics."""
    required = ["loading/deformationLoveNumbers_CM_Gegout97.txt", "loading/loadLoveNumbers_Gegout97.txt",
        "tides/secularPole2018.xml", "tides/oceanPoleTide_desai2004.dat",
        "tides/earthAnelastic2003.xml", "tides/oceanTide_fes2014b_n180_version20170520.dat",
        "tides/oceanTide_fes2014b_admittance_linear_linear.txt", "tides/ephemerides_JPL_DE432.dat",
        "earthRotation/timeSeries_EOP_rapid_IAU2000_desai.dat"]
    for station in stations:
        required += [f"slr/stations/stationInfo/stationInfo.{station}.xml",
                     f"slr/stations/position/slrf2020_CM/stationPosition.{station}.dat"]
    return [(GROOPS_DATA+relative, relative) for relative in required]+[
        (DHF_URL, "slr/documentation/ILRS_Data_Handling_File_20250513.snx"),
        (LRR_MANUAL, "slr/documentation/GFO-LRR-manual.pdf"),
        (CSR_STANDARD, "slr/documentation/CSR-RL06-standards.pdf")]


def crd_station_headers(path):
    """Read station identifiers only; never interpret normal-point values prefit."""
    stations = set()
    with Path(path).open() as stream:
        for line in stream:
            if line[:2].upper() != "H2": continue
            fields = line.split()
            if len(fields) < 3 or len(fields[2]) != 4 or not fields[2].isdigit():
                raise ValueError("Invalid CRD station header in SLR auxiliary preflight")
            stations.add(fields[2])
    return sorted(stations)


def verify_slr_auxiliary(record, date, crd_path, auxiliary_dir):
    """Verify the frozen correction files without any network or orbit access."""
    payload = {key: value for key, value in record.items() if key != "manifest_hash"}
    if record.get("manifest_hash") != canonical_hash(payload):
        raise ValueError("SLR auxiliary freeze has been modified")
    if record.get("schema_version") != 1 or record.get("date") != date:
        raise ValueError("SLR auxiliary freeze date/schema mismatch")
    if record.get("crd_source", {}).get("sha256") != sha256_file(crd_path):
        raise ValueError("SLR auxiliary freeze normal-point source changed")
    if record.get("stations") != crd_station_headers(crd_path):
        raise ValueError("SLR auxiliary freeze station header inventory changed")
    aux = Path(auxiliary_dir).resolve()
    expected = {(url, str(aux/relative)) for url, relative in _slr_source_specs(record["stations"])}
    sources = record.get("sources", [])
    actual = {(item["url"], item["path"]) for item in sources}
    if actual != expected or len(sources) != len(expected):
        raise ValueError("SLR auxiliary freeze source inventory is incomplete")
    for item in sources:
        if sha256_file(item["path"]) != item["sha256"]:
            raise ValueError("Frozen SLR correction changed: "+item["path"])
        if sha256_file(item["acquisition_path"]) != item["acquisition_sha256"]:
            raise ValueError("Frozen SLR acquisition record changed: "+item["acquisition_path"])
        acquisition = json.loads(Path(item["acquisition_path"]).read_text())
        if any(acquisition.get(key) != item[key] for key in ("url", "sha256")):
            raise ValueError("Frozen SLR acquisition record has inconsistent identity")
    return record


def preflight_slr_auxiliary(date, crd_path, auxiliary_dir, manifest_path, *,
                            download=True, allow_frozen_evaluation=False):
    """Pin external corrections after calibration using only CRD station headers.

    Normal-point values, quality/residual screening and GNV interpretation remain
    post-fit operations. All header stations are included, even if excluded later.
    """
    validate_flight_date(date, allow_frozen_evaluation=allow_frozen_evaluation)
    path, aux = Path(manifest_path), Path(auxiliary_dir).resolve()
    if path.exists():
        return verify_slr_auxiliary(json.loads(path.read_text()), date, crd_path, aux)
    stations = crd_station_headers(crd_path)
    sources = []
    for url, relative in _slr_source_specs(stations):
        item = fetch_url(url, aux/relative, download=download)
        acquisition = Path(item["path"]+".source.json")
        sources.append({**item, "acquisition_path":str(acquisition),
                        "acquisition_sha256":sha256_file(acquisition)})
    record = {"schema_version":1, "date":date, "status":"frozen",
        "crd_source":artifact(crd_path, "slr_validation"), "stations":stations, "sources":sources,
        "prefit_access":"CRD H2 station identifiers only; raw files hashed without interpreting normal points or reference ephemerides",
        "reflector_offset_srf_m":list(REFLECTOR_OFFSET_SRF_M),
        "correction_policy":"Fixed published reflector/prism model and bounded ILRS bias records; no corrections fitted to evaluation observations"}
    record["manifest_hash"] = canonical_hash(record)
    verify_slr_auxiliary(record, date, crd_path, aux)
    write_json(path, record)
    return record


def slr_auxiliary_inventory(manifest_path, record):
    """Transitive byte inventory embedded in the campaign evaluation freeze."""
    records = [{"usage":"slr_evaluation_corrections", **artifact(manifest_path, "slr_auxiliary_manifest")}]
    for item in record["sources"]:
        records += [{"usage":"slr_evaluation_corrections", "role":"slr_auxiliary_source",
            "path":item["path"], "sha256":item["sha256"]},
            {"usage":"slr_evaluation_corrections", "role":"slr_auxiliary_acquisition",
            "path":item["acquisition_path"], "sha256":item["acquisition_sha256"]}]
    return records


def frozen_slr_auxiliary(job, evaluation_dir, crd_path):
    """Resolve an evaluator's date-specific corrections from the campaign freeze."""
    candidates = [parent/"evaluation-input-freeze-flight.json"
                  for parent in [Path(evaluation_dir).resolve(), *Path(evaluation_dir).resolve().parents]]
    freeze_path = next((path for path in candidates if path.is_file()), None)
    if freeze_path is None:
        raise ValueError("Frozen flight evaluation requires its SLR auxiliary input freeze")
    frozen = json.loads(freeze_path.read_text())
    payload = {key:value for key,value in frozen.items() if key != "input_freeze_hash"}
    if frozen.get("input_freeze_hash") != canonical_hash(payload):
        raise ValueError("Evaluation input freeze has been modified")
    if frozen.get("stage") != "flight" or frozen.get("status") != "frozen":
        raise ValueError("SLR correction inventory is not a frozen flight evaluation")
    for key in ("protocol_hash", "source_hash"):
        if frozen.get(key) != job.get(key):
            raise ValueError("SLR correction freeze differs from evaluation job: "+key)
    if frozen.get("native_binary", {}).get("sha256") != job.get("expected_native_binary_sha256"):
        raise ValueError("SLR correction freeze native identity differs")
    matches = [entry for entry in frozen.get("slr_auxiliary", []) if entry["date"] == job["case"]["date"]]
    if len(matches) != 1:
        raise ValueError("Frozen flight evaluation requires exactly one date-specific SLR correction manifest")
    item = matches[0]
    if sha256_file(item["path"]) != item["sha256"]:
        raise ValueError("Frozen SLR correction manifest changed")
    record = verify_slr_auxiliary(json.loads(Path(item["path"]).read_text()),
        job["case"]["date"], crd_path, job["backend"]["auxiliary_dir"])
    declared = {(row["usage"], row["role"], row["path"], row["sha256"]) for row in frozen["inputs"]}
    required = {(row["usage"], row["role"], row["path"], row["sha256"])
                for row in slr_auxiliary_inventory(item["path"], record)}
    if not required <= declared:
        raise ValueError("SLR corrections are missing from the evaluation input inventory")
    return record


def station_bias_policy(path, date, stations):
    """Bounded ILRS records; never carry an expired historic correction forward.

    Formal scores require both externally calibrated LAGEOS bias estimates with
    quoted uncertainty. Other stations remain descriptive, with no fitted bias.
    """
    from datetime import timedelta
    text=Path(path).read_text()
    if not text.startswith("=SNX") or "+MODEL/RANGE_BIAS" not in text:
        raise SlrPrerequisiteError("invalid ILRS Data Handling SINEX file")
    start=datetime.fromisoformat(date);end=start+timedelta(days=1)
    def instant(value,upper=False):
        if value=="00:000:00000": return datetime.max if upper else datetime.min
        year,day,seconds=map(int,value.split(":"))
        return datetime(1900+year if year>=50 else 2000+year,1,1)+timedelta(days=day-1,seconds=seconds)
    active={station:[] for station in stations};section=""
    for line in text.splitlines():
        if line.startswith("+"):section=line[1:]
        if section not in ("MODEL/RANGE_BIAS","MODEL/TIME_BIAS","SOLUTION/DATA_HANDLING"):continue
        f=line.split()
        if len(f)<7 or f[0] not in active or not f[4].count(":")==2:continue
        a,b=instant(f[4]),instant(f[5],True)
        if a>=end or b<=start:continue
        if not (a<=start and b>=end):
            raise SlrPrerequisiteError("ILRS correction changes within day; bounded segment handling required")
        active[f[0]].append({"section":section,"target":f[1],"code":f[6],"record":line,
                            "value":float(line[44:56]) if line[44:56].strip() else None,
                            "sigma":float(line[56:64]) if line[56:64].strip() else None})
    result={}
    for station,entries in active.items():
        generic=[r for r in entries if r["target"] in ("--","64") and r["section"] != "MODEL/RANGE_BIAS"]
        unsupported=[r for r in generic if r["code"] in ("T","P","H","C","S","R","U")]
        if unsupported:
            raise SlrPrerequisiteError(f"station{station} has an active additional ILRS correction; implement its bounded correction before validation")
        bad=[r for r in generic if r["code"] in ("X","N","Q","V")]
        range_records=[]
        for target in ("51","52"):
            match=[r for r in entries if r["section"]=="MODEL/RANGE_BIAS" and r["target"]==target and r["code"]=="R"]
            if len(match)>1:raise SlrPrerequisiteError("overlapping ILRS range-bias records")
            range_records.append(match[0] if match else None)
        formal=all(r and r["value"] is not None and r["sigma"] is not None for r in range_records) and not bad
        estimated=any(r["code"]=="E" and r["target"] in ("--","64","51","52") for r in entries)
        formal=bool(formal and not estimated)
        bias=.0005*sum(r["value"] if r and r["value"] is not None else 0 for r in range_records)
        sigma=.0005*sum(r["sigma"] for r in range_records) if formal else None
        result[station]={"range_bias_m":bias,"range_bias_sigma_m":sigma,
            "formal_prediction_eligible":formal,"descriptive_only":not formal,
            "exclude_station":bool(bad),"active_records":entries,
            "reason":"externally calibrated LAGEOS1/2 mean" if formal else "no complete bounded external bias calibration or ILRS requires bias estimation",
            "uncertainty_policy":"mean of published standard deviations (conservative perfect correlation); station-common across normal points" if formal else "unknown station bias; no formal predictive score"}
    return result


def _write_range_bias(path,mjd,value):
    Path(path).write_text("groops instrument version=20200123\n# MISCVALUE\n-3 1\n# GPSMJD range-bias[m]\n1\n"+f"{mjd:.14f} {value:.17g}\n")


def build_slr_configs(date, crd_path, fitted_orbit_path, attitude_path,
                      auxiliary_dir, output_dir, *, download=True,
                      allow_frozen_evaluation=False, fit_config_path=None,
                      parameter_covariance_path=None, variational_path=None, frozen_auxiliary=None):
    """Build native correction-complete validation inputs from an already fit orbit."""
    validate_flight_date(date,allow_frozen_evaluation=allow_frozen_evaluation)
    root,aux = Path(output_dir).resolve(),Path(auxiliary_dir).resolve()
    root.mkdir(parents=True,exist_ok=True)
    qc = inspect_crd(crd_path,root/"selected.np2")
    if frozen_auxiliary is not None:
        if download:
            raise ValueError("Frozen SLR correction evaluation must be offline")
        frozen_auxiliary = verify_slr_auxiliary(frozen_auxiliary, date, crd_path, aux)
        if not set(qc["stations"]) <= set(frozen_auxiliary["stations"]):
            raise ValueError("Post-fit SLR stations were not frozen before evaluation")
        sources = frozen_auxiliary["sources"]
    else:
        sources = []
        for url, relative in _slr_source_specs(qc["stations"]):
            try: sources.append(fetch_url(url, aux/relative, download=download))
            except Exception as exc: raise SlrPrerequisiteError(f"required SLR auxiliary unavailable: {relative}") from exc
    dhf_path=aux/"slr/documentation/ILRS_Data_Handling_File_20250513.snx"
    bias_policy=station_bias_policy(dhf_path,date,qc["stations"])
    listings={"rangeBias":list(qc["stations"]),"timeBias":[]}
    day_mjd=(datetime.fromisoformat(date)-datetime(1858,11,17)).days
    for station,policy in bias_policy.items():
        _write_range_bias(root/f"rangeBias.{station}.txt",day_mjd,policy["range_bias_m"])
    excluded_stations=[s for s,p in bias_policy.items() if p["exclude_station"]]
    qc["station_metadata_exclusions"]=excluded_stations
    qc["stations"]=[s for s in qc["stations"] if s not in excluded_stations]
    if not qc["stations"]:raise SlrPrerequisiteError("all stations excluded by ILRS metadata")
    info=_satellite_info(root/"satelliteInfo.gracefo1.xml")
    (root/"satellites.txt").write_text("gracefo1\n")
    (root/"stations.txt").write_text("\n".join(qc["stations"])+"\n")
    conversion=ET.Element("groops")
    p=_program(conversion,"Crd2NormalPoints")
    _add(p,"outputfileNormalPoints",root/"normalPoints.{station}.dat")
    _add(p,"outputfileMeteorological",root/"meteorology.{station}.dat")
    _add(p,"inputfileSlrData",root/"selected.np2")
    prediction=ET.Element("groops")
    p=_program(prediction,"OrbitPocPredictSlr")
    _add(p,"outputfilePredictions",root/"slr_predictions.txt")
    covariance_path = None
    if any(x is not None for x in (fit_config_path,parameter_covariance_path,variational_path)):
        if not all(x is not None for x in (fit_config_path,parameter_covariance_path,variational_path)):
            raise SlrPrerequisiteError("SLR predictive covariance requires the final fit configuration, variational file and parameter covariance")
        fitted = ET.parse(fit_config_path).getroot()
        globals_node = fitted.find("global")
        if globals_node is not None: prediction.insert(0,deepcopy(globals_node))
        dynamic = fitted.find(".//leoDynamicOrbits")
        if dynamic is None: raise SlrPrerequisiteError("final native dynamic configuration missing")
        _add(p,"inputfileParameterCovariance",Path(parameter_covariance_path).resolve())
        _add(p,"inputfileVariational",Path(variational_path).resolve())
        covariance_path = str(root/"slr_predictive_covariance.txt")
        _add(p,"outputfilePredictiveCovariance",covariance_path)
        for tag in ("parametrizationAcceleration","stochasticPulse","ephemerides","integrationDegree","interpolationDegree"):
            for child in dynamic.findall(tag): p.append(deepcopy(child))
        start = (datetime.fromisoformat(date)-datetime(1858,11,17)).days
        for node in p.iter():
            if node.text:
                node.text = node.text.replace("{loopTime:%D}",date).replace("{station}","gracefo1").replace("loopTimeEnd",str(start+1)).replace("loopTime",str(start))
    mjd=(datetime.fromisoformat(date)-datetime(1858,11,17)).days
    # Daily CRD files are UTC days. Preserve exact GPS epochs via the native
    # offset rather than parsing a fractional absolute MJD as binary64.
    arc_offset=18.
    if fit_config_path:
        node=ET.parse(fit_config_path).find("global/double[@label='arcStartOffsetSeconds']")
        if node is not None:arc_offset=float(node.text)
    sampling=_add(_add(p,"timeSeries"),"uniformSampling")
    for tag,value in (("timeStart",mjd),("timeEnd",mjd+1),("sampling","600/86400"),("offsetSeconds",arc_offset)): _add(sampling,tag,value)
    satellite=_add(_add(p,"satellite"),"satellites")
    for tag,value in (("inputfileSatelliteList",root/"satellites.txt"),("inputfileSatelliteInfo",info),
                      ("inputfileOrbit",Path(fitted_orbit_path).resolve()),("inputfileAttitude",Path(attitude_path).resolve()),("interpolationDegree",7)):
        _add(satellite,tag,value)
    station=_add(_add(p,"station"),"stations")
    for tag,value in (("inputfileStationList",root/"stations.txt"),
                      ("inputfileStationInfo",aux/"slr/stations/stationInfo/stationInfo.{station}.xml"),
                      ("inputfileStationPosition",aux/"slr/stations/position/slrf2020_CM/stationPosition.{station}.dat"),
                      ("disableStationWithoutPosition",1),("inputfileObservations",root/"normalPoints.{station}.dat"),
                      ("accuracy","max(accuracy,0.005)"),("elevationCutOff",20),("interpolationDegree",7),
                      ("inputfileDeformationLoadLoveNumber",aux/"loading/deformationLoveNumbers_CM_Gegout97.txt"),
                      ("inputfilePotentialLoadLoveNumber",aux/"loading/loadLoveNumbers_Gegout97.txt")):
        _add(station,tag,value)
    tide=_add(_add(station,"tidalDisplacement"),"earthTide")
    _add(tide,"inputfileEarthtide",aux/"tides/earthAnelastic2003.xml")
    _add(tide,"includePermanentTide",0)
    tide=_add(_add(station,"tidalDisplacement"),"doodsonHarmonicTide")
    _add(tide,"inputfileTides",aux/"tides/oceanTide_fes2014b_n180_version20170520.dat")
    _add(tide,"inputfileAdmittance",aux/"tides/oceanTide_fes2014b_admittance_linear_linear.txt")
    tide=_add(_add(station,"tidalDisplacement"),"poleTide")
    _add(tide,"inputfileMeanPole",aux/"tides/secularPole2018.xml")
    tide=_add(_add(station,"tidalDisplacement"),"oceanPoleTide")
    _add(tide,"inputfileOceanPole",aux/"tides/oceanPoleTide_desai2004.dat")
    _add(tide,"inputfileMeanPole",aux/"tides/secularPole2018.xml")
    ephemerides=_add(_add(station,"ephemerides"),"jpl")
    _add(ephemerides,"inputfileEphemerides",aux/"tides/ephemerides_JPL_DE432.dat")
    _add(_add(ephemerides,"origin"),"earth")
    _rotation(p,aux)
    trop=_add(_add(p,"parametrization"),"troposphere")
    _add(_add(trop,"selectStations"),"all")
    _add(_add(_add(trop,"troposphere"),"mendesAndPavlis"),"inputfileStationMeteorology",root/"meteorology.{station}.dat")
    correction=_add(_add(p,"parametrization"),"rangeBiasStationApriori")
    _add(_add(correction,"selectStations"),"all")
    _add(correction,"inputfileRangeBias",root/"rangeBias.{station}.txt")
    manifest={"status":"configured","date":date,"configs":{"convert_slr":_save(conversion,root/"convert_slr.xml"),
               "predict_slr":_save(prediction,root/"predict_slr.xml")},"predictions":str(root/"slr_predictions.txt"),
              "predictive_covariance":covariance_path,
              "quality_control":qc,"sources":sources,"slr_auxiliary_freeze_hash":(frozen_auxiliary or {}).get("manifest_hash"),
              "fitted_orbit":artifact(fitted_orbit_path,"fitted_orbit"),
              "attitude":artifact(attitude_path,"attitude"),"reflector_offset_srf_m":REFLECTOR_OFFSET_SRF_M,
              "published_bias_stations":listings,"station_bias_policy":bias_policy,
              "formal_prediction_stations":[s for s,policy in bias_policy.items() if policy["formal_prediction_eligible"]],
              "bias_policy":"Bounded ILRS2025 mean LAGEOS1/2 biases; no fitted SLR bias. Stations without external bias calibration are descriptive only.",
              "corrections":["CRD UTC-to-GPS event time","station calibration already applied in CRD",
                 "SLRF2020_CM station positions and eccentricity","solid Earth/ocean/pole tides",
                 "Mendes-Pavlis with measured meteorology","native round-trip light time and Shapiro",
                 "measured spacecraft attitude and CSR SRF reflector offset","GFZ wavelength-dependent angular prism correction"],
              "limitations":["No non-tidal loading supplied; unmodeled displacement contributes to external residuals.",
                 "CSR post-launch reflector z=.2188m differs from prelaunch ILRS/manual .221m by2.2mm; CSR convention fixed before evaluation.",
                 "Dominating-prism approximation has documented sub-millimetre error; no SLR parameter estimation."],
              "fit_to_slr":False}
    write_json(root/"slr_manifest.json",manifest)
    return manifest


def summarize_slr(path, *, predictive_covariance=None,
                  formal_prediction_stations=(), gps_utc_offset_seconds=18,
                  pass_sessions=None, pass_source_sha256=None):
    """Describe all usable returns and score fixed externally calibrated subsets.

    ``predictive_covariance`` is the full matrix in native prediction-row order,
    including measurement noise and externally supplied station-common bias
    uncertainty. Each group uses its principal submatrix; grouped scores overlap
    and must never be added or treated as independent trials. CRD-session groups
    require source metadata; native arc IDs are never labelled as passes.
    """
    from datetime import timedelta
    from .metrics import flight_residual_metrics
    if isinstance(path, (str, Path)):
        rows=[]
        for line in Path(path).read_text().splitlines():
            try: row=[float(x) for x in line.split()]
            except ValueError: continue
            if len(row) in (14, 15): rows.append(row[:14])
        data=np.asarray(rows, dtype=float).reshape((-1,14))
    else:
        data=np.asarray(path,dtype=float)
        if data.size==0: data=np.empty((0,14))
        if data.ndim!=2 or data.shape[1] not in (14,15):
            raise SlrPrerequisiteError("unsupported native SLR prediction schema")
        data=data[:,:14]
    if not np.all(np.isfinite(data)):
        raise SlrPrerequisiteError("nonfinite native SLR predictions")
    n=len(data)
    covariance=None if predictive_covariance is None else np.asarray(predictive_covariance,dtype=float)
    if covariance is not None and (covariance.shape!=(n,n) or not np.isfinite(covariance).all()):
        raise SlrPrerequisiteError("full SLR covariance must match all native prediction rows")
    valid=data[:,9]==1
    station_ids=data[:,1].astype(int)
    formal=valid & np.isin(station_ids,[int(x) for x in formal_prediction_stations])
    dates=np.array([(datetime(1858,11,17)+timedelta(days=float(mjd),seconds=-gps_utc_offset_seconds)).date().isoformat()
                    for mjd in data[:,0]])
    elevation=np.rad2deg(data[:,5]);azimuth=np.mod(np.rad2deg(data[:,6]),360.)

    def group(mask):
        retained=mask & valid
        chosen=np.flatnonzero(retained)
        r=data[chosen,3]
        score=flight_residual_metrics(r,sigma=data[chosen,4])
        score.update(status="complete" if len(chosen) else "unavailable",
                     count=len(chosen),native_points=int(np.count_nonzero(mask)),
                     reflector_cutoff_excluded=int(np.count_nonzero(mask & ~valid)))
        if not len(chosen): score["reason"]="No native points within the fixed reflector incidence cutoff"
        selected=np.flatnonzero(mask & formal)
        if not len(selected) or covariance is None:
            score["predictive"]={"status":"unavailable","valid":False,"nll":None,"dimensions":len(selected),
                "reason":"No physically usable externally calibrated points" if not len(selected) else "Predictive covariance unavailable"}
        else:
            projected=covariance[np.ix_(selected,selected)]
            predictive=flight_residual_metrics(data[selected,3],sigma=data[selected,4],predictive_covariance=projected)["predictive"]
            predictive["status"]="complete" if predictive["valid"] else "invalid_covariance"
            predictive["stations"]=sorted(set(station_ids[selected].tolist()))
            score["predictive"]=predictive
        if len(chosen):
            score["geometry"]={"elevation_min_deg":float(elevation[chosen].min()),"elevation_max_deg":float(elevation[chosen].max()),
                "azimuth_min_deg":float(azimuth[chosen].min()),"azimuth_max_deg":float(azimuth[chosen].max())}
        return score

    all_rows=np.ones(n,dtype=bool)
    whole=group(all_rows)
    retained=data[valid]
    result={**whole,"normal_points":int(valid.sum()),"stations":sorted(set(station_ids[valid].tolist())),
        "passes":None,
        "range_rms_m":whole["rms_m"],"range_mean_m":whole["mean_m"],"range_median_m":whole["median_m"],
        "range_abs_p95_m":float(np.percentile(abs(retained[:,3]),95)) if len(retained) else None,
        "residual_sign":"observed-minus-modeled one-way range","fit_to_slr":False,
        "date_time_scale":"UTC", "gps_minus_utc_seconds":gps_utc_offset_seconds,
        "grouping_note":"Each formal score uses the full covariance principal submatrix including shared external station-bias uncertainty. Groups overlap; scores are not additive and points are not independent trials.",
        "per_station":{str(s):group(station_ids==s) for s in sorted(set(station_ids.tolist()))},
        "per_date":{d:group(dates==d) for d in sorted(set(dates.tolist()))},
        "per_pass":{},"per_native_arc":{},"by_geometry":{"elevation":{},"azimuth":{}}}
    for day,station,pass_id in sorted(set((dates[i],station_ids[i],int(data[i,2])) for i in range(n))):
        mask=(dates==day)&(station_ids==station)&(data[:,2]==pass_id)
        result["per_native_arc"][f"{day}/station-{station}/arc-{pass_id}"]={"date":day,"station":int(station),"native_arc":pass_id,**group(mask)}
    result["pass_mapping"]={"status":"unavailable", "reason":"Original CRD session metadata was not supplied; native arcs can merge multiple sessions"}
    if pass_sessions is not None:
        if (not isinstance(pass_source_sha256,str) or len(pass_source_sha256)!=64
                or any(c not in "0123456789abcdef" for c in pass_source_sha256)):
            raise SlrPrerequisiteError("CRD pass mapping requires the original source SHA256")
        assignment=np.full(n,-1,dtype=int)
        matches=np.zeros(n,dtype=int)
        errors=[]
        session_numbers=set()
        for index, session in enumerate(pass_sessions):
            if session.get("source_sha256") != pass_source_sha256:
                raise SlrPrerequisiteError("CRD session/source hash mismatch")
            if session["session"] in session_numbers:
                raise SlrPrerequisiteError("duplicate CRD session identity")
            session_numbers.add(session["session"])
            if session.get("reasons"): continue
            try:
                origin=datetime.fromisoformat(session["transmit_time_origin_utc"])
                day=(origin-datetime(1858,11,17)).total_seconds()/86400
                seconds=np.array([float(x) for x in session["transmit_seconds_from_origin"]])
                if not len(seconds) or not np.isfinite(seconds).all(): raise ValueError("empty/nonfinite epochs")
                ids=np.flatnonzero(station_ids==int(session["station"]))
                prediction_seconds=(data[ids,0]-day)*86400-gps_utc_offset_seconds
                difference=np.abs(prediction_seconds[:,None]-seconds[None,:])
                hits=difference<=CRD_EPOCH_MATCH_TOLERANCE_SECONDS
                if np.any(hits.sum(axis=1)>1):
                    raise SlrPrerequisiteError("ambiguous duplicate CRD normal-point epoch")
                chosen=ids[hits.any(axis=1)]
                matches[chosen]+=1; assignment[chosen]=index
                errors.extend(difference.min(axis=1)[hits.any(axis=1)].tolist())
            except (ValueError, KeyError, TypeError) as exc:
                raise SlrPrerequisiteError("invalid CRD session mapping metadata") from exc
        if np.any(matches!=1):
            raise SlrPrerequisiteError("SLR predictions must map uniquely to original CRD sessions")
        for index,session in enumerate(pass_sessions):
            mask=assignment==index
            day=session.get("header_start_utc", "unknown")[:10]
            key=f"{day}/station-{session['station']}/crd-session-{session['session']}"
            result["per_pass"][key]={**group(mask),"date":day,"station":session["station"],
                "crd_session":session["session"],"source_sha256":pass_source_sha256,
                "header_start_utc":session.get("header_start_utc"),"header_end_utc":session.get("header_end_utc"),
                "transmit_start_utc":session.get("transmit_start_utc"),"transmit_end_utc":session.get("transmit_end_utc"),
                "header_sha256":session.get("header_sha256"),
                "source_normal_points":session["normal_points"],"provider_exclusion_reasons":session.get("reasons",[]),
                "native_arc_ids":sorted(set(data[mask,2].astype(int).tolist()))}
            if not mask.any():
                result["per_pass"][key]["reason"]="No native prediction rows after provider and fixed physical selection"
        result["passes"]=len(set(assignment[valid].tolist()))
        result["pass_mapping"]={"status":"complete","definition":"Original provider CRD H4/H8 session, not a native station arc",
            "source_sha256":pass_source_sha256,"source_sessions":len(pass_sessions),
            "sessions_with_native_predictions":len(set(assignment.tolist())),
            "predicted_rows_matched":n,"match_tolerance_seconds":CRD_EPOCH_MATCH_TOLERANCE_SECONDS,
            "maximum_epoch_match_error_seconds":max(errors,default=0.),
            "session_bounds_sha256":hashlib.sha256(json.dumps(pass_sessions,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            "selection":"Station and source ground-transmit epoch only; no residual selection"}
    for low,high in ((-90,30),(30,60),(60,90)):
        mask=(elevation>=low)&((elevation<high) if high<90 else (elevation<=high))
        result["by_geometry"]["elevation"][f"{low}_to_{high}_deg"]=group(mask)
    for low in (0,90,180,270):
        result["by_geometry"]["azimuth"][f"{low}_to_{low+90}_deg"]=group((azimuth>=low)&(azimuth<low+90))
    return result
