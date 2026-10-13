"""Public flight-data acquisition with separate estimation and evaluation inputs.

Downloads are pinned by their first recorded SHA-256; a checksum recorded locally
is an integrity/provenance record, not an assertion of a provider signature.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date, datetime, timezone, timedelta
from fnmatch import fnmatch
import hashlib
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

DEVELOPMENT_DATES = tuple(f"2024-04-{d:02d}" for d in (18, 19, 20, 23, 24, 25))
EVALUATION_DATES = tuple(f"2024-05-{d:02d}" for d in range(7, 13))
GFZ_L1B = "https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/2024/"
CODE_PRODUCTS = "https://www.aiub.unibe.ch/download/CODE/2024/"
EDC_SLR = "https://edc.dgfi.tum.de/pub/slr/data/npt_crd_v2/gracefo1/2024/"
GROOPS_DATA = "https://ftp.tugraz.at/pub/ITSG/groops/data/"


def sha256_file(path: str | Path) -> str:
    """Exact SHA256 shared with the process-local immutable-input identity cache."""
    from .protocol import file_hash
    return file_hash(path)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def write_json(path: str | Path, value: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    tmp.replace(path)


def artifact(path: str | Path, role: str, **metadata) -> dict:
    path = Path(path).resolve()
    return {"role": role, "path": str(path), "sha256": sha256_file(path),
            "bytes": path.stat().st_size, **metadata}


def fetch_url(url: str, path: str | Path, expected_sha256: str | None = None,
              *, download: bool = True, max_bytes: int = 2_000_000_000) -> dict:
    """Atomic HTTPS download; a cached file must match its acquisition record."""
    path = Path(path).resolve()
    record_path = path.with_name(path.name + ".source.json")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("public data URLs must use HTTPS without credentials")
    if path.exists():
        digest = sha256_file(path)
        record = json.loads(record_path.read_text()) if record_path.exists() else None
        if expected_sha256 and digest != expected_sha256:
            raise ValueError(f"checksum mismatch: {path}")
        if record and (record["sha256"] != digest or record["url"] != url):
            raise ValueError(f"cached input changed or URL differs: {path}")
        if record:
            return {**record, "path": str(path)}
        if not download:
            raise ValueError(f"unrecorded cached input: {path}")
    elif not download:
        raise FileNotFoundError(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".partial")
        digest_obj = hashlib.sha256()
        count = 0
        try:
            with urlopen(Request(url, headers={"User-Agent": "orbit-smoothing-research/3"}),
                         timeout=120) as response, tmp.open("wb") as output:
                final_url = response.geturl()
                if urlparse(final_url).scheme != "https":
                    raise ValueError("refusing a non-HTTPS redirect")
                headers = dict(response.headers)
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > max_bytes:
                        raise ValueError(f"download exceeds byte limit: {url}")
                    digest_obj.update(block)
                    output.write(block)
            digest = digest_obj.hexdigest()
            if expected_sha256 and digest != expected_sha256:
                raise ValueError(f"download checksum mismatch: {url}")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        record = {"resolved_url": final_url, "last_modified": headers.get("Last-Modified"),
                  "etag": headers.get("ETag")}
    record = {**(record or {}), "url": url, "path": str(path), "sha256": digest,
              "bytes": path.stat().st_size, "retrieved_utc": datetime.now(timezone.utc).isoformat(),
              "checksum_authority": "caller_pin" if expected_sha256 else "local_acquisition_record"}
    write_json(record_path, record)
    return record


def validate_flight_date(date: str, *, allow_frozen_evaluation: bool = False) -> str:
    Date.fromisoformat(date)
    if date in DEVELOPMENT_DATES:
        return "flight_development"
    if date in EVALUATION_DATES and allow_frozen_evaluation:
        return "flight_evaluation"
    if date in EVALUATION_DATES:
        raise ValueError("May evaluation inputs are locked; an explicit evaluation-stage call is required")
    raise ValueError(f"date is outside the preregistered flight windows: {date}")


def extract_gracefo_bundle(bundle: str | Path, prepared_dir: str | Path, date: str) -> dict:
    """Extract only mission C inputs, never unpack arbitrary archive paths."""
    root = Path(prepared_dir).resolve()
    estimation, evaluation = [], []
    allowed = {"GPS1B": "gnss_observations", "SCA1B": "attitude", "MAS1B": "spacecraft_metadata",
               "VGN1B": "spacecraft_metadata", "THR1B": "spacecraft_metadata",
               "GNV1B": "reference_orbit"}
    with tarfile.open(bundle, "r:gz") as archive:
        for member in archive:
            components = PurePosixPath(member.name)
            if components.is_absolute() or ".." in components.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe archive member: {member.name}")
            name = components.name
            match = re.fullmatch(r"([A-Z0-9]+)_" + re.escape(date) + r"_C_04\.(txt|rnx)", name)
            if not match or match[1] not in allowed or not member.isfile():
                continue
            if member.size > 500_000_000:
                raise ValueError(f"unexpected member size: {name}")
            role = allowed[match[1]]
            group = "evaluation" if role == "reference_orbit" else "estimation"
            destination = root / group / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            assert stream is not None
            with stream, destination.open("wb") as output:
                shutil.copyfileobj(stream, output, length=1024 * 1024)
            entry = artifact(destination, role, archive_member=member.name,
                             product=match[1], mission="GRACE-FO-1")
            (evaluation if group == "evaluation" else estimation).append(entry)
    for role in ("gnss_observations", "attitude"):
        if not any(item["role"] == role for item in estimation):
            raise ValueError(f"bundle lacks {role} for GRACE-FO-1 on {date}")
    if not any(item["role"] == "reference_orbit" for item in evaluation):
        raise ValueError("bundle lacks the separately stored comparison orbit")
    return {"estimation_inputs": estimation, "evaluation_inputs": evaluation}


def _cached_day_product(url, cache_path, destination, *, download=True):
    """Verify a shared acquired product, then copy it into one isolated job.

    Per-product advisory locking prevents concurrent mask jobs from sharing a
    partially written download. Existing destination acquisition records can
    seed an empty relocated cache without network access or provenance changes.
    """
    import fcntl
    cache_path,destination=Path(cache_path).resolve(),Path(destination).resolve()
    cache_path.parent.mkdir(parents=True,exist_ok=True)
    with cache_path.with_name(cache_path.name+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not cache_path.exists() and destination.exists():
            previous=fetch_url(url,destination,download=False)
            shutil.copy2(destination,cache_path)
            shutil.copy2(destination.with_name(destination.name+'.source.json'),
                         cache_path.with_name(cache_path.name+'.source.json'))
        record=fetch_url(url,cache_path,download=download)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            if sha256_file(destination)!=record['sha256']:
                raise ValueError(f'isolated product changed: {destination}')
        else:
            shutil.copy2(cache_path,destination)
        sidecar=destination.with_name(destination.name+'.source.json')
        original=cache_path.with_name(cache_path.name+'.source.json')
        if not sidecar.exists():shutil.copy2(original,sidecar)
        elif json.loads(sidecar.read_text())['sha256']!=record['sha256']:
            raise ValueError(f'isolated acquisition record changed: {sidecar}')
    return {**record,'path':str(destination),'cache_path':str(cache_path)}


def flight_arc(date: str) -> dict:
    """UTC calendar day expressed on the mission's GPS/J2000 time axis."""
    day = Date.fromisoformat(date)
    if day.year != 2024:
        raise ValueError("GPS minus UTC is pinned to 18 seconds for the 2024 campaign")
    midnight = (datetime.fromisoformat(date)-datetime(2000, 1, 1, 12)).total_seconds()
    return {"time_scale": "UTC", "utc_start": date+"T00:00:00Z",
            "utc_end": (day+timedelta(days=1)).isoformat()+"T00:00:00Z",
            "gps_minus_utc_seconds": 18, "gps_start_offset_seconds": 18,
            "start_gps_seconds_since_j2000": midnight+18,
            "end_gps_seconds_since_j2000": midnight+86418,
            "duration_seconds": 86400, "interval_convention": "[start,end)"}


