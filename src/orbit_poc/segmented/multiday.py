"""Explicit continuous-arc preparation; legacy daily validation is unchanged.

The copied bootstrap and XML adapter retain the existing physical model. Only
interval handling, product coverage and multi-day mask validation differ.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict,is_dataclass
from datetime import datetime,timedelta
from pathlib import Path
import json,math,os,subprocess,re
import xml.etree.ElementTree as ET
import numpy as np
from ..comparison import data as data
from ..comparison.data import (GROOPS_DATA,CODE_PRODUCTS,artifact,canonical_hash,fetch_url,reuse_auxiliary_manifest,sha256_file,verify_manifest,write_json,screen_flight_inputs,read_sp3,read_clock,read_gps1b_code,_gps1b_text)
from ..comparison.groops_config import (_template,_select,_program,_add,_rotation,_resample_at_receiver_epochs,_flight_thermal_step,_official_ar_steps,_flight_event_fields,_extra_exports,_exact_mjd,_save,_pulse_grid)
from ..comparison.synthetic import (write_truth_instruments,receiver_to_gps1b,read_receiver_ascii,write_synthetic_accuracy,SIGNALS,NOISE_MODEL,compact_generation,mixed_force_specification)


def normalize_mask(mask=None):
    value=dict(mask or {})
    if set(value)-{'cadence_seconds','time_scale','duration_seconds','intervals_seconds'}:raise ValueError('Unknown multi-day mask field')
    duration=value.get('duration_seconds',86400)
    cadence=value.get('cadence_seconds',30)
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=259200:raise ValueError('Invalid multi-day duration')
    if type(cadence) not in (int,float) or not math.isfinite(cadence) or cadence<=0 or 86400%cadence:raise ValueError('Invalid multi-day cadence')
    scale=value.get('time_scale','UTC')
    if scale not in ('UTC','GPS','elapsed'):raise ValueError('Invalid mask scale')
    intervals=value.get('intervals_seconds',[])
    for i,pair in enumerate(intervals):
        if len(pair)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in pair):raise ValueError('Invalid mask interval')
        a,b=pair
        if not 0<=a<b<=duration or (i and a<intervals[i-1][1]):raise ValueError('Overlapping or out-of-bounds mask')
    canonical=lambda x:int(x) if float(x).is_integer() else float(x)
    return {'cadence_seconds':canonical(cadence),'time_scale':scale,'duration_seconds':canonical(duration),'intervals_seconds':[[canonical(x) for x in pair] for pair in intervals]}


def product_dates(epoch,hours,margin_seconds=3600):
    start=datetime.fromisoformat(epoch);end=start+timedelta(hours=hours)
    if hours not in (24,48,72) or margin_seconds<3600:raise ValueError('Unsupported interval/product margin')
    first=(start-timedelta(seconds=margin_seconds)).date();last=(end+timedelta(seconds=margin_seconds)).date()
    return [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]


def acquire_products(case,backend,output):
    """Retain every daily source; merge ephemerides with one-hour brackets.

    Synthetic observations and inference use one common first-day OSB datum.
    All daily bias files are retained and checked; no unsupported time-varying
    BSX record is silently passed to GROOPS's time-fixed converter.
    """
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    days=product_dates(case['epoch'],case['duration_hours'],backend.get('interpolation_margin_seconds',3600))
    daily={role:[] for role in ('gnss_orbits','gnss_clocks','gnss_biases','gnss_attitudes')}
    for date in days:
        day=datetime.fromisoformat(date)
        for role,suffix in (('gnss_orbits','05M_ORB.SP3'),('gnss_clocks','30S_CLK.CLK'),('gnss_biases','01D_OSB.BIA'),('gnss_attitudes','30S_ATT.OBX')):
            name=f'COD0OPSFIN_{day.year}{day.timetuple().tm_yday:03d}0000_01D_{suffix}.gz'
            rec=fetch_url(CODE_PRODUCTS+name,Path(backend['cache_dir'])/'gnss'/name)
            daily[role].append(artifact(rec['path'],role,date=date,source_url=rec['url']))
    from .products import audit_daily_products
    boundaries=audit_daily_products(daily,output/'boundary-audit')
    merged=[]
    origin=datetime(2000,1,1,12);start=(datetime.fromisoformat(case['epoch'])-origin).total_seconds();end=start+case['duration_hours']*3600
    for role,kind in (('gnss_orbits','sp3'),('gnss_clocks','clk'),('gnss_attitudes','obx')):
        rec=data.merge_gnss_products([r['path'] for r in daily[role]],output/('merged.'+kind),role,next_day_limit_seconds=86400)
        coverage=rec['coverage_gps_seconds_since_j2000']
        if coverage[0]>start-3600 or coverage[1]<end+3600:raise ValueError('Merged GNSS product lacks interpolation margin')
        merged.append(artifact(rec['path'],role,daily_sources=daily[role],boundary_audit=boundaries,coverage_gps_j2000_seconds=coverage))
    bias=next(x for x in daily['gnss_biases'] if x['date']==case['epoch'][:10])
    for entry in daily['gnss_biases']:
        if not data.read_gps_osb(entry['path']):raise ValueError('Daily GPS bias product has no supported biases')
    merged.append(artifact(bias['path'],'gnss_biases',daily_sources=daily['gnss_biases'],boundary_audit=boundaries,datum='fixed first-day OSB shared by native simulation and inference'))
    write_json(output/'daily-products.json',{'schema':'orbit-poc-segmented-products-v1','dates':days,'products':merged,'daily_sources':daily,'boundary_audit':boundaries})
    return merged


def split_gps1b(path: str | Path, date: str, output_dir: str | Path, mask: dict | None,
                 *, arc_start_offset_seconds=0., duration_hours=24.) -> dict:
    """Remove held-out epochs before any data-dependent bootstrap/preprocessing."""
    mask = normalize_mask({**(mask or {}), "duration_seconds":float(duration_hours)*3600})
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
    mask = normalize_mask({**(mask or {}), "duration_seconds":float(duration_hours)*3600})
    duration_seconds = float(duration_hours)*3600
    if not 0 < duration_seconds <= 259200 or integration_step_seconds <= 0 or duration_seconds % integration_step_seconds:
        raise ValueError("integration step must be positive and divide the continuous arc")
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


def build_arc_configs(data_manifest: dict, scenario_dir: str | Path | None,
                      auxiliary_dir: str | Path, output_dir: str | Path, *,
                      method="groops_pulses", mask=None,
                      pulse_interval_seconds=1200., pulse_sigma_velocity_m_s=1e-4,
                      density_knot_seconds=60., density_tau_seconds=7200.,
                      density_sigma_log=0.3, inputfile_log_density=None,
                      integration_step_seconds=5., duration_hours=24.) -> dict:
    """Prepare native configs; a successful return is not a successful fit.

    Pulse coefficients and their native Gaussian prior use micrometres/second,
    while the public argument is metres/second.  Pulse axes are inertial CRF.
    Shared native preprocessing is based on the same GNSS-only bootstrap; model
    fitting uses fixed nominal measurement sigmas, without residual reweighting.
    """
    verify_manifest(data_manifest)
    if method not in ("groops_pulses", "groops_log_drag_ou", "groops_pulses_ar"):
        raise ValueError("unknown comparison method")
    if not all(math.isfinite(x) and x > 0 for x in
               (pulse_interval_seconds, pulse_sigma_velocity_m_s, density_knot_seconds,
                density_tau_seconds, density_sigma_log)):
        raise ValueError("model intervals and standard deviations must be finite and positive")
    duration_seconds = float(duration_hours)*3600
    if not 0 < duration_seconds <= 259200 or duration_seconds % density_knot_seconds or duration_seconds % pulse_interval_seconds:
        raise ValueError("knot and pulse spacing must divide the continuous arc")
    root, auxiliary = Path(output_dir).resolve(), Path(auxiliary_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if data_manifest.get("mission") == "GRACE-FO-1":
        screening = screen_flight_inputs(data_manifest, root / "flight_screening.json")
        if screening["status"] != "eligible":
            raise ValueError("fixed flight day excluded by metadata screening: " + ", ".join(screening["exclusion_reasons"]))
    date = data_manifest["date"]
    mjd = (datetime.fromisoformat(date)-datetime(1858, 11, 17)).days
    arc = data_manifest.get("arc",{})
    arc_offset=float(arc.get("gps_start_offset_seconds",0.))
    include_endpoint=arc.get("time_scale")=="UTC"
    if not math.isfinite(integration_step_seconds) or integration_step_seconds<=0:
        raise ValueError("integration step must be finite and positive")
    if include_endpoint and (integration_step_seconds>5 or abs(5/integration_step_seconds-round(5/integration_step_seconds))>1e-12):
        raise ValueError("flight integration grid must subdivide the canonical5s attitude grid")
    if data_manifest.get("mission")=="GRACE-FO-1" and (arc.get("time_scale")!="UTC" or arc_offset!=18):
        raise ValueError("flight inputs must be assembled as a verified UTC day")
    mask = normalize_mask({**(mask or {}), "duration_seconds":duration_seconds})
    masked = split_gps1b(_select(data_manifest, "gnss_observations", ".txt"), date,
                         root / "preprocessing", mask,arc_start_offset_seconds=arc_offset,duration_hours=duration_hours)
    bootstrap = code_bootstrap(masked["retained"]["path"], _select(data_manifest, "gnss_orbits"),
                               _select(data_manifest, "gnss_clocks"), date,
                               root / "preprocessing/bootstrap_trf.txt", mask=mask,
                               integration_step_seconds=integration_step_seconds, duration_hours=duration_hours,
                               arc_start_offset_seconds=arc_offset,include_endpoint=include_endpoint)
    # All auxiliary models are verified before constructing any runnable config.
    auxiliary_records = []
    for name in ("auxiliary_manifest.json", "flight_auxiliary_manifest.json"):
        manifest = reuse_auxiliary_manifest(auxiliary, name)
        auxiliary_records.extend(manifest["sources"])
    d = root / "data" / date / "gracefo"
    d.mkdir(parents=True, exist_ok=True)
    paths = {"receiver": d/f"gracefo1_gnssReceiver_{date}.dat",
             "orbit": d/f"gracefo1_orbit_{date}.dat",
             "attitude": d/f"gracefo1_starCamera_{date}.dat",
             "receiver_orbit": d/f"gracefo1_receiverOrbit_{date}.dat",
             "receiver_attitude": d/f"gracefo1_receiverStarCamera_{date}.dat",
             "variational": d/f"gracefo1_variational_{date}.dat"}
    if include_endpoint and integration_step_seconds!=5:
        paths["attitude_integration"]=d/f"gracefo1_starCamera_integration_{date}.dat"
    one = _template("01groopsConvert.xml", scenario_dir, root, auxiliary, date, mjd)
    replacements = {"Sp3Format2Orbit": ("inputfile", "gnss_orbits"),
                    "GnssOrbex2StarCamera": ("inputfileOrbex", "gnss_attitudes"),
                    "GnssClockRinex2InstrumentClock": ("inputfileClockRinex", "gnss_clocks"),
                    "GnssSinexBias2SignalBias": ("inputfileSinexBias", "gnss_biases")}
    for tag, (field, role) in replacements.items():
        for program in one.iter(tag):
            program.find(field).text = _select(data_manifest, role)
            # The pinned GROOPS version removed this unused legacy option.
            for obsolete in list(program.findall("inputfileGlonassSignalDefinition")):
                program.remove(obsolete)
    two = ET.Element("groops")
    p = _program(two, "GraceL1b2GnssReceiver")
    _add(p, "outputfileGnssReceiver", paths["receiver"])
    _add(p, "inputfile", masked["retained"]["path"])
    p = _program(two, "GroopsAscii2Orbit")
    _add(p, "outputfileOrbit", paths["orbit"])
    _rotation(p, auxiliary)
    _add(p, "inputfile", bootstrap["path"])
    # Decimal MJD bootstrap import passes through binary64. Canonicalize times
    # natively before differentiation/integration to avoid sub-microsecond jitter.
    p = _program(two, "InstrumentResample")
    _add(p, "outputfileInstrument", paths["orbit"])
    _add(p, "inputfileInstrument", paths["orbit"])
    interpolation = _add(_add(p, "method"), "polynomial")
    for tag,value in (("polynomialDegree",7),("maxDataPointRange",300),("maxExtrapolationDistance",1)):
        _add(interpolation,tag,value)
    grid = _add(_add(p,"timeSeries"),"uniformSampling")
    _add(grid,"timeStart",mjd)
    endpoint_operator='+' if include_endpoint else '-'
    _add(grid,"timeEnd",f"{mjd}+({duration_hours*3600}{endpoint_operator}{0.5*integration_step_seconds})/86400")
    _add(grid,"sampling",f"{integration_step_seconds}/86400")
    if arc_offset:_add(grid,"offsetSeconds",format(arc_offset,'.17g'))
    p = _program(two, "OrbitAddVelocityAndAcceleration")
    _add(p, "outputfileOrbit", paths["orbit"])
    _add(p, "inputfileOrbit", paths["orbit"])
    _add(p, "polynomialDegree", 7)
    attitude_entry = next(x for x in data_manifest["estimation_inputs"] if x["role"] == "attitude")
    if attitude_entry.get("format", attitude_entry.get("metadata", {}).get("format")) == "groops_instrument":
        p = _program(two, "FileConvert")
        _add(p, "outputfile", paths["attitude"])
        _add(p, "inputfile", attitude_entry["path"])
    else:
        p = _program(two, "GraceL1b2StarCamera")
        _add(p, "outputfileStarCamera", paths["attitude"])
        _add(p, "inputfile", _select(data_manifest, "attitude"))
    p = _program(two, "InstrumentResample")
    _add(p, "outputfileInstrument", paths["attitude"])
    _add(p, "inputfileInstrument", paths["attitude"])
    polynomial = _add(_add(p, "method"), "polynomial")
    for tag, value in (("polynomialDegree", 1), ("maxDataPointRange", 300),
                       ("maxExtrapolationDistance", 100)):
        _add(polynomial, tag, value)
    if include_endpoint:
        # The physical attitude curve is fixed at the canonical5s provider
        # samples, independently of dynamics refinement. GNSS/SLR use this file.
        grid=_add(_add(p,"timeSeries"),"uniformSampling")
        for tag,value in (("timeStart",mjd),("timeEnd",f"{mjd}+({duration_seconds}+2.5)/86400"),
                          ("sampling","5/86400"),("offsetSeconds",format(arc_offset,'.17g'))):_add(grid,tag,value)
        if "attitude_integration" in paths:
            p=_program(two,"InstrumentResample")
            _add(p,"inputfileInstrument",paths["attitude"])
            _add(p,"outputfileInstrument",paths["attitude_integration"])
            polynomial=_add(_add(p,"method"),"polynomial")
            for tag,value in (("polynomialDegree",7),("maxDataPointRange",-8.1),("maxExtrapolationDistance",-1.1)):_add(polynomial,tag,value)
            _add(_add(_add(p,"timeSeries"),"instrument"),"inputfileInstrument",paths["orbit"])
    else:
        _add(_add(_add(p, "timeSeries"), "instrument"), "inputfileInstrument", paths["orbit"])
    # The native LEO receiver matches input geometry within timeMargin=0.1s;
    # it does not interpolate the UTC18+5n dynamics grid onto GPS30n epochs.
    # Derive both inputs from the common bootstrap/canonical attitude, using
    # the converted retained observations as the exact epoch authority.
    _resample_at_receiver_epochs(two, paths["orbit"], paths["receiver_orbit"], paths["receiver"])
    _resample_at_receiver_epochs(two, paths["attitude"], paths["receiver_attitude"], paths["receiver"])
    three = _template("03groopsVariational.xml", scenario_dir, root, auxiliary, date, mjd)
    _flight_thermal_step(three)
    three.find(".//PreprocessingVariationalEquation/inputfileStarCamera").text=str(paths.get("attitude_integration",paths["attitude"]))
    boundaries = _add(_add(three.find(".//PreprocessingVariationalEquation"), "integrationBoundaries"),
                      "uniformSampling")
    _add(boundaries, "timeStart", "loopTime")
    _add(boundaries, "timeEnd", "loopTimeEnd")
    _add(boundaries, "sampling", f"{density_knot_seconds}/86400")
    if arc_offset:_add(boundaries,"offsetSeconds",format(arc_offset,'.17g'))
    # Pre-fit coefficients become unrecorded offsets in the reference trajectory.
    # Keep this initializer to six state components so final pulse priors are
    # centred on physically zero pulses, rather than zero additional increments.
    initializer = three.find(".//PreprocessingVariationalEquationOrbitFit")
    for pulse in list(initializer.findall("stochasticPulse")):
        initializer.remove(pulse)
    four = _template("04groopsGnssProcessing.xml", scenario_dir, root, auxiliary, date, mjd)
    processing = four.find(".//GnssProcessing")
    series = processing.find("timeSeries")
    series.clear()
    uniform = _add(series, "uniformSampling")
    _add(uniform, "timeStart", "loopTime")
    observation_offset=math.ceil(arc_offset/mask['cadence_seconds'])*mask['cadence_seconds']
    end_guard=observation_offset-arc_offset+0.5*mask['cadence_seconds']
    _add(uniform, "timeEnd", f"loopTimeEnd-{end_guard}/86400")
    _add(uniform, "sampling", f"{mask['cadence_seconds']}/86400")
    if observation_offset:_add(uniform,"offsetSeconds",format(observation_offset,'.17g'))
    receiver = processing.find("receiver/lowEarthOrbiter")
    receiver.find("inputfileOrbit").text = str(paths["receiver_orbit"])
    receiver.find("inputfileStarCamera").text = str(paths["receiver_attitude"])
    _add(four.find("global"), "filename", paths["attitude"], label="orbitPocCanonicalAttitude")
    for node in four.iter():
        if node.text: node.text = node.text.replace("igsR3", "igs20")
    for step in list(processing.findall("processingStep")):
        if step.find("resolveAmbiguities") is not None:
            processing.remove(step)
    processing.find("receiver/lowEarthOrbiter/supportsIntegerAmbiguities").text = "0"
    _add(processing.find("receiver/lowEarthOrbiter"),"orbitPocPreprocessFromInputOrbit",1)
    for node in processing.findall(".//estimate/computeWeights") + processing.findall(".//estimate/adjustSigma0"):
        node.text = "0"
    dynamic = processing.find("parametrization/leoDynamicOrbits")
    _add(dynamic, "outputfileParameters", root / "output" / date / "orbit_parameters.txt")
    _add(dynamic, "outputfileCovariance", root / "output" / date / "state_covariance.txt")
    _add(processing.find("parametrization/clocks"), "outputfileClockReceiver",
         root / "output" / date / "receiver_clock.txt")
    final_write = next(s for s in processing.findall("processingStep") if s.find("writeResults") is not None)
    index = list(processing).index(final_write)
    covariance_step = ET.Element("processingStep")
    _add(covariance_step, "computeCovarianceMatrix")
    processing.insert(index, covariance_step)
    residuals = _add(_add(processing, "processingStep"), "writeResiduals")
    _add(_add(residuals, "selectReceivers"), "all")
    _add(residuals, "outputfileResiduals", root / "output" / date / "gnss_residuals.dat")
    # Export the native common measurement recipe before attaching either prior.
    shared_measurement = deepcopy(processing)
    for param in list(shared_measurement.findall("parametrization")):
        if param.find("leoDynamicOrbits") is not None:
            shared_measurement.remove(param)
    for node in shared_measurement.iter():
        if node.text: node.text = node.text.replace(str(root), "{job}")
    base_forces = three.find(".//PreprocessingVariationalEquation/forces")
    nominal_drag = deepcopy(base_forces.find("miscAccelerations/atmosphericDrag"))
    shared_forces = ET.tostring(base_forces, encoding="unicode").replace(str(auxiliary), "{auxiliary}")
    if method in ("groops_pulses", "groops_pulses_ar"):
        for parent in (three, four):
            for pulse in parent.findall(".//stochasticPulse/uniformSampling"):
                pulse.find("timeStart").text = "loopTime"
                pulse.find("timeEnd").text = f"loopTimeEnd-{1.5*pulse_interval_seconds}/86400"
                pulse.find("sampling").text = f"{pulse_interval_seconds:g}/86400"
                _add(pulse,"offsetSeconds",format(arc_offset+pulse_interval_seconds,'.17g'))
        constraint = _add(_add(processing, "parametrization"), "constraints")
        _add(constraint, "name", "constraint.pulses")
        wildcard = _add(_add(constraint, "parameters"), "wildcard")
        for tag, value in (("object", "*"), ("type", "stochasticPulse.*"),
                           ("temporal", "*"), ("interval", "*")):
            _add(wildcard, tag, value)
        _add(constraint, "sigma", pulse_sigma_velocity_m_s * 1e6)
        _add(constraint, "bias", 0)
        _add(constraint, "relativeToApriori", 0)
    else:
        # The nominal drag is the only force scaled by exp(g).
        log_density = Path(inputfile_log_density).resolve() if inputfile_log_density else root / "log_density.txt"
        if not log_density.exists():
            with log_density.open("w") as stream:
                for i in range(round(duration_seconds/density_knot_seconds)+1):
                    stream.write(f"{_exact_mjd(mjd, arc_offset+i*density_knot_seconds)} 0\n")
        for wrapper in base_forces.findall("miscAccelerations"):
            drag = wrapper.find("atmosphericDrag")
            if drag is not None:
                wrapper.remove(drag)
                density = _add(wrapper, "logDensity")
                _add(density, "nominalDrag").append(drag)
                _add(density, "inputfileLogDensity", log_density)
        for parent in (three, four):
            for element in parent.iter():
                for pulse in list(element.findall("stochasticPulse")):
                    element.remove(pulse)
        acceleration = _add(_add(dynamic, "parametrizationAcceleration"), "logDensity")
        _add(acceleration, "nominalDrag").append(nominal_drag)
        _add(acceleration, "inputfileLogDensity", log_density)
        ou = _add(_add(processing, "parametrization"), "logDensityOu")
        _add(ou, "name", "constraint.logDensityOu")
        selector = _add(_add(ou, "parameters"), "wildcard")
        for tag, value in (("object", "*"), ("type", "logDensity"), ("temporal", "*"), ("interval", "*")):
            _add(selector, tag, value)
        _add(ou, "inputfileLogDensity", log_density)
        _add(ou, "tau", density_tau_seconds)
        _add(ou, "sigma", density_sigma_log)
    for tree in (one,three,four):
        _add(tree.find("global"),"double",arc_offset,label="arcStartOffsetSeconds")
    if method == "groops_pulses_ar":
        _official_ar_steps(three, four)
    _flight_event_fields(three,four)
    # Clock support must include bracketing native GPS epochs at both ends.
    for intervals in one.findall(".//GnssClockRinex2InstrumentClock/intervals"):
        intervals.clear(); grid=_add(intervals,"uniformSampling")
        _add(grid,"timeStart","timeStart-1");_add(grid,"timeEnd","timeEnd+1");_add(grid,"sampling",duration_hours/24+2)
    for tree in (one, three, four):
        tree.find("global/time[@label='timeEnd']").text = f"timeStart+{duration_seconds}/86400"
        for interval in tree.findall(".//timeIntervals/timeIntervals/uniformSampling/sampling"):
            interval.text = f"{duration_seconds}/86400"
    _extra_exports(processing, root, date)
    config_paths = {}
    for label, tree in (("convert_gnss", one), ("convert_receiver", two),
                        ("variational", three), ("estimate", four)):
        config_paths[label] = _save(tree, root / f"{label}.xml")
        if "GNV1B" in Path(config_paths[label]).read_text():
            raise AssertionError("reference orbit leaked into estimation XML")
    estimation = [x for x in data_manifest["estimation_inputs"] if x["role"] != "gnss_observations"]
    estimation += [masked["retained"], bootstrap]
    for entry in auxiliary_records:
        role = "earth_orientation" if "/earthRotation/" in entry["path"] else "force_auxiliary"
        estimation.append({**entry, "role": role})
    preprocessing = {"mask": mask, "mask_hash": canonical_hash(mask), "bootstrap": bootstrap,
                     "receiver_conversion": "GraceL1b2GnssReceiver",
                     "observation_cadence_seconds": mask["cadence_seconds"],"arc":arc,
                     "observation_grid":"GPS-midnight multiples, restricted to UTC arc" if arc_offset else "elapsed/GPS grid",
                     "receiver_geometry_grid":"exact retained native GNSS observation epochs",
                     "receiver_attitude_interpolation":"degree7 normalized continuous-sign quaternion interpolation of canonical attitude",
                     "boundary_osb_policy":"known primary-day minus active-day bias added before masking; no track reset" if arc_offset else None,
                     "integration_step_seconds": integration_step_seconds,
                     "epoch_grid": "native uniform sampling after ASCII bootstrap import, before differentiation",
                     "bootstrap_provenance": "gnss_only", "reference_inputs_used": False,
                     "native_outlier_preprocessing": "same code bootstrap and receiver configuration for both models",
                     "estimation_reweighting": method=="groops_pulses_ar", "ambiguity_policy": "integer_native_reference" if method=="groops_pulses_ar" else "float",
                     "preprocessing_geometry":"native dynamic orbit" if method=="groops_pulses_ar" else "immutable masked GNSS-code bootstrap"}
    # Hashes describe common physical/measurement models, excluding the prior.
    common_aux = sorted((Path(x["path"]).relative_to(auxiliary).as_posix(), x["sha256"])
                        for x in auxiliary_records)
    result = {"schema_version": 1, "status": "configured", "method": method, "date": date,
              "output_dir": str(root), "duration_hours": duration_hours, "arc":arc, "configs": config_paths,
              "native_paths": {k: str(v) for k, v in paths.items()},
              "preprocessing_orbit_path":str(paths["receiver_orbit"]),
              "result_paths": {"orbit": str(root / "output" / date / f"gracefo1_orbit_{date}.txt"),
                               "orbit_native": str(root / "output" / date / f"gracefo1_orbit_{date}.dat"),
                               "parameters": str(root / "output" / date / "orbit_parameters.txt"),
                               "covariance": str(root / "output" / date / "state_covariance.txt"),
                               "covariance_observations": str(root / "output" / date / "state_covariance_observations.txt"),
                               "receiver_clock": str(root / "output" / date / "receiver_clock.txt"),
                               "residuals": str(root / "output" / date / "gnss_residuals.dat"),
                               "parameter_covariance": str(root / "output" / date / "parameter_covariance.txt"),
                               "apriori_solution": str(root / "output" / date / "full_apriori_solution.txt"),
                               "parameter_names": str(root / "output" / date / "full_parameter_names.txt"),
                               "phase_recovery": str(root / "output" / date / "phase_recovery.txt"),
                               "preprocessing_audit":str(root/"output"/date/"preprocessing_audit.txt")},
              "estimation_inputs": estimation, "evaluation_inputs": data_manifest.get("evaluation_inputs", []),
              "calibration_inputs": [masked["heldout"]] if masked["heldout"]["records"] else [],
              "force_model_hash": canonical_hash([shared_forces, common_aux]),
              "measurement_model_hash": canonical_hash(ET.tostring(shared_measurement, encoding="unicode")),
              "preprocessing_hash": canonical_hash({"mask": mask,"arc":arc, "bootstrap_sha256": bootstrap["sha256"],
                                                      "retained_sha256": masked["retained"]["sha256"]}),
              "preprocessing": preprocessing, "mask_hash": canonical_hash(mask),
              "metadata": {"pulse_frame": "CRF", "pulse_parameter_unit": "um/s",
                           "pulse_sigma_velocity_m_s": pulse_sigma_velocity_m_s,
                           "pulse_sigma_native_um_s": pulse_sigma_velocity_m_s*1e6,
                           "density_outer_relinearization_required": method == "groops_log_drag_ou",
                           "density_knot_seconds": density_knot_seconds,
                           "integration_step_seconds": integration_step_seconds,
                           "attitude_numerical_model": "canonical5s provider samples with degree7 native interpolation; common to dynamics, GNSS and SLR" if include_endpoint else "synthetic prescribed attitude",
                           "native_execution_verified": False}}
    write_json(root / "preparation_manifest.json", result)
    return result


def simulation_configs(case, instruments, products, output_dir, backend):
    """Build runnable native conversion and observation simulation configs."""
    root = Path(output_dir).resolve()
    auxiliary = Path(backend["auxiliary_dir"]).resolve()
    scenario = backend.get("example_directory") or None
    date = case["epoch"][:10]
    mjd = instruments["mjd_start"]
    convert = _template("01groopsConvert.xml", scenario, root, auxiliary, date, mjd)
    roles = {entry["role"]: entry["path"] for entry in products}
    for tag, field, role in (("Sp3Format2Orbit", "inputfile", "gnss_orbits"),
                             ("GnssClockRinex2InstrumentClock", "inputfileClockRinex", "gnss_clocks"),
                             ("GnssOrbex2StarCamera", "inputfileOrbex", "gnss_attitudes"),
                             ("GnssSinexBias2SignalBias", "inputfileSinexBias", "gnss_biases")):
        for node in convert.iter(tag):
            node.find(field).text = roles[role]
    for interval in convert.findall('.//GnssClockRinex2InstrumentClock/intervals'):
        interval.clear(); uniform=_add(interval,'uniformSampling')
        _add(uniform,'timeStart','timeStart-1');_add(uniform,'timeEnd',f'timeStart+{case["duration_hours"]/24+1}')
        _add(uniform,'sampling',case['duration_hours']/24+2)
    simulate = _template("04groopsGnssProcessing.xml", scenario, root, auxiliary, date, mjd)
    p = simulate.find(".//GnssProcessing")
    p.tag = "GnssSimulateReceiver"
    for node in list(p):
        if node.tag == "processingStep" or (node.tag == "parametrization" and
                any(node.find(tag) is not None for tag in ("leoDynamicOrbits", "ambiguities", "constraints"))):
            p.remove(node)
    for node in p.iter():
        if node.text:
            node.text = node.text.replace("igsR3", "igs20")
    receiver = p.find("receiver/lowEarthOrbiter")
    receiver.find("inputfileOrbit").text = instruments["orbit"]
    receiver.find("inputfileStarCamera").text = instruments["attitude"]
    receiver.find("inputfileAccuracyDefinition").text = write_synthetic_accuracy(root/"synthetic_accuracy.xml")
    receiver.remove(receiver.find("inputfileObservations"))
    receiver.find("supportsIntegerAmbiguities").text = "0"
    # Same-frequency signal ambiguities must differ by full cycles: native
    # preprocessing repairs full-cycle offsets before sharing their ambiguity.
    receiver.find("wavelengthFactor").text = "1"
    series = p.find("timeSeries")
    series.clear()
    uniform = _add(series, "uniformSampling")
    _add(uniform, "timeStart", mjd)
    _add(uniform, "timeEnd", f"{mjd}+({case['duration_hours']}*3600-{case['cadence']})/86400")
    _add(uniform, "sampling", f"{case['cadence']}/86400")
    receiver_output = root / "receiver_unmasked.txt"
    _add(p, "outputfileGnssReceiver", receiver_output)
    _add(p, "outputfileClock", root / "simulated_clock.txt")
    for signal in SIGNALS:
        _add(p, "observationType", signal)
    for tag, sigma, salt in (("noiseObservation", 1., 17011), ("noiseClockReceiver", 30., 29131)):
        white = _add(_add(p, tag), "white")
        _add(white, "sigma", sigma)
        _add(white, "initRandom", int(case["seed"])+salt)
    for tree in (convert,simulate):
        for node in tree.findall("./global/time[@label='timeEnd']"):node.text=f'timeStart+{case["duration_hours"]}/24'
    for tree in (convert,simulate):
        for interval in tree.findall('.//timeIntervals/timeIntervals/uniformSampling/sampling'):interval.text=str(case['duration_hours']/24)
    return {"convert_gnss": _save(convert, root/"convert_transmitters.xml"),
            "simulate": _save(simulate, root/"simulate_receiver.xml"),
            "receiver": str(receiver_output)}


def generate_continuous_case(case, workdir, backend_cfg):
    """Generate real native GNSS measurements; common masked preprocessing follows.

    Returns ``observations_ready``, never a fit or accepted scientific result.
    Native executable and Tudat are required; there is no approximate fallback.
    """
    from ..simulator import generate
    from ..comparison.data import fetch_example_auxiliary
    from ..comparison.groops_config import fetch_flight_auxiliary
    backend = asdict(backend_cfg) if is_dataclass(backend_cfg) else dict(backend_cfg)
    root = Path(workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fetch_example_auxiliary(backend.get("example_directory"), backend["auxiliary_dir"])
    fetch_flight_auxiliary(backend["auxiliary_dir"])
    date = case["epoch"][:10]
    day = datetime.fromisoformat(date)
    if day.year != 2024 or float(case["cadence"]) != 30:
        raise ValueError("Frozen synthetic native protocol requires 2024 products and 30-second GNSS")
    if case['duration_hours'] != 72:raise ValueError('Generate exactly one continuous 72-hour truth arc')
    products = acquire_products(case,backend,root/'products')
    truth_config = {**case, "cadence": 5, "truth_step_seconds": 5, "coverage": "normal", "truth_profile": "controlled"}
    if case.get("truth_model") == "tudat_mixed_force_stress_gnss":
        truth_config["extra_acceleration"] = mixed_force_specification(case["seed"])
    generated = generate(truth_config, root/"generation", truth_backend="tudat",
                         tudat_python=backend.get("tudat_python") or None)
    truth_path = Path(generated["truth"])
    instruments = write_truth_instruments(truth_path, root/"generation", case["epoch"])
    configs = simulation_configs(case, instruments, products, root/"generation", backend)
    conversion = _execute(backend["groops_executable"], configs["convert_gnss"], root/"generation", case["seed"])
    execution = [conversion, _execute(backend["groops_executable"], configs["simulate"], root/"generation", case["seed"])]
    observation_path = root/"observations"/f"GPS1B_{date}_C_synthetic.txt"
    export = receiver_to_gps1b(configs["receiver"], observation_path, seed=case["seed"],
                              mjd_start=instruments["mjd_start"])
    # Store explicit MJD alongside elapsed times for native post-fit comparison.
    with np.load(truth_path, allow_pickle=False) as truth:
        values = {key: truth[key] for key in truth.files}
    values["mjd"] = instruments["mjd_start"] + values["times"]/86400
    simulated_epochs = read_receiver_ascii(configs["receiver"])
    values["receiver_clock_mjd"] = np.asarray([e["mjd"] for e in simulated_epochs], dtype=float)
    values["receiver_clock_seconds"] = np.asarray([e["clock_seconds"] for e in simulated_epochs])
    ambiguity_file = root/"generation"/"ambiguity_truth.txt"
    if not ambiguity_file.is_file():
        raise RuntimeError("Native ambiguity truth export is required for the synthetic recovery gate")
    values["ambiguity_truth_text"] = np.asarray(ambiguity_file.read_text())
    values["cycle_slips_json"] = np.asarray(json.dumps(export["slips"]))
    evaluation_path = root/"evaluation"/"truth.npz"
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(evaluation_path, **values)
    result = {"schema_version": 1, "status": "observations_ready", "date": date,
              "stage": "synthetic", "mission": "synthetic-GRACE-receiver", "case": case,
              "duration_hours": case["duration_hours"],
              "estimation_inputs": [*products, artifact(observation_path, "gnss_observations"),
                  artifact(instruments["attitude"], "attitude", format="groops_instrument")],
              "evaluation_inputs": [artifact(evaluation_path, "truth", frame="CRF/J2000", time_scale="GPS")],
              "native_simulation": {"engine": "GnssSimulateReceiver", "seed": case["seed"],
                  "ambiguity_injection": "independent integer cycles per signal; same-frequency fractional bias is coherent",
                  "simulation_wavelength_factor": 1.,
                  "independent_trajectory": "TudatPy", "truth_sha256": sha256_file(truth_path),
                  "simulation_configs": configs, "execution": execution, "export": export,
                  "transmitter_cache": conversion,
                  "measurement_parity": "shared native observation model; numerical gate still required",
                  "noise": {**NOISE_MODEL, "receiver_clock_sigma_m": 30.,
                            "accuracy_definition_sha256": sha256_file(root/"generation"/"synthetic_accuracy.xml")},
                  "mask_applied": False, "bootstrap_performed": False},
              "missing": ["masked_gnss_only_bootstrap", "common_native_preparation", "numerical_parity_gate"]}
    retention = {"retain_native_diagnostics": bool(backend.get("retain_native_diagnostics", False)),
                 "deleted_outputs": []}
    if not retention["retain_native_diagnostics"]:
        retention["deleted_outputs"] = compact_generation(root,
            [configs["receiver"], instruments["orbit"], generated["truth"], generated["dataset"],
             root/"generation"/"simulated_clock.txt", ambiguity_file],
            [observation_path, instruments["attitude"], evaluation_path])
    result["native_simulation"]["retention"] = retention
    write_json(root/"data_manifest.json", result)
    return result


def _execute(executable,config,root,seed):
    from ..comparison.backend import run_native
    return run_native(executable,config,root,Path(config).stem,timeout=7200,threads=1,
        environment_overrides={'ORBIT_POC_SIMULATION_SEED':str(int(seed)),
            'ORBIT_POC_SIMULATION_AMBIGUITIES':str(Path(config).with_name('ambiguity_truth.txt'))})


def native_data_inventory(root):
    """Seal exact glob membership, links and bytes, including linked directories."""
    root=Path(root).absolute()
    if not root.is_dir():raise ValueError('Native data directory is missing')
    entries=[]
    def walk(directory,relative,ancestors):
        resolved=directory.resolve()
        if resolved in ancestors:raise ValueError('Native data directory contains a symlink cycle')
        for path in sorted(directory.iterdir()):
            rel=(relative/path.name).as_posix()
            if path.is_symlink() and not path.exists():raise ValueError('Native data contains dangling symlink')
            entry={'relative':rel,'kind':'directory' if path.is_dir() else 'file','link_target':os.readlink(path) if path.is_symlink() else None,'resolved':str(path.resolve())}
            if path.is_dir():
                entries.append(entry);walk(path,relative/path.name,ancestors|{resolved})
            elif path.is_file():
                entry.update(bytes=path.stat().st_size,sha256=sha256_file(path));entries.append(entry)
            else:raise ValueError('Unsupported native data entry')
    walk(root,Path(),set())
    return {'schema':'orbit-poc-native-data-directory-v1','root':str(root),'entries':entries}


def prefix_inputs(raw,case):
    """Keep continuous observations; select prefix/mask before bootstrap below."""
    if raw.get('stage')!='synthetic' or raw.get('duration_hours')!=72:
        raise ValueError('Prefix requires one continuous72h synthetic source')
    original=raw['case'];current=case['case']
    for key in ('orbit','seed','atmosphere','epoch'):
        if original[key]!=current[key]:raise ValueError('Prefix does not belong to continuous generation')
    if current['duration_hours'] not in (24,48,72):raise ValueError('Invalid prefix duration')
    data.verify_manifest(raw)
    return {**raw,'duration_hours':current['duration_hours'],'case':current,
        'multiday_preparation':{'generation_id':case['generation_id'],'continuous_source_hours':72,
            'prefix_hours':current['duration_hours'],'continuous_input_sha256':canonical_hash(raw['estimation_inputs']),
            'mask_before_initialization':True,'independent_trial':False,
            'ambiguity_policy':'Preprocess retained observations afresh; no daily resets of continuous arcs'}}


def prepare_one(case,root,runtime,options,raw):
    """Convert the retained prefix and close its own GNSS-only initialization."""
    from ..comparison import backend as native
    from ..comparison import groops_config
    from ..comparison.initialization import _field
    from ..comparison.synthetic import configure_synthetic_forces
    from ..comparison.protocol import artifact_record,validate_estimation_inputs
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    binary=runtime['native']['path'];model=case['case']
    if case['stage']=='synthetic':raw=prefix_inputs(raw,case)
    if raw.get('status')=='excluded':raise ValueError('Fixed flight day excluded by prespecified metadata')
    data.fetch_example_auxiliary(options['example_directory'],options['auxiliary_dir'])
    groops_config.fetch_flight_auxiliary(options['auxiliary_dir'])
    # Both disturbance models share this exact zero-disturbance preparation.
    configured=build_arc_configs(raw,options['example_directory'],options['auxiliary_dir'],root/'native-prepared',
        method='groops_pulses',mask=model['mask'],duration_hours=model['duration_hours'])
    if case['stage']=='synthetic':
        configured=configure_synthetic_forces(configured,model,options)
        # Nominal closure precedes NativeModel's profile selection. Use the
        # corrected synthetic path here too, without changing legacy defaults.
        path=configured['configs']['variational']
        tree=ET.parse(path).getroot()
        propagation=tree.find('.//PreprocessingVariationalEquation')
        if propagation is None:raise ValueError('Synthetic initialization needs native propagation')
        _field(propagation,'orbitPocDerivativeProfile','synthetic_complete_v1')
        _save(tree,path)
    executions=[]
    for label in ('convert_gnss','convert_receiver'):
        executions.append(native.run_native(binary,configured['configs'][label],configured['output_dir'],label,timeout=7200,threads=1))
    for key in ('receiver','orbit','attitude'):
        p=Path(configured['native_paths'][key])
        if not p.is_file() or not p.stat().st_size:raise ValueError('Native preparation output missing: '+key)
    native._verify_transmitters(configured)
    executions.extend(native._close_prepared_nominal_reference(configured,binary,root,timeout=7200))
    blind=native._blind_record(configured)
    blind['native_data_inventory']=native_data_inventory(Path(configured['output_dir'])/'data')
    if case['stage']=='synthetic':blind['multiday_preparation']=raw['multiday_preparation']
    path=root/'native_preparation.json';write_json(path,blind)
    estimation=[*configured['estimation_inputs'],artifact_record('force_auxiliary',path,metadata={'kind':'native_preparation'})]
    validate_estimation_inputs(estimation,flight=case['stage']=='flight')
    write_json(root/'execution.json',{'executions':executions,'native':runtime['native'],'mask_before_initialization':True})
    return {**{key:case[key] for key in ('stage','case','method','parameters')},'estimation_inputs':estimation,
        **{key:configured[key] for key in ('force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash')}}


def prepare_catalog(cases,output,runtime,options):
    """Concrete native/Tudat preparation; missing tools raise, never simulate success.

    Four72h generations are reused by all prefixes and both methods. Each unique
    prefix/mask is initialized independently; both methods share that preparation.
    """
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    for key in ('cache_dir','auxiliary_dir','example_directory','tudat_python'):
        if not options.get(key):raise ValueError('Native multi-day preparation requires '+key)
    from .protocol import verify_artifact
    verify_artifact({'path':options['tudat_python'],'sha256':options.get('tudat_python_sha256','')})
    options={**options,'groops_executable':runtime['native']['path'],'retain_native_diagnostics':True}
    generations={};prepared={};entries=[]
    for case in cases:
        if case['stage']=='flight':
            try:request=options['flight_requests'][case['case_id']]
            except KeyError as error:raise ValueError('Pinned original April24 flight request required; regeneration is forbidden') from error
        else:
            gid=case['generation_id']
            if gid not in generations:
                target=root/'generation'/gid
                if target.exists():raise ValueError('Unsealed partial generation exists; use a new preparation directory')
                continuous={**case['case'],'duration_hours':72,'coverage':'normal'};continuous.pop('mask',None)
                generations[gid]=generate_continuous_case(continuous,target,options)
            key=canonical_hash({'stage':case['stage'],'case':case['case']})
            if key not in prepared:prepared[key]=prepare_one(case,root/'prefixes'/key,runtime,options,generations[gid])
            request={**prepared[key],'method':case['method'],'parameters':case['parameters']}
        path=root/'requests'/(case['case_id']+'.json');write_json(path,request)
        entries.append({'case_id':case['case_id'],'request':{'path':str(path.resolve()),'sha256':sha256_file(path)}})
    return {'schema':'orbit-poc-segmented-input-catalog-v1','entries':entries}