def _row_gps_seconds(row, product):
    return float(row[0]) + (float(row[1])*1e-6 if product in ("GPS1B", "THR1B", "MAS1B") else 0.)


def _write_l1b(path, header, rows, product):
    """Keep mission column semantics, updating selection metadata and count."""
    header, count = re.subn(r"(num_records:\s*)\d+", lambda m:m[1]+str(len(rows)), header, count=1)
    if count != 1:
        raise ValueError("L1B num_records header missing")
    if rows:
        times = [_row_gps_seconds(line.split(), product) for line in rows]
        for name,value in (("start_time_epoch_secs",min(times)),("stop_time_epoch_secs",max(times))):
            header = re.sub(r"("+name+r":\s*)[^\n]+", lambda m:m[1]+format(value,'.6f'),header)
        for name,value in (("time_coverage_start",min(times)),("time_coverage_stop",max(times))):
            stamp=(datetime(2000,1,1,12)+timedelta(seconds=value)).isoformat(timespec='microseconds')
            header=re.sub(r"("+name+r":\s*)[^\n]+",lambda m:m[1]+stamp,header)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(header+"\n".join(rows)+("\n" if rows else ""))
    return path


def read_gps_osb(path):
    """Match native GPS OSB selection: first phase bias per frequency, metres.

    GROOPS strips phase attributes; absent bias entries compute to zero. Code
    attributes remain distinct. This parser never estimates biases from data.
    """
    result={};opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='latin1') as stream:
        for line in stream:
            if not line.startswith(' OSB') or line[11:12]!='G' or line[15:24].strip():continue
            prn,signal,unit=line[11:14],line[25:28],line[65:69].strip()
            if signal[0] not in ('C','L'):continue
            key=signal[:2] if signal.startswith('L') else signal
            value=float(line[70:91])
            if unit=='ns':value*=1e-9*299792458.
            elif unit=='cyc':
                frequency={'1':1575.42e6,'2':1227.60e6,'5':1176.45e6}.get(signal[1])
                if frequency is None:raise ValueError('unsupported GPS OSB frequency')
                value*=299792458./frequency
            else:raise ValueError('unsupported GPS OSB unit: '+unit)
            result.setdefault(prn,{}).setdefault(key,value)
    if not result:raise ValueError('no GPS satellite OSBs in '+str(path))
    return result


def normalize_boundary_osb(line, base_biases, active_biases):
    """y'=y+b_base-b_active gives y'-b_base=y-b_active in native residuals."""
    fields=line.split();prn=f'G{int(fields[3]):02d}';flags=int(fields[5],2)
    if prn not in base_biases or prn not in active_biases:
        raise ValueError('missing boundary OSB transmitter '+prn)
    mapping={0:'C1C',1:'C1W',2:'C2W',3:'L1',4:'L1',5:'L2'}
    corrections={};cursor=7
    for bit in range(16):
        if not flags & (1<<bit):continue
        if bit in mapping:
            signal=mapping[bit];delta=base_biases[prn].get(signal,0.)-active_biases[prn].get(signal,0.)
            fields[cursor]=format(float(fields[cursor])+delta,'.17g')
            corrections[str(bit)]={"native_signal":signal,"added_m":delta,
                "base_bias_m":base_biases[prn].get(signal,0.),"active_bias_m":active_biases[prn].get(signal,0.)}
        cursor+=1
    return ' '.join(fields),corrections


def assemble_utc_mission_inputs(date, day_inputs, next_inputs, output_dir, bias_paths):
    """Merge two GPS products to one UTC day without using any reference orbit."""
    arc=flight_arc(date);start=arc['start_gps_seconds_since_j2000'];end=arc['end_gps_seconds_since_j2000']
    root=Path(output_dir);estimation=[];ledger=[];primary_midnight=start-18
    biases=[read_gps_osb(p) for p in bias_paths]
    for product,role in (("GPS1B","gnss_observations"),("SCA1B","attitude"),("THR1B","spacecraft_metadata"),("MAS1B","spacecraft_metadata")):
        selected=[];sources=[];header=None
        for bundle in (day_inputs,next_inputs):
            matches=[x for x in bundle['estimation_inputs'] if x.get('product')==product and x['path'].endswith('.txt')]
            if len(matches)!=1:raise ValueError('missing/ambiguous UTC boundary product '+product)
            entry=matches[0];h,lines=_gps1b_text(entry['path']);header=header or h;sources.append(entry)
            for line in lines:
                row=line.split();t=_row_gps_seconds(row,product)
                overlap=product=='THR1B' and t<start and t+max(map(float,row[18:32]),default=0.)/1000>=start
                # Attitude carries the terminal support epoch for a closed
                # integration grid. Measurement and screening arcs stay [start,end).
                endpoint=product=='SCA1B' and t==end
                if not (start<=t<end or overlap or endpoint):continue
                if product=='GPS1B' and t>=primary_midnight+86400:
                    line,corrections=normalize_boundary_osb(line,biases[0],biases[1])
                    ledger.append({'gps_seconds_since_j2000':t,'prn':int(row[3]),'corrections':corrections})
                selected.append((t,line))
        selected.sort(key=lambda item:item[0])
        rows=[item[1] for item in selected]
        path=_write_l1b(root/f'{product}_{date}_C_04.utc.txt',header,rows,product)
        estimation.append(artifact(path,role,product=product,mission='GRACE-FO-1',arc=arc,
            source_inputs=[{'path':x['path'],'sha256':x['sha256']} for x in sources],records=len(rows),
            reference_inputs_used=False))
        if product=='SCA1B':
            times=[x[0] for x in selected]
            if len(times)!=86401 or times[0]!=start or times[-1]!=end or any(b-a!=1 for a,b in zip(times,times[1:])):
                raise ValueError('UTC SCA boundary coverage is incomplete or not the expected1Hz grid')
    correction=root/'boundary_osb_normalization.json'
    write_json(correction,{'schema_version':1,'arc':arc,'corrections':ledger,
        'formula':'normalized_observation = raw_observation + primary_day_bias - active_day_bias',
        'native_sign_evidence':'GnssObservationEquation subtracts transmitter antennaVariations; GnssTransceiver::antennaVariations adds signalBias.compute(types)',
        'native_phase_policy':'strip phase attributes; first entry per frequency; missing native bias defaults to zero',
        'bias_inputs':[{'path':str(Path(p).resolve()),'sha256':sha256_file(p)} for p in bias_paths],
        'phase_track_policy':'do not insert slips or reset ambiguities at product-day boundary',
        'reference_inputs_used':False,'observation_estimated_biases_used':False})
    estimation.append(artifact(correction,'force_auxiliary',metadata={'kind':'known_gnss_osb_datum_normalization'}))
    return {'estimation_inputs':estimation,'arc':arc,'normalization':str(correction)}


def merge_gnss_products(paths, output_path, kind, *, next_day_limit_seconds=3600):
    """Stitch provider rows at their GPS epochs; later day wins exact overlaps."""
    paths=list(map(Path,paths));texts=[]
    for p in paths:
        opener=gzip.open if str(p).endswith('.gz') else open
        with opener(p,'rt',encoding='latin1') as f:texts.append(f.read())
    rows={};header=[];footer=[];product_start_dates={}
    def epoch_key(tokens):
        return (*map(int,tokens[:5]),float(tokens[5]))
    def keep(key,index):
        if not index:return True
        # SP3 may contain the NEXT midnight in addition to its nominal GPS day.
        # Bound by elapsed time from this product's first date, not time-of-day.
        day=product_start_dates.setdefault(index,datetime(*key[:3]))
        epoch=datetime(*key[:5])+timedelta(seconds=key[5])
        return 0 <= (epoch-day).total_seconds() <= next_day_limit_seconds
    if kind=='gnss_orbits':
        for index,text in enumerate(texts):
            block=[];key=None;head=[]
            for line in text.splitlines():
                if line.startswith('* '):
                    if key is not None and keep(key,index):rows[key]=block
                    key=epoch_key(line[1:].split());block=[line]
                elif line.startswith('EOF'):break
                elif key is None:head.append(line)
                else:block.append(line)
            if key is not None and keep(key,index):rows[key]=block
            if not index:header=head
        if header and header[0].startswith('#'):
            header[0]=header[0][:32]+f'{len(rows):7d}'+header[0][39:]
        footer=['EOF']
    elif kind=='gnss_clocks':
        for index,text in enumerate(texts):
            lines=text.splitlines();end=next(i for i,x in enumerate(lines) if 'END OF HEADER' in x)
            if not index:header=lines[:end+1]
            for line in lines[end+1:]:
                if not line.startswith('AS '):continue
                f=line.split();epoch=epoch_key(f[2:8])
                if keep(epoch,index):rows[(*epoch,f[1])]=[line]
    elif kind=='gnss_attitudes':
        for index,text in enumerate(texts):
            lines=text.splitlines();begin=next(i for i,x in enumerate(lines) if x.startswith('+EPHEMERIS/DATA'))
            if not index:header=lines[:begin+1]
            block=[];key=None
            for line in lines[begin+1:]:
                if line.startswith('-EPHEMERIS/DATA'):break
                if line.startswith('##'):
                    if key is not None and keep(key,index):rows[key]=block
                    key=epoch_key(line[2:].split()[:6]);block=[line]
                elif key is not None:block.append(line)
            if key is not None and keep(key,index):rows[key]=block
        footer=['-EPHEMERIS/DATA','%END_ORBEX']
    else:raise ValueError('unsupported product stitching: '+kind)
    if not rows:raise ValueError('empty stitched '+kind)
    def stamp(key):return datetime(*key[:5])+timedelta(seconds=key[5])
    first,last=stamp(min(rows)),stamp(max(rows))
    if kind=='gnss_attitudes':
        for i,line in enumerate(header):
            if line.startswith(' END_TIME'):
                header[i]=' END_TIME            '+last.strftime('%Y %m %d %H %M %S.000000000000')
    output=Path(output_path);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('\n'.join(header+[line for key in sorted(rows) for line in rows[key]]+footer)+'\n',encoding='latin1')
    return artifact(output,kind,source_inputs=[{'path':str(p.resolve()),'sha256':sha256_file(p)} for p in paths],
        known_product_stitching=True,duplicate_epoch_policy='later GPS day wins',next_day_support_seconds=next_day_limit_seconds,
        coverage_gps_seconds_since_j2000=[(t-datetime(2000,1,1,12)).total_seconds() for t in (first,last)])


def prepare_flight_day(date: str, cache_dir: str | Path, prepared_dir: str | Path,
                       *, allow_frozen_evaluation: bool = False, download: bool = True) -> dict:
    stage = validate_flight_date(date, allow_frozen_evaluation=allow_frozen_evaluation)
    cache, root = Path(cache_dir).resolve(), Path(prepared_dir).resolve()
    adjacent=(Date.fromisoformat(date)+timedelta(days=1)).isoformat()
    # Only the explicitly authorized base UTC date grants boundary support; this
    # does not authorize fitting or inspecting an adjacent evaluation day.
    sources=[];daily=[];products={}
    suffixes={"gnss_orbits":"05M_ORB.SP3","gnss_clocks":"30S_CLK.CLK",
              "gnss_biases":"01D_OSB.BIA","gnss_attitudes":"30S_ATT.OBX"}
    for day in (date,adjacent):
        filename=f"gracefo_1B_{day}_RL04.ascii.noLRI.tgz"
        source=_cached_day_product(GFZ_L1B+filename,cache/filename,cache/filename,download=download)
        sources.append(source)
        daily.append(extract_gracefo_bundle(source['path'],root/'raw_gps_days'/day,day))
        doy=Date.fromisoformat(day).timetuple().tm_yday
        products[day]={}
        for role,suffix in suffixes.items():
            name=f"COD0OPSFIN_2024{doy:03d}0000_01D_{suffix}.gz"
            rec=_cached_day_product(CODE_PRODUCTS+name,cache/'gnss'/name,root/'raw_gps_days'/day/'gnss'/name,download=download)
            sources.append(rec);products[day][role]=rec['path']
    assembly=assemble_utc_mission_inputs(date,daily[0],daily[1],root/'estimation',
        [products[day]['gnss_biases'] for day in (date,adjacent)])
    inputs={'estimation_inputs':assembly['estimation_inputs'],
            'evaluation_inputs':[entry for bundle in daily for entry in bundle['evaluation_inputs']]}
    for role in ('gnss_orbits','gnss_clocks','gnss_attitudes'):
        suffix={'gnss_orbits':'SP3','gnss_clocks':'CLK','gnss_attitudes':'OBX'}[role]
        inputs['estimation_inputs'].append(merge_gnss_products([products[day][role] for day in (date,adjacent)],
            root/'estimation'/'gnss'/f'UTC_{date}.{suffix}',role))
    inputs['estimation_inputs'].append(artifact(products[date]['gnss_biases'],'gnss_biases',
        datum_policy='primary GPS-day OSB; appended observations normalized by archived known bias difference'))
    slr_name=f"gracefo1_{date.replace('-', '')}.np2"
    laser=_cached_day_product(EDC_SLR+slr_name,cache/'slr'/slr_name,root/'evaluation'/slr_name,download=download)
    sources.append(laser)
    inputs['evaluation_inputs'].append(artifact(laser['path'],'slr_validation',source_url=laser['url']))
    manifest={"schema_version":2,"status":"observations_ready","date":date,"arc":assembly['arc'],
        "stage":stage,"mission":"GRACE-FO-1","sources":sources,"support_gps_dates":[date,adjacent],
        "boundary_osb_normalization":assembly['normalization'],
        "reference_policy":"Both GNV1B GPS-day files are evaluation-only and remain unparsed until evaluation; GNSS-only bootstrap follows masking",
        "missing":["verified_auxiliary_models","masked_gnss_only_bootstrap","native_conversion"],**inputs}
    by_role={entry['role']:entry for entry in inputs['estimation_inputs']}
    orbits=read_sp3(by_role['gnss_orbits']['path']);clocks=read_clock(by_role['gnss_clocks']['path'])
    start,end=manifest['arc']['start_gps_seconds_since_j2000'],manifest['arc']['end_gps_seconds_since_j2000']
    complete=sorted(prn for prn in set(orbits)&set(clocks)
        if orbits[prn][0,0]<=start-1 and orbits[prn][-1,0]>=end+1
        and clocks[prn][0,0]<=start-1 and clocks[prn][-1,0]>=end+1)
    if len(complete)<5:raise ValueError('fewer than five transmitters bracket the entire UTC arc in orbit and clock products')
    manifest['transmitter_coverage']={'complete_orbit_clock_prns':complete,
        'requirement':'each listed orbit/clock brackets [UTC arc start minus1s, UTC arc end plus1s] in GPS time',
        'derived_products':[{'role':role,'path':by_role[role]['path'],'sha256':by_role[role]['sha256']} for role in ('gnss_orbits','gnss_clocks','gnss_attitudes')]}
    manifest['screening']=screen_flight_inputs(manifest,root/'screening.json')
    if manifest['screening']['status']!='eligible':manifest['status']='excluded'
    write_json(root/'data_manifest.json',manifest)
    return manifest


def screen_flight_inputs(manifest: dict, output_path=None) -> dict:
    """Fixed metadata-only maneuver/instrument gate, before orbit initialization.

    Orbital thruster firing, unresolved thruster timing, malformed instruments
    and unavailable THR1B exclude the fixed day; excluded dates are not replaced.
    Routine attitude-control firings and documented SCA interpolation/single-
    camera flags are counted, without excluding otherwise valid mission data.
    """
    from collections import Counter
    import numpy as np
    records = manifest["estimation_inputs"]
    reasons, counts, evidence = [], {}, []
    def product(name):
        found = [x for x in records if Path(x["path"]).name.startswith(name) and Path(x["path"]).suffix == ".txt"]
        if len(found) != 1:
            reasons.append(f"missing_or_ambiguous_{name}")
            return []
        evidence.append({"path": found[0]["path"], "sha256": found[0]["sha256"]})
        return [line.split() for line in _gps1b_text(found[0]["path"])[1]]
    thr = product("THR1B")
    try:
        flags = [int(row[46], 2) for row in thr]
        orbital = [row for row in thr if float(row[30]) > 0 or float(row[31]) > 0]
        cumulative = [int(row[44]) for row in thr]
        if orbital or any(a != b for a,b in zip(cumulative,cumulative[1:])):
            reasons.append("orbital_control_thruster_activity")
        if any(flag & 0b11000011 for flag in flags) or any(row[2] != "G" for row in thr):
            reasons.append("unresolved_thruster_timing_or_on_time")
        counts["thruster"] = {"records": len(thr), "orbital_control_events": len(orbital),
            "attitude_control_events": sum(any(float(x)>0 for x in row[18:30]) for row in thr),
            "quality_flags": dict(Counter(str(f) for f in flags)),
            "orbit_control_accumulated_duration_ms": cumulative,
            "event_gps_seconds": [float(row[0])+1e-6*float(row[1]) for row in thr]}
    except (IndexError, ValueError): reasons.append("malformed_thruster_record")
    sca = product("SCA1B")
    try:
        flags = [int(row[8],2) for row in sca]
        q = np.asarray([[float(v) for v in row[3:7]] for row in sca])
        if not len(q) or not np.isfinite(q).all() or np.max(abs(np.linalg.norm(q,axis=1)-1)) > 1e-5:
            reasons.append("invalid_attitude_quaternion")
        if any(flag & ~0b00001011 for flag in flags): reasons.append("unsupported_attitude_quality_flags")
        counts["attitude"] = {"records":len(sca),"quality_flags":dict(Counter(str(f) for f in flags)),
            "known_flag_policy":"count documented interpolation/IMU/single-camera flags; reject undefined flags or invalid quaternion"}
    except (IndexError,ValueError): reasons.append("malformed_attitude_record")
    gps = product("GPS1B")
    try:
        flags=[int(row[6],2) for row in gps]
        counts["gnss"]={"records":len(gps),"quality_flags":dict(Counter(str(f) for f in flags)),
            "low_snr_records":sum(bool(f & 0b00110000) for f in flags),
            "phase_break_or_cycle_slip_records":sum(bool(f & 15) for f in flags),
            "policy":"drop low-SNR and provider phase-break/cycle-slip records before native conversion; native receiver preprocessing also detects track discontinuities"}
    except (IndexError,ValueError): reasons.append("malformed_gnss_record")
    result={"status":"excluded" if reasons else "eligible","date":manifest.get("date"),
        "exclusion_reasons":sorted(set(reasons)),"counts":counts,"sources":evidence,
        "selection_basis":"THR1B orbital-control on-times, timing flags, SCA/GPS instrument metadata only; no reference or fit residuals",
        "replacement_date_allowed":False,"arc":manifest.get("arc"),
        "screening_scope":"assembled UTC interval including thruster events overlapping the start" if manifest.get("arc") else "input GPS day"}
    if output_path: write_json(output_path,result)
    return result


def verify_manifest(manifest: dict) -> None:
    estimation_paths = set()
    for group in ("estimation_inputs", "evaluation_inputs"):
        for entry in manifest.get(group, []):
            path = Path(entry["path"])
            if not path.is_file() or sha256_file(path) != entry["sha256"]:
                raise ValueError(f"missing or changed input: {path}")
            if group == "estimation_inputs":
                if entry["role"] in ("reference_orbit", "slr_validation", "truth") or path.name.startswith("GNV"):
                    raise ValueError("evaluation material must not enter estimation inputs")
                estimation_paths.add(path.resolve())
                if entry["role"] == "bootstrap_orbit" and entry.get("provenance") != "gnss_only":
                    raise ValueError("bootstrap orbit must be derived from retained GNSS observations")
            elif path.resolve() in estimation_paths:
                raise ValueError("the same file appears in estimation and evaluation inputs")


def _directory_links(relative: str) -> list[str]:
    url = GROOPS_DATA + quote(relative.rstrip("/") + "/", safe="/")
    html = urlopen(url, timeout=60).read().decode()
    return [x for x in re.findall(r'href=["\x27]([^"\x27]+)', html)
            if not x.startswith(("?", "/", "http")) and x not in ("../", "./")]


def reuse_auxiliary_manifest(output_dir, name="auxiliary_manifest.json", *, relocate=False):
    """Reuse a frozen URL/checksum selection; relocation is explicit and offline."""
    root=Path(output_dir).resolve();path=root/name
    manifest=json.loads(path.read_text())
    if manifest.get("status")!="complete":raise ValueError("cached auxiliary selection is incomplete")
    sources=[]
    for source in manifest["sources"]:
        if not source["url"].startswith(GROOPS_DATA):raise ValueError("unrecognized auxiliary source URL")
        relative=PurePosixPath(unquote(source["url"][len(GROOPS_DATA):]))
        if relative.is_absolute() or ".." in relative.parts:raise ValueError("unsafe auxiliary relative path")
        target=root/relative
        recorded = Path(source["path"]).resolve()
        same_file = recorded == target or (recorded.exists() and target.exists() and recorded.samefile(target))
        if not relocate and not same_file:
            raise ValueError("auxiliary manifest needs explicit offline relocation")
        checked=fetch_url(source["url"],target,expected_sha256=source["sha256"],download=False)
        sources.append({**source,**checked,"path":str(target)})
    # The returned view uses the verified requested root even when a platform
    # exposes a second spelling of the same directory. Only explicit relocation
    # rewrites the frozen manifest on disk.
    manifest={**manifest,"sources":sources}
    if relocate:
        write_json(path,manifest)
    return manifest


def fetch_example_auxiliary(scenario_dir: str | Path, output_dir: str | Path,
                             *, download: bool = True) -> dict:
    """Fetch once, then verify and reuse the frozen example model selection."""
    scenario, root = Path(scenario_dir), Path(output_dir).resolve()
    if (root/"auxiliary_manifest.json").exists() or not download:
        return reuse_auxiliary_manifest(root)
    relative_paths = set()
    for file in sorted(scenario.glob("*.xml")):
        tree = ET.parse(file)
        for parent in tree.getroot().iter():
            for child in list(parent):
                if child.attrib.get("disabled") == "1":
                    parent.remove(child)
        text = ET.tostring(tree.getroot(), encoding="unicode")
        relative_paths.update(re.findall(r"\{groopsDataDir\}/([^<]+)", text))
    expanded = set()
    for relative in sorted(relative_paths):
        if "{prn}" in relative:
            expanded.update(relative.replace("{prn}", f"G{i:02d}") for i in range(1, 33))
        elif "{svn}" in relative:
            directory, pattern = relative.rsplit("/", 1)
            expanded.update(directory + "/" + n for n in _directory_links(directory)
                            if fnmatch(n, pattern.replace("{svn}", "G*")))
        elif relative == "thermosphere/hwm14":
            expanded.update(relative + "/" + n for n in _directory_links(relative) if not n.endswith("/"))
        else:
            expanded.add(relative)
    expanded.add("DISCLAIMER.txt")
    def fetch(relative):
        return fetch_url(GROOPS_DATA + quote(relative, safe="/"), root / relative, download=download)
    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = list(pool.map(fetch, sorted(expanded)))
    manifest = {"schema_version": 1, "status": "complete", "sources": sources,
                "total_bytes": sum(item["bytes"] for item in sources),
                "source_url": GROOPS_DATA, "selection": "active official example XML references"}
    write_json(root / "auxiliary_manifest.json", manifest)
    return manifest


def normalize_mask(mask: dict | None) -> dict:
    mask = mask or {}
    number = lambda x: int(x) if float(x).is_integer() else float(x)
    cadence = number(mask.get("cadence_seconds", 30))
    intervals = sorted([[number(a), number(b)] for a, b in mask.get("intervals_seconds", [])])
    scale = mask.get("time_scale", "UTC")
    if scale not in ("UTC", "GPS", "elapsed"):
        raise ValueError("mask time_scale must be UTC, GPS, or elapsed")
    if cadence <= 0 or 86400 % cadence:
        raise ValueError("cadence must be positive and divide one day")
    for i, (a, b) in enumerate(intervals):
        if not (0 <= a < b <= 86400) or (i and a < intervals[i-1][1]):
            raise ValueError("mask intervals must be disjoint and within the GPS day")
    return {"intervals_seconds": intervals, "cadence_seconds": cadence, "time_scale": scale}


def _gps1b_text(path: str | Path) -> tuple[str, list[str]]:
    text = Path(path).read_text()
    marker = "# End of YAML header\n"
    if marker not in text:
        raise ValueError("expected the GRACE-FO RL04 ASCII YAML header")
    header, body = text.split(marker, 1)
    return header + marker, [line for line in body.splitlines() if line.strip()]


def split_gps1b(path: str | Path, date: str, output_dir: str | Path, mask: dict | None,
                 *, arc_start_offset_seconds=0., duration_hours=24.) -> dict:
    """Remove held-out epochs before any data-dependent bootstrap/preprocessing."""
    mask = normalize_mask(mask)
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    header, lines = _gps1b_text(path)
    origin = datetime(2000, 1, 1, 12)
    midnight = (datetime.fromisoformat(date) - origin).total_seconds()
    if mask["time_scale"] == "UTC" and not date.startswith("2024-"):
        raise ValueError("UTC-to-GPS offset is pinned to the 2024 campaign")
    offset = 18 if mask["time_scale"] == "UTC" else 0
    retained, heldout = [], []
    quality_excluded = 0
    for line in lines:
        fields = line.split()
        if int(fields[6], 2) & 0b00111111:
            quality_excluded += 1
            continue
        t = int(fields[0]) + int(fields[1]) * 1e-6 - midnight
        if not arc_start_offset_seconds <= t < arc_start_offset_seconds+duration_hours*3600 or abs(t / mask["cadence_seconds"] - round(t / mask["cadence_seconds"])) > 1e-6:
            continue
        hidden = any(a + offset <= t < b + offset for a, b in mask["intervals_seconds"])
        (heldout if hidden else retained).append(line)
    if not retained:
        raise ValueError("mask leaves no observations")
    result = {"mask": mask, "mask_hash": canonical_hash(mask), "source_sha256": sha256_file(path),
              "provider_quality_excluded_records": quality_excluded}
    for name, rows in (("retained", retained), ("heldout", heldout)):
        destination = root / f"GPS1B_{date}_C_04.{name}.txt"
        adjusted_header, count = re.subn(r"(num_records:\s*)\d+", lambda m: m[1] + str(len(rows)), header, count=1)
        if count != 1:
            raise ValueError("GPS1B record-count header was not found")
        destination.write_text(adjusted_header + "\n".join(rows) + ("\n" if rows else ""))
        result[name] = artifact(destination, "gnss_observations" if name == "retained" else "heldout_gnss_code",
                                mask_hash=result["mask_hash"], records=len(rows),
                                source_sha256=result["source_sha256"])
    write_json(root / "mask_manifest.json", result)
    return result


def read_gps1b_code(path: str | Path) -> dict:
    """Ionosphere-free P1/P2 code for initialization/scoring; no orbit products."""
    import numpy as np
    _, lines = _gps1b_text(path)
    observations = {}
    alpha = (1575.42 / 1227.60) ** 2
    for line in lines:
        f = line.split()
        flags, quality = int(f[5], 2), int(f[6], 2)
        if f[2] != "C" or int(f[4]) != 0 or (flags & 7) != 7 or quality & 0b00110000:
            continue
        values = iter(f[7:])
        fields = {i: float(next(values)) for i in range(16) if flags & (1 << i)}
        code = (alpha * fields[1] - fields[2]) / (alpha - 1)
        if not np.isfinite(code) or not 1e6 < code < 5e7:
            continue
        t = int(f[0]) + int(f[1]) * 1e-6
        observations.setdefault(t, []).append((f"G{int(f[3]):02d}", code))
    return observations


def read_sp3(path: str | Path) -> dict:
    """GPS positions and clocks in SP3's TRF/GPS-time convention, SI units."""
    import numpy as np
    origin = datetime(2000, 1, 1, 12)
    opener = gzip.open if str(path).endswith(".gz") else open
    records = {}
    with opener(path, "rt") as stream:
        for line in stream:
            if line.startswith("* "):
                f = line[1:].split()
                time = (datetime(*map(int, f[:5])) - origin).total_seconds() + float(f[5])
            elif line.startswith("PG"):
                sat = line[1:4]
                value = [float(line[i:i+14]) for i in (4, 18, 32, 46)]
                if all(abs(v) < 999999 for v in value[:3]):
                    records.setdefault(sat, []).append([time, *(v*1000 for v in value[:3]), value[3]*1e-6])
    return {sat: np.asarray(rows) for sat, rows in records.items()}


def read_clock(path: str | Path) -> dict:
    import numpy as np
    origin = datetime(2000, 1, 1, 12)
    opener = gzip.open if str(path).endswith(".gz") else open
    records = {}
    with opener(path, "rt") as stream:
        for line in stream:
            if line.startswith("AS G"):
                f = line.split()
                t = (datetime(*map(int, f[2:7])) - origin).total_seconds() + float(f[7])
                records.setdefault(f[1], []).append([t, float(f[9].replace("D", "E"))])
    return {sat: np.asarray(rows) for sat, rows in records.items()}


def code_bootstrap(retained_gps1b: str | Path, sp3: str | Path, clock: str | Path,
                   date: str, output_path: str | Path, *, mask: dict | None = None,
                   integration_step_seconds: float = 5., duration_hours: float = 24., arc_start_offset_seconds: float = 0., include_endpoint: bool = False) -> dict:
    """Code-only SPP bootstrap; simple corrections suffice ONLY for initialization.

    The native GNSS estimator subsequently applies its complete correction model.
    Unobserved epochs are filled from the retained-data state using central+J2
    propagation; reference orbits never enter this function.
    """
    import numpy as np
    from scipy.integrate import solve_ivp
    from scipy.interpolate import BarycentricInterpolator, CubicSpline
    mask = normalize_mask(mask)
    duration_seconds = float(duration_hours)*3600
    if not 0 < duration_seconds <= 86400 or integration_step_seconds <= 0 or duration_seconds % integration_step_seconds:
        raise ValueError("integration step must be positive and divide a day")
    orbit, clocks, obs = read_sp3(sp3), read_clock(clock), read_gps1b_code(retained_gps1b)
    c, omega = 299792458., 7.292115e-5
    last_position = np.zeros(3)
    solved, residuals = [], []
    for t, values in sorted(obs.items()):
        if len(values) < 5:
            continue
        points, ranges = [], []
        for sat, pseudorange in values:
            if sat not in orbit or sat not in clocks:
                continue
            tx = t - pseudorange/c
            table = orbit[sat]
            idx = np.searchsorted(table[:, 0], tx)
            start = max(0, min(idx-4, len(table)-9))
            section = table[start:start+9]
            if len(section) < 8 or tx < section[0, 0]-1 or tx > section[-1, 0]+1:
                continue
            abscissa = (section[:, 0]-tx)/300.
            differences = abscissa[:, None]-abscissa[None, :]
            np.fill_diagonal(differences, 1.)
            weights = 1./np.prod(differences, axis=1)
            position = BarycentricInterpolator(abscissa, section[:, 1:4], axis=0, wi=weights)(0.)
            angle = omega*(t-tx)
            rotation = np.array([[np.cos(angle), np.sin(angle), 0], [-np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
            points.append(rotation @ position)
            satclock = np.interp(tx, clocks[sat][:, 0], clocks[sat][:, 1])
            ranges.append(pseudorange + c*satclock)
        if len(points) < 5:
            continue
        points, ranges = np.asarray(points), np.asarray(ranges)
        state = np.r_[last_position, 0.]
        for _ in range(12):
            difference = state[:3] - points
            distances = np.linalg.norm(difference, axis=1)
            design = np.c_[difference / distances[:, None], np.ones(len(points))]
            delta, _, rank, _ = np.linalg.lstsq(design, ranges-distances-state[3], rcond=None)
            state += delta
            if np.linalg.norm(delta) < 1e-4:
                break
        residual = ranges - np.linalg.norm(state[:3]-points, axis=1) - state[3]
        rms = float(np.sqrt(np.mean(residual**2)))
        if rank < 4 or not 6.3e6 < np.linalg.norm(state[:3]) < 8e6 or rms > 100:
            continue
        last_position = state[:3]
        solved.append([t, *state[:3]])
        residuals.append(rms)
    if len(solved) < 12:
        raise ValueError("insufficient GNSS-only bootstrap solutions")
    solved = np.asarray(solved)
    midnight = (datetime.fromisoformat(date)-datetime(2000, 1, 1, 12)).total_seconds()
    grid = midnight + arc_start_offset_seconds + np.arange(0, duration_seconds+(0.5*integration_step_seconds if include_endpoint else 0), integration_step_seconds)
    # Interpolate short missing intervals, propagate long masks in rotating TRF.
    result = np.column_stack([np.interp(grid, solved[:, 0], solved[:, j]) for j in range(1, 4)])
    # Interpolate each observed segment independently; a long withheld interval
    # must not influence the interpolant's endpoint derivatives.
    split_points = np.where(np.diff(solved[:, 0]) > 2*mask["cadence_seconds"])[0]+1
    for segment in np.split(solved, split_points):
        if len(segment) >= 4:
            selected = (grid >= segment[0, 0]) & (grid <= segment[-1, 0])
            result[selected] = CubicSpline(segment[:, 0], segment[:, 1:4], axis=0)(grid[selected])
    mu, radius, j2 = 3.986004418e14, 6378137., 1.08262668e-3
    w = np.array([0., 0., omega])
    def dynamics(_, x):
        r, v = x[:3], x[3:]
        rn = np.linalg.norm(r)
        z2 = (r[2]/rn)**2
        a = -mu*r/rn**3 + 1.5*j2*mu*radius**2/rn**5 * r*np.array([5*z2-1, 5*z2-1, 5*z2-3])
        return np.r_[v, a-2*np.cross(w, v)-np.cross(w, np.cross(w, r))]
    gaps = [(a, b) for a, b in zip(solved[:-1, 0], solved[1:, 0]) if b-a > 2*mask["cadence_seconds"]]
    if solved[0, 0] > grid[0]:
        gaps.insert(0, (grid[0]-mask["cadence_seconds"], solved[0, 0]))
    if solved[-1, 0] < grid[-1]:
        gaps.append((solved[-1, 0], grid[-1]+mask["cadence_seconds"]))
    for a, b in gaps:
        missing = (grid > a) & (grid < b)
        if not missing.any():
            continue
        anchor = np.argmin(abs(solved[:, 0]-a)) if a >= solved[0, 0] else 0
        neighbors = np.argsort(abs(solved[:, 0]-solved[anchor, 0]))[:7]
        t0 = solved[anchor, 0]
        coeff = np.polynomial.polynomial.polyfit((solved[neighbors, 0]-t0)/60., solved[neighbors, 1:4], 5)
        initial = np.r_[solved[anchor, 1:4], coeff[1]/60.]
        direction = -1 if grid[missing][-1] < t0 else 1
        requested = grid[missing][::direction]
        propagation = solve_ivp(dynamics, (t0, requested[-1]), initial, t_eval=requested,
                                method="DOP853", rtol=2e-11, atol=1e-5, max_step=30.)
        if not propagation.success:
            raise ValueError("bootstrap gap propagation failed")
        result[missing] = propagation.y[:3].T[::direction]
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as out:
        out.write("# GNSS-only initialization, TRF positions; GPS-time MJD\n# MJD x y z xx yy zz xy xz yz\n")
        for t, r in zip(grid, result):
            out.write(f"{51544.5+t/86400:.14f} {r[0]:.9f} {r[1]:.9f} {r[2]:.9f} 10000 10000 10000 0 0 0\n")
    entry = artifact(path, "bootstrap_orbit", provenance="gnss_only", mask_hash=canonical_hash(mask),
                     frame="TRF", time_scale="GPS", solved_epochs=len(solved), grid_epochs=len(grid),
                     integration_step_seconds=integration_step_seconds, include_endpoint=include_endpoint,
                     code_residual_rms_median_m=float(np.median(residuals)),
                     input_sha256=[sha256_file(p) for p in (retained_gps1b, sp3, clock)],
                     usage="initialization only; not a measurement or accuracy reference",
                     gap_fill="central+J2 propagation from retained code-only solution")
    write_json(path.with_suffix(".provenance.json"), entry)
    return entry
