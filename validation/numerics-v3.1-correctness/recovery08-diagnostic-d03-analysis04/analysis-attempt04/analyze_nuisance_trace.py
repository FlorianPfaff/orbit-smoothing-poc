#!/usr/bin/env python3
"""Independent, complete-row Decimal110 accounting for the bounded D03 trace.

This program reads evidence only.  It never executes GROOPS.  A successful
trace-equivalence receipt is necessary, but never a scientific acceptance gate.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
import hashlib
import gzip
import json
import math
from pathlib import Path
import re
import struct

PRECISION = 110
D = Decimal
ZERO = D(0)
C = D(299792458)
SENTINEL = 2**64 - 1
HEX = re.compile(r'([+-]?)0x([0-9a-f]+)(?:\.([0-9a-f]*))?p([+-]?\d+)\Z', re.I)
GEOMETRY_PREFIXES = ('polynomial_', 'receiver_center_', 'receiver_antenna_',
                     'transmitter_center_', 'transmitter_antenna_', 'distance_')
GEOMETRY_STAGES = {'travel_seconds', 'duration_seconds', 'transmitter_time_remainder',
                   'receiver_position_high', 'receiver_position_low',
                   'transmitter_position_high', 'transmitter_position_low',
                   'receiver_velocity', 'transmitter_velocity'}
UPDATE_PREFIXES = ('parameter_', 'clock_', 'local_', 'VTEC_', 'bias_', 'ambiguity_update_', 'ambiguity_global_')
LIGHT_STAGES = {'distance_before_narrowing.high', 'distance_before_narrowing.low',
                'travel_seconds', 'duration_seconds', 'receiver_clock_seconds',
                'transmitter_time_remainder', 'nominal_receiver_time.day',
                'nominal_receiver_time.fraction', 'rounded_transmitter_time.day',
                'rounded_transmitter_time.fraction'}


def exact_hex(text):
    m = HEX.fullmatch(text)
    if not m:
        raise ValueError(f'Finite hexadecimal floating value required: {text!r}')
    sign, whole, frac, exp = m.groups(); frac = frac or ''
    n = int(whole + frac, 16); e = int(exp) - 4 * len(frac)
    if abs(e) > 20000:
        raise ValueError('Unbounded exponent')
    if e < 0:
        return D((int(sign == '-'), tuple(map(int, str(n * 5**(-e)))), e))
    return D((int(sign == '-'), tuple(map(int, str(n << e))), 0))


def rounded64(value):
    f = float(value)
    if not math.isfinite(f):
        raise ValueError('Nonfinite rounded binary64')
    return D.from_float(f)


def rounded_binary(value, bits=64):
    """Nearest-even normal binary rounding, e.g. the pinned x87 significand."""
    if not value: return value
    sign = -1 if value < 0 else 1
    n, d = abs(value).as_integer_ratio()
    e = n.bit_length()-d.bit_length()
    if (n < d*(1 << e)) if e >= 0 else (n*(1 << -e) < d): e -= 1
    shift = e-bits+1
    nn, dd = (n, d*(1 << shift)) if shift >= 0 else (n*(1 << -shift), d)
    q, r = divmod(nn, dd)
    if 2*r > dd or (2*r == dd and q % 2): q += 1
    return D(sign*q)*D(2)**shift


def native_target(value):
    """Native static_cast<Double>(TwofoldGeometry::rounded()), in two stages."""
    return rounded64(rounded_binary(value, bits=64))


def validate_native_targets(precise, native):
    if set(precise) != set(native) or any(native_target(precise[k]) != native[k] for k in precise):
        raise ValueError('Native row and two-stage rounded precise row disagree')


def artifact(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return {'path': str(path), 'bytes': Path(path).stat().st_size, 'sha256': h.hexdigest()}


@dataclass(slots=True)
class Record:
    file: str; line: int; stem: str; phase: str; alpha: D; block: tuple
    row: int; component: str; stage: str; kind: str; index: int
    value: D | str; evaluation: int; event: int; audit: str

    @property
    def key(self):
        return self.component, self.stage, self.row, self.index

    @property
    def identity(self):
        return self.file, self.evaluation, self.phase, self.alpha, self.audit


def records(path):
    previous = -1
    with Path(path).open() as f:
        for line, text in enumerate(f, 1):
            a = text.rstrip('\n').split('\t')
            if len(a) != 16:
                raise ValueError(f'Expected 16 columns at {path}:{line}')
            stem, phase, alpha, recv, trans, epoch, row, comp, stage, kind, col, value, bits, ev, event, audit = a
            if kind == 'text':
                if bits != '-': raise ValueError('Text has floating bit pattern')
            else:
                value = exact_hex(value)
                if kind == 'double':
                    if not re.fullmatch('[0-9a-f]{16}', bits): raise ValueError('Bad binary64 bits')
                    f64 = struct.unpack('>d', bytes.fromhex(bits))[0]
                    if not math.isfinite(f64) or D.from_float(f64) != value:
                        raise ValueError('Float bits disagree with hex value')
                    if not value and (bits[0] in '89abcdef') != value.is_signed():
                        raise ValueError('Signed zero mismatch')
                elif kind != 'long_double' or bits != '-':
                    raise ValueError('Unknown scalar kind')
            event = int(event)
            if event <= previous: raise ValueError('Nonmonotonic per-process event')
            previous = event
            if phase not in ('baseline', 'joint', 'trial') or not stem.endswith('.4'):
                raise ValueError('Trace outside prescribed generation/phase')
            alpha = exact_hex(alpha)
            if phase == 'trial' and alpha not in (ZERO, D(1)):
                raise ValueError('Unexpected comprehensive trial alpha')
            yield Record(str(path), line, stem, phase, alpha, (int(recv), int(trans), int(epoch)),
                         int(row), comp, stage, kind, int(col), value, int(ev), event, audit)


@dataclass
class Ledger:
    identity: tuple
    block: tuple
    start_event: int
    values: dict = field(default_factory=dict)
    geometry: dict = field(default_factory=dict)
    light_events: list = field(default_factory=list)

    def put(self, r):
        if r.key in self.values:
            raise ValueError(f'Duplicate equation operand {r.key} in {self.identity}/{self.block}')
        self.values[r.key] = r.value

    def matrix(self, stage, component=None):
        out = {}
        for (comp, name, row, col), value in self.values.items():
            if name == stage and (component is None or component == comp):
                if (row, col) in out: raise ValueError(f'Ambiguous {stage}')
                out[row, col] = value
        return out

    def scalar(self, stage, row=0, col=0, component=None, optional=False):
        a = self.matrix(stage, component)
        if (row, col) not in a:
            if optional: return None
            raise ValueError(f'Missing {stage}[{row},{col}] in {self.identity}/{self.block}')
        return a[row, col]

    def pairs(self, stage):
        high, low = self.matrix(stage+'.high'), self.matrix(stage+'.low')
        if set(high) != set(low): raise ValueError(f'Incomplete expansion {stage}')
        return {k: high[k]+low[k] for k in high}


def is_geometry(r):
    return (r.stage.startswith(GEOMETRY_PREFIXES) or r.stage in GEOMETRY_STAGES
            or r.stage.startswith(('nominal_receiver_time.', 'rounded_transmitter_time.'))
            or (r.stage == 'receiver_clock_seconds' and r.component == 'light_time'))


def load_trace(paths):
    """Keep final geometry per equation, never all repeated interpolation records."""
    equations = []; open_eq = {}; pending_geometry = defaultdict(dict); pending_light = defaultdict(list)
    updates = defaultdict(list); constraints = defaultdict(dict); counts = defaultdict(int); stems = set()
    for path in paths:
        for r in records(path):
            counts['records'] += 1
            stems.add(r.stem)
            if len(stems) != 1: raise ValueError('Trace contains multiple QR stem identities')
            key = r.identity, r.block
            if is_geometry(r):
                pending_geometry[key][r.key] = r.value
                if r.stage in LIGHT_STAGES:
                    pending_light[key].append((r.event, r.component, r.stage, r.value))
                counts['geometry_records'] += 1
                continue
            if r.stage.startswith(UPDATE_PREFIXES):
                updates[r.identity].append(r)
                continue
            if r.stage.startswith('constraint_'):
                ckey = r.block[2], r.row
                row = constraints[r.identity].setdefault(ckey, {})
                coperand = r.stage, r.index
                if coperand in row: raise ValueError('Duplicate original constraint operand')
                row[coperand] = r.value
                continue
            if r.stage == 'observed' and (r.row, r.index) == (0, 0):
                if key in open_eq: equations.append(open_eq.pop(key))
                open_eq[key] = Ledger(r.identity, r.block, r.event,
                                      geometry=pending_geometry.pop(key, {}), light_events=pending_light.pop(key, []))
            if key in open_eq:
                open_eq[key].put(r)
            else:
                counts['unassigned_records'] += 1
    equations.extend(open_eq.values())
    return equations, dict(updates), dict(constraints), dict(counts)


def vector(a, name='vector'):
    if any(col != 0 for row, col in a): raise ValueError(f'{name} is not a vector')
    if a and set(row for row, col in a) != set(range(len(a))):
        raise ValueError(f'{name} is not contiguous')
    return {row: val for (row, col), val in a.items()}


def dot_rows(a, x):
    result = defaultdict(lambda: ZERO)
    for (i, j), value in a.items():
        if j not in x: raise ValueError(f'Missing requested coordinate {j}')
        result[i] += value*x[j]
    return dict(result)


def reduction(base, change):
    return sum((base[k]*change[k] - change[k]*change[k]/2 for k in base), ZERO)


def stats(items):
    items = list(items)
    if not items: return {'count': 0, 'sum': '0', 'max_abs': '0'}
    largest = max(items, key=lambda x: abs(x[1]))
    return {'count': len(items), 'sum': str(sum((v for _, v in items), ZERO)),
            'max_abs': str(abs(largest[1])), 'max_signed': str(largest[1]), 'max_key': str(largest[0])}


def equation_components(e, row):
    """Additive normalized residual terms; the closure term is explicitly retained."""
    def p(stage):
        a = e.pairs(stage)
        if (row, 0) not in a: raise ValueError(f'Missing component {stage}/{row}')
        return a[row, 0]
    weighted = p('retained_original_precise')
    obs = e.matrix('observed')
    if (row, 0) not in obs:
        # Added local Gaussian constraint: no physical observation or sigma slot.
        return {'local_STEC_prior': weighted}
    sigma = e.scalar('sigma', row)
    if sigma <= 0: raise ValueError('Nonpositive observation sigma')
    w = rounded64(D(1)/sigma)
    scale = e.scalar('transmitter_scale', component='')
    dist = p('range_distance'); rel = D(2)*p('range_relativistic_dot')/C
    shapiro = e.scalar('range_shapiro', row)
    clock = p('range_clock')
    rrange = p('range_residual'); recv = p('after_receiver_correction')
    trans = p('after_transmitter_correction'); amb = p('after_ambiguity'); models = p('after_models')
    def antenna_terms(component):
        bias = e.matrix('signal_bias_operand', component)
        pattern = e.matrix('antenna_pattern_operand', component)
        if not bias or set(bias) != set(pattern): raise ValueError('Incomplete antenna primitive operands')
        if component == 'receiver_correction':
            return bias[row, 0], pattern[row, 0]
        T = e.matrix('signal_composition')
        coeff = {j: v for (i, j), v in T.items() if i == row}
        if set(coeff) != {i for i, j in bias if j == 0}: raise ValueError('Incomplete transmitter composition')
        return (sum((v*bias[j, 0] for j, v in coeff.items()), ZERO),
                sum((v*pattern[j, 0] for j, v in coeff.items()), ZERO))
    rb, ra = antenna_terms('receiver_correction'); tb, ta = antenna_terms('transmitter_correction')
    result = {'observed': obs[row, 0]*w, 'distance': -scale*dist*w,
              'relativistic': -scale*rel*w, 'shapiro': -scale*shapiro*w,
              'clock': -scale*clock*w, 'receiver_bias': -rb*w, 'receiver_antenna': -ra*w,
              'transmitter_bias': -tb*w, 'transmitter_antenna': -ta*w, 'ambiguity': (amb-trans)*w,
              'models_STEC': (models-amb)*w}
    result['component_arithmetic_closure'] = weighted-sum(result.values(), ZERO)
    return result


def stec_coefficients(e, row):
    """Infer branch only when its actual model contribution is reproduced."""
    stec = e.scalar('STEC', optional=True)
    if stec is None: return None
    get = lambda name: e.scalar('ionosphere_'+name, row)
    ap, s, r, bend, f2, f3, f4 = (get(name) for name in ('Ap', 's', 'r', 'bending', 'f2', 'f3', 'f4'))
    flags = {n: bool(e.scalar(n)) for n in ('apply1stOrder', 'apply2ndOrder', 'apply3rdOrder', 'applyBending')}
    a1 = rounded64(-ap/f2) if flags['apply1stOrder'] else ZERO
    a2 = rounded64(rounded64(-s/2)/f3) if flags['apply2ndOrder'] else ZERO
    a3 = rounded64(rounded64(-r/3)/f4) if flags['apply3rdOrder'] else ZERO
    a4 = rounded64(bend/f4) if flags['applyBending'] else ZERO
    b1 = rounded64(ap/f2) if flags['apply1stOrder'] else ZERO
    b2 = rounded64(s/f3) if flags['apply2ndOrder'] else ZERO
    b3 = rounded64(r/f4) if flags['apply3rdOrder'] else ZERO
    actual = e.pairs('after_ambiguity')[row, 0]-e.pairs('after_models')[row, 0]
    matches = []
    for name, c, d in [('phase', a1+a2, a3+a4), ('range', b1+b2, b3)]:
        value = c*stec+d*stec*stec
        # A 128-ish-bit expansion has far more than 25 reliable decimal places
        # at these metre-scale correction values. This is a reconstruction test,
        # not a relaxed estimation/convergence threshold.
        if abs(value-actual) <= D('1e-25')*max(D(1), abs(actual)):
            matches.append((name, c, d))
    if len(matches) == 1: return matches[0]
    if matches and len({(c, d) for _, c, d in matches}) == 1:
        return ('identical_effect_branches', matches[0][1], matches[0][2])
    return None


def decompose_clock_kinematics(p):
    """Exact algebraic attribution using baseline kinematics and captured queries.

    This does not rerun a counterfactual propagator or certify its derivative.
    Residual terms explicitly retain imperfect kinematics and finite light-time
    closure; their inclusion makes the accounting an identity for stored inputs.
    """
    rb, rt, tb, tt = (p[name] for name in ('receiver_before', 'receiver_after', 'transmitter_before', 'transmitter_after'))
    separation = [rb[i]-tb[i] for i in range(3)]
    norm = sum((v*v for v in separation), ZERO).sqrt()
    if norm <= 0: raise ValueError('Zero baseline range in clock decomposition')
    k = [v/norm for v in separation]
    dr = sum((k[i]*(rt[i]-rb[i]) for i in range(3)), ZERO)
    dt = sum((k[i]*(tt[i]-tb[i]) for i in range(3)), ZERO)
    dq = p['range_after']-p['range_before']
    rc = p['clock_after']-p['clock_before']; tc = p['transmitter_clock_after']-p['transmitter_clock_before']
    rR, rT, w, scale = (p[name] for name in ('r_dot_receiver', 'r_dot_transmitter', 'weight', 'scale'))
    if abs(rT) >= 1: raise ValueError('Invalid light-time derivative denominator')
    first = 1+rT-rR; fixed = (1-rR)/(1-rT)
    native_coefficient = rounded64(rounded64(1+rT)-rR)
    native = C*(rounded64(native_coefficient*w)*rc-rounded64(w)*tc)
    before, after = p['query_before'], p['query_after']
    for query, clock in ((before, p['clock_before']), (after, p['clock_after'])):
        if query.get('seed_query') or 'distance_before_narrowing_m' not in query:
            raise ValueError('Final query is not tied to its path-distance operand')
        if query['receiver_clock_seconds'] != clock:
            raise ValueError('Query clock and observation clock differ')
    travel_error = ((after['travel_seconds']-after['distance_before_narrowing_m']/C)-
                    (before['travel_seconds']-before['distance_before_narrowing_m']/C))
    duration_error = ((after['duration_seconds']-after['travel_seconds']-p['clock_after'])-
                      (before['duration_seconds']-before['travel_seconds']-p['clock_before']))
    iteration_error = ((after['distance_before_narrowing_m']-p['range_after'])-
                       (before['distance_before_narrowing_m']-p['range_before']))
    receiver_remainder = dr+C*rR*rc
    transmitter_remainder = -dt-C*rT*(after['duration_seconds']-before['duration_seconds'])
    range_remainder = dq-(dr-dt)
    weight = scale*w; feedback = weight/(1-rT)
    components = {
        'coefficient_weight_scale_rounding': weight*C*(first*rc-tc)-native,
        'exact_fixed_point_minus_first_order_clock_coefficient': weight*C*(fixed-first)*rc,
        'travel_distance_cast_and_division_arithmetic': feedback*C*rT*travel_error,
        'clock_plus_travel_duration_arithmetic': feedback*C*rT*duration_error,
        'final_light_time_iteration_residual': feedback*rT*iteration_error,
        'receiver_position_vs_moving_clock_kinematics': feedback*receiver_remainder,
        'transmitter_position_vs_captured_duration_kinematics': feedback*transmitter_remainder,
        'range_projection_remainder': feedback*range_remainder,
    }
    actual = weight*(dq+C*rc-C*tc)-native
    closure = actual-sum(components.values(), ZERO)
    if abs(closure) > D('1e-80'): raise ValueError('Clock-geometry decomposition does not close')
    diagnostics = {
        'actual_distance_clock_minus_native': actual,
        'accounting_closure': closure,
        'paired_travel_arithmetic_error_seconds': travel_error,
        'paired_duration_addition_error_seconds': duration_error,
        'paired_final_light_time_iteration_residual_metres': iteration_error,
        'receiver_position_projection_metres': dr,
        'moving_receiver_clock_projection_metres': -C*rR*rc,
        'fixed_receiver_clock_counterfactual_difference': weight*C*rR/(1-rT)*rc,
        'transmitter_scale': scale,
    }
    return components, diagnostics


def clock_geometry_attribution(be, te, row):
    def positions(e, name):
        g = Ledger(e.identity, e.block, e.start_event, values=e.geometry)
        hi, lo = vector(g.matrix(name+'_position_high')), vector(g.matrix(name+'_position_low'))
        if set(hi) != {0, 1, 2} or set(lo) != set(hi): return None
        return [hi[k]+lo[k] for k in range(3)]
    points = [positions(e, name) for e, name in ((be, 'receiver'), (te, 'receiver'), (be, 'transmitter'), (te, 'transmitter'))]
    if any(v is None for v in points): return {}
    queries = [light_time_queries(e.light_events) for e in (be, te)]
    if not all(queries): return {}
    scales = [e.scalar('transmitter_scale') for e in (be, te)]
    if scales[0] != scales[1]: raise ValueError('Changing transmitter scale is outside clock decomposition')
    p = dict(zip(('receiver_before', 'receiver_after', 'transmitter_before', 'transmitter_after'), points))
    p.update(range_before=be.pairs('range_distance')[0, 0], range_after=te.pairs('range_distance')[0, 0],
             clock_before=be.scalar('receiver_clock_seconds', component=''), clock_after=te.scalar('receiver_clock_seconds', component=''),
             transmitter_clock_before=be.scalar('transmitter_clock_seconds', component=''), transmitter_clock_after=te.scalar('transmitter_clock_seconds', component=''),
             r_dot_receiver=be.scalar('rDotRecv'), r_dot_transmitter=be.scalar('rDotTrans'),
             weight=rounded64(1/be.scalar('sigma', row)), scale=scales[0],
             query_before=queries[0][-1], query_after=queries[1][-1])
    components, diagnostics = decompose_clock_kinematics(p)
    return {**{'clock_geometry_component_'+k: v for k, v in components.items()},
            **{'clock_geometry_diagnostic_'+k: v for k, v in diagnostics.items()}}


def stored_state_attribution(be, te, row):
    out = {}
    if (row, 0) not in be.matrix('observed'):
        sigma = be.scalar('sigmaSTEC', optional=True)
        if sigma is not None and sigma > 0:
            before, after = be.scalar('dSTEC'), te.scalar('dSTEC')
            exact = (after-before)/sigma
            native = rounded64(1/sigma)*(after-before)
            out['local_prior_stored_state_change'] = exact
            out['local_prior_native_coefficient_discrepancy'] = exact-native
            out['stored_state_linear_model_change'] = native
        return out
    w = rounded64(1/be.scalar('sigma', row))
    rc = te.scalar('receiver_clock_seconds', component='')-be.scalar('receiver_clock_seconds', component='')
    tc = te.scalar('transmitter_clock_seconds', component='')-be.scalar('transmitter_clock_seconds', component='')
    # Explicit native clock geometry coefficient, before weighting. Retain
    # binary64 operation order of 1+rDotTrans-rDotRecv.
    coeff = rounded64(rounded64(1+be.scalar('rDotTrans'))-be.scalar('rDotRecv'))
    native_clock = (rounded64(coeff*w)*rc-rounded64(w)*tc)*C
    actual_components = equation_components(be, row), equation_components(te, row)
    delta = {k: actual_components[0][k]-actual_components[1][k] for k in actual_components[0]}
    actual_range = sum((delta[k] for k in ('distance', 'relativistic', 'shapiro', 'clock')), ZERO)
    out.update(clock_geometry_attribution(be, te, row))
    out['native_clock_design_at_exact_stored_seconds'] = native_clock
    out['actual_range_minus_native_clock_design_at_stored_state'] = actual_range-native_clock
    out['distance_clock_minus_native_clock_design_at_stored_state'] = delta['distance']+delta['clock']-native_clock
    out['relativistic_plus_shapiro_change'] = delta['relativistic']+delta['shapiro']
    gb, gt = geometry_diagnostics(be), geometry_diagnostics(te)
    label = 'velocity_narrowing_relativistic_range_m'
    if gb.get('available') and gt.get('available') and label in gb and label in gt:
        out['velocity_narrowing_effect_on_range_change'] = (D(gt[label])-D(gb[label]))*be.scalar('transmitter_scale')*w
    cb, ct = stec_coefficients(be, row), stec_coefficients(te, row)
    if cb is not None and ct is not None and cb[0] == ct[0]:
        sb, st = be.scalar('STEC'), te.scalar('STEC')
        state = (cb[1]*(st-sb)+cb[2]*(st*st-sb*sb))*w
        geometry = ((ct[1]-cb[1])*st+(ct[2]-cb[2])*st*st)*w
        out['STEC_exact_stored_state_at_baseline_geometry'] = state
        out['STEC_coefficient_geometry_change'] = geometry
        out['STEC_decomposition_closure'] = delta['models_STEC']-state-geometry
        B = be.matrix('complete_original_local_design')
        if (row, 0) in B:
            out['STEC_exact_state_minus_native_local_derivative'] = state-B[row, 0]*(st-sb)
            # Direct physical primitive mapping avoids pretending that rounded
            # raw bias arrays remain exactly inside their selected gauge basis.
            # T must be fixed for this interpretation; otherwise report no full
            # stored-state model prediction for this row.
            if (be.matrix('signal_composition') == te.matrix('signal_composition') and
                be.matrix('ambiguity_composition') == te.matrix('ambiguity_composition') and
                be.matrix('ambiguity_type_mapping') == te.matrix('ambiguity_type_mapping')):
                out['stored_state_linear_model_change'] = (native_clock + delta['receiver_bias'] +
                    delta['transmitter_bias'] + delta['ambiguity'] + B[row, 0]*(st-sb))
    return out


def geometry_diagnostics(e):
    """Replay final stored geometry; keep missing primitives explicit.

    These differences measure arithmetic representations at the captured query,
    not the change that an infinitely precise physical clock update would cause.
    """
    g = Ledger(e.identity, e.block, e.start_event, values=e.geometry)
    output = {}
    def v(name): return vector(g.matrix(name))
    def p(name, comp=None):
        hi = g.matrix(name+'.high', comp); lo = g.matrix(name+'.low', comp)
        if set(hi) != set(lo): raise ValueError('Incomplete geometry expansion')
        return {k: hi[k]+lo[k] for k in hi}
    rh, rl, th, tl = (v(n) for n in ('receiver_position_high', 'receiver_position_low', 'transmitter_position_high', 'transmitter_position_low'))
    if any(set(a) != {0, 1, 2} for a in (rh, rl, th, tl)):
        return {'available': False, 'reason': 'Final position high/low vectors missing'}
    rp = {k: rh[k]+rl[k] for k in rh}; tp = {k: th[k]+tl[k] for k in th}
    distances = e.pairs('range_distance')
    if not distances: return {'available': False, 'reason': 'Final range expansion missing'}
    exact_range = sum(((rp[k]-tp[k])**2 for k in rp), ZERO).sqrt()
    output['range_sqrt_representation_error_m'] = next(iter(distances.values()))-exact_range
    precise_velocity = p('polynomial_precise_result', 'transmitter_velocity_interpolation')
    native_velocity = v('transmitter_velocity')
    if precise_velocity and set(native_velocity) == {0, 1, 2}:
        if set(precise_velocity) == {(0, k) for k in range(3)}:
            pv = {k: precise_velocity[0, k] for k in range(3)}
        elif set(precise_velocity) == {(k, 0) for k in range(3)}:
            pv = {k: precise_velocity[k, 0] for k in range(3)}
        else: raise ValueError('Unexpected polynomial velocity result shape')
        output['velocity_narrowing_relativistic_range_m'] = D(2)/C*sum((tp[k]*(native_velocity[k]-pv[k]) for k in range(3)), ZERO)
        output['velocity_narrowing_max_m_per_s'] = max(abs(native_velocity[k]-pv[k]) for k in range(3))
    travel = g.scalar('travel_seconds', component='light_time', optional=True)
    duration = g.scalar('duration_seconds', component='light_time', optional=True)
    clk = g.scalar('receiver_clock_seconds', component='light_time', optional=True)
    if travel is not None and duration is not None and clk is not None:
        output['duration_addition_error_s'] = duration-travel-clk
    queries = light_time_queries(e.light_events)
    if queries:
        last = queries[-1]
        for name, value in last.items():
            if name not in ('seed_query', 'event'):
                output['last_query_'+name] = value
        output['light_time_queries'] = len(queries)
    rem = g.scalar('transmitter_time_remainder', component='light_time', optional=True)
    if rem is not None and duration is not None:
        try:
            dd = g.scalar('rounded_transmitter_time.day')-g.scalar('nominal_receiver_time.day')
            df = g.scalar('rounded_transmitter_time.fraction')-g.scalar('nominal_receiver_time.fraction')
            output['time_remainder_arithmetic_error_s'] = rem-(-duration-(dd+df)*D(86400))
        except ValueError:
            output['time_remainder_unavailable'] = 'Missing split time operands'
    return {'available': True, **{k: str(val) for k, val in output.items()}}


def light_time_queries(events):
    """The distance directly preceding each travel assignment is its operand.

    A later preciseDistance call checks transmitter displacement, not the path
    length. It must never be substituted for the travel assignment's distance.
    """
    queries = []; distance_high = None; last_distance = None; current = None
    previous_event = -1
    for event, component, stage, value in events:
        if event <= previous_event: raise ValueError('Nonmonotonic light-time events')
        previous_event = event
        if stage == 'distance_before_narrowing.high': distance_high = value
        elif stage == 'distance_before_narrowing.low':
            if distance_high is None: raise ValueError('Light-time distance low without high')
            last_distance = distance_high+value; distance_high = None
        elif stage == 'travel_seconds':
            current = {'event': event, 'seed_query': last_distance is None, 'travel_seconds': value}
            if last_distance is not None:
                rounded = rounded_binary(last_distance)
                expected = rounded_binary(rounded/C)
                current.update(distance_before_narrowing_m=last_distance, distance_cast_error_m=rounded-last_distance,
                    division_error_s=value-rounded/C,
                    native_division_replay_error_s=value-expected,
                    travel_vs_precise_distance_error_s=value-last_distance/C)
            queries.append(current)
        elif current is not None:
            current[stage] = value
    for q in queries:
        if 'duration_seconds' in q and 'receiver_clock_seconds' in q:
            exact = q['travel_seconds']+q['receiver_clock_seconds']
            q['duration_addition_error_s'] = q['duration_seconds']-exact
            q['native_duration_replay_error_s'] = q['duration_seconds']-rounded_binary(exact)
            if 'travel_vs_precise_distance_error_s' in q:
                q['total_query_arithmetic_error_s'] = q['duration_addition_error_s']+q['travel_vs_precise_distance_error_s']
    return queries


def constraint_ledger(rows):
    target = {}; designs = {}; contexts = {}
    for key, operands in rows.items():
        if ('constraint_context', 0) not in operands or ('constraint_original_rhs', 0) not in operands:
            raise ValueError('Incomplete original constraint row')
        target[key] = operands['constraint_original_rhs', 0]
        contexts[key] = operands['constraint_context', 0]
        designs[key] = {col: v for (stage, col), v in operands.items() if stage == 'constraint_original_coefficient'}
        if not designs[key]: raise ValueError('Constraint with no retained coefficients')
    return target, designs, contexts


def update_matrix(rs, stage):
    result = {}
    for r in rs:
        if r.stage == stage:
            key = r.row, r.index
            if key in result: raise ValueError(f'Repeated global update {stage}')
            result[key] = r.value
    return result


def summarize_raw_updates(rs):
    """Exact native arithmetic discrepancies, separate from transformed coordinates."""
    grouped = defaultdict(list)
    for r in rs:
        grouped[r.block, r.component].append(r)
    output = defaultdict(list)
    for (block, component), rr in grouped.items():
        # Updates from repeated bias/ambiguity families may share context. Split
        # using their explicit start marker, retaining every individual operation.
        sections = []; current = []
        starters = {'bias_global_start', 'ambiguity_global_start', 'clock_seconds_before',
                    'local_STEC_before', 'VTEC_STEC_before'}
        for r in rr:
            if r.stage in starters and current:
                sections.append(current); current = []
            current.append(r)
        if current: sections.append(current)
        for sec in sections:
            values = defaultdict(dict)
            for r in sec: values[r.stage][r.row, r.index] = r.value
            ident = (block, component, sec[0].event)
            if 'clock_seconds_before' in values:
                one = lambda name: values[name][0, 0]
                applied = one('clock_seconds_after')-one('clock_seconds_before')
                req = one('clock_requested_metres')
                output['clock_store_loss_metres'].append((ident, applied*C-req))
                output['clock_division_loss_metres'].append((ident, one('clock_requested_seconds')*C-req))
            elif 'local_STEC_before' in values:
                one = lambda name: values[name][0, 0]
                req = one('local_STEC_requested')
                for coord in ('STEC', 'dSTEC'):
                    output['local_'+coord+'_store_loss'].append((ident, one('local_'+coord+'_after')-one('local_'+coord+'_before')-req))
            elif 'VTEC_STEC_before' in values:
                one = lambda name: values[name][0, 0]
                req = one('VTEC_mapping')*(one('VTEC_requested')+one('VTEC_cos')*one('VTEC_gradient_x_requested')+one('VTEC_sin')*one('VTEC_gradient_y_requested'))
                output['VTEC_arithmetic_and_store_loss'].append((ident, one('VTEC_STEC_after')-one('VTEC_STEC_before')-req))
            elif 'ambiguity_update_before' in values:
                before = values['ambiguity_update_before']; after = values['ambiguity_update_after']; req = values['ambiguity_update_requested']
                if set(before) != set(after) or set(before) != set(req): raise ValueError('Ambiguity update shape mismatch')
                for k in before: output['ambiguity_store_loss_cycles'].append(((ident, k), after[k]-before[k]-req[k]))
            elif 'bias_update_before' in values:
                before = values['bias_update_before']; after = values['bias_update_after']; req = values['bias_requested']
                mapping = values.get('bias_type_mapping')
                expected = defaultdict(lambda: ZERO)
                for (i, j), v in req.items():
                    if j: raise ValueError('Bias requested is not vector')
                    target = int(mapping[i, 0]) if mapping else i
                    expected[target, 0] += v
                if set(before) != set(after): raise ValueError('Bias state support changed')
                for k in before: output['bias_store_loss_metres'].append(((ident, k), after[k]-before[k]-expected[k]))
    return {name: stats(v) for name, v in output.items()}


def analyze(equations, updates, constraints, factor, search):
    retained = defaultdict(dict); joints = defaultdict(dict); double_rounding = []
    for e in equations:
        r = vector(e.pairs('retained_original_precise'))
        if r:
            if e.block in retained[e.identity]: raise ValueError('Duplicate retained equation block')
            complete = vector(e.pairs('complete_original_precise'))
            if complete != r: raise ValueError('Retained residual differs from complete equation')
            native = vector(e.matrix('retained_original_native'))
            validate_native_targets(r, native)
            double_rounding.extend(((e.identity+e.block+(k,), native[k]-rounded64(r[k])) for k in r))
            retained[e.identity][e.block] = e
        if e.matrix('joint_total_native_influence'):
            if e.block in joints[e.identity]: raise ValueError('Duplicate joint equation')
            joints[e.identity][e.block] = e
    baseline_ids = [i for i in retained if i[2] == 'baseline' and i[4] == '0']
    joint_ids = [i for i in joints if i[2] == 'joint' and i[4] == '0']
    if len(baseline_ids) != 1 or len(joint_ids) != 1:
        raise ValueError('Require one complete baseline and joint evaluation')
    bi, ji = baseline_ids[0], joint_ids[0]; base_eq = retained[bi]; joint_eq = joints[ji]
    if set(base_eq) != set(joint_eq): raise ValueError('Joint equation support differs from baseline')
    x = vector(update_matrix(updates.get(ji, []), 'parameter_requested'))
    if not x: raise ValueError('Missing original global correction')
    base = {}; rounded_base = {}; requested = {}; native_requested = {}; row_components = {}
    joint_rounding = []; requested_block_discrepancies = []
    for block in sorted(base_eq):
        be, je = base_eq[block], joint_eq[block]
        b = vector(be.pairs('retained_original_precise'))
        jb = vector(je.pairs('joint_original_precise'))
        if b != jb: raise ValueError('Joint recovery changed fixed original residual')
        gx = dot_rows(je.matrix('joint_global_design'), x)
        local = vector(je.matrix('joint_local_requested'))
        lx = dot_rows(je.matrix('joint_local_design'), local)
        for (i, offset), value in je.matrix('joint_global_requested_block').items():
            if offset+i not in x or value != x[offset+i]:
                raise ValueError('Mapped global requested block differs from global correction')
        native = vector(je.matrix('joint_total_native_influence'))
        native_targets = vector(be.matrix('retained_original_native'))
        if set(native) != set(b): raise ValueError('Joint influence row support differs')
        for row, value in b.items():
            key = (*block, row); pred = gx.get(row, ZERO)+lx.get(row, ZERO)
            base[key] = value; requested[key] = pred; native_requested[key] = native[row]
            rounded_base[key] = native_targets[row]
            joint_rounding.append((key, native[row]-pred))
            row_components[key] = equation_components(be, row)
    cb, ca, cc = constraint_ledger(constraints.get(bi, {}))
    constraint_base = {}; constraint_request = {}
    for key, value in cb.items():
        k = ('constraint', *key); constraint_base[k] = value
        constraint_request[k] = sum((coef*x[j] for j, coef in ca[key].items()), ZERO)
    allbase = {**base, **constraint_base}; allrequest = {**requested, **constraint_request}
    allrounded = {**rounded_base, **constraint_base}
    allnative_influence = {**native_requested, **constraint_request}
    if len(allbase) != factor['original_objective_rows']:
        raise ValueError(f'Original objective support incomplete: {len(allbase)} vs {factor["original_objective_rows"]}')
    trials = []
    trial_ids = [i for i in retained if i[2] == 'trial' and i[4] == '0']
    if sorted(i[3] for i in trial_ids) != [ZERO, D(1)]:
        raise ValueError('Require exactly ordinary alpha0 and alpha1 full-row trials')
    for ti in sorted(trial_ids, key=lambda i: i[3]):
        eqs = retained[ti]; alpha = ti[3]
        if set(eqs) != set(base_eq): raise ValueError('Trial observation support changed')
        current = {}; component_delta = defaultdict(dict); state_attribution = defaultdict(dict)
        for block, be in base_eq.items():
            te = eqs[block]
            b = vector(be.pairs('retained_original_precise')); t = vector(te.pairs('retained_original_precise'))
            if set(b) != set(t): raise ValueError('Trial row support changed')
            if be.matrix('observed') != te.matrix('observed') or be.matrix('sigma') != te.matrix('sigma'):
                raise ValueError('Trial observations or weights changed')
            for row in b:
                key = (*block, row); current[key] = t[row]
                comp = equation_components(te, row)
                if set(comp) != set(row_components[key]): raise ValueError('Component support changed')
                for name, value in comp.items(): component_delta[name][key] = row_components[key][name]-value
                for name, value in stored_state_attribution(be, te, row).items():
                    state_attribution[name][key] = value
        ct, cta, ctc = constraint_ledger(constraints.get(ti, {}))
        if set(ct) != set(cb) or ctc != cc or cta != ca: raise ValueError('Trial constraint support/design changed')
        for key, value in ct.items(): current['constraint', *key] = value
        delta = {k: allbase[k]-current[k] for k in allbase}
        if alpha == 0 and any(delta.values()): raise ValueError('Ordinary zero-update residual changed')
        requested_delta = {k: alpha*v for k, v in allrequest.items()}
        errors = {k: delta[k]-requested_delta[k] for k in allbase}
        # Exact symmetric attribution: total actual reduction equals the sum of
        # component delta times the mean residual. No arbitrary cross-term order.
        comp_reduction = {name: sum((v*(base[k]+current[k])/2 for k, v in values.items()), ZERO)
                          for name, values in component_delta.items()}
        comp_reduction['separate_constraints'] = sum((delta[k]*(allbase[k]+current[k])/2 for k in constraint_base), ZERO)
        actual = reduction(allbase, delta)
        closure = actual-sum(comp_reduction.values(), ZERO)
        if abs(closure) > D('1e-80'): raise ValueError('Component objective accounting does not close')
        parameters = updates.get(ti, [])
        before = vector(update_matrix(parameters, 'parameter_before'))
        after = vector(update_matrix(parameters, 'parameter_after'))
        if set(before) != set(x) or set(after) != set(x): raise ValueError('Global stored-state support differs')
        mapped_applied = {j: after[j]-before[j] for j in x}
        applied = {}
        for block, je in joint_eq.items():
            ag = dot_rows(je.matrix('joint_global_design'), mapped_applied)
            # This coordinate diagnostic deliberately retains the requested
            # local update; exact raw local state losses are reported separately.
            al = dot_rows(je.matrix('joint_local_design'), vector(je.matrix('joint_local_requested')))
            for row in vector(je.pairs('joint_original_precise')):
                applied[*block, row] = ag.get(row, ZERO)+alpha*al.get(row, ZERO)
        for key in cb: applied['constraint', *key] = sum((coef*mapped_applied[j] for j, coef in ca[key].items()), ZERO)
        stored = dict(state_attribution.get('stored_state_linear_model_change', {}))
        stored_observation_complete = set(stored) == set(base)
        # Separate constraint targets remain binary64 and use native transformed
        # coordinates. Their actual target change is retained, not silently
        # replaced by the mapped export when that export is lossy.
        stored_with_actual_constraints = {**stored, **{k: delta[k] for k in constraint_base}}
        stored_prediction = reduction(allbase, stored_with_actual_constraints) if stored_observation_complete else None
        prediction_error_contributions = {k: errors[k]*(allbase[k]-(delta[k]+requested_delta[k])/2) for k in allbase}
        prediction_error_closure = actual-reduction(allbase, requested_delta)-sum(prediction_error_contributions.values(), ZERO)
        if abs(prediction_error_closure) > D('1e-80'): raise ValueError('Prediction error contribution accounting does not close')
        largest = sorted(allbase, key=lambda k: abs(prediction_error_contributions[k]), reverse=True)[:20]
        largest_rows = []
        for k in largest:
            item = {'key': list(k), 'baseline': str(allbase[k]), 'trial': str(current[k]),
                    'requested_change': str(requested_delta[k]), 'actual_change': str(delta[k]),
                    'residual_change_error': str(errors[k]),
                    'error_times_actual_mean_residual': str(errors[k]*(allbase[k]+current[k])/2)}
            item['actual_minus_prediction_contribution'] = str(prediction_error_contributions[k])
            if k in base:
                item['component_changes'] = {n: str(values.get(k, ZERO)) for n, values in component_delta.items()}
                item['stored_state_attribution'] = {n: str(values[k]) for n, values in state_attribution.items() if k in values}
                item['baseline_geometry'] = geometry_diagnostics(base_eq[k[:3]])
                item['trial_geometry'] = geometry_diagnostics(eqs[k[:3]])
            largest_rows.append(item)
        geometry_change = defaultdict(list); geometry_missing = []
        for block in base_eq:
            gb, gt = geometry_diagnostics(base_eq[block]), geometry_diagnostics(eqs[block])
            if not gb['available'] or not gt['available']:
                geometry_missing.append(list(block)); continue
            for name in set(gb) & set(gt) - {'available'}:
                try: change = D(gt[name])-D(gb[name])
                except Exception: continue
                geometry_change[name].append((block, change))
        native_trial = search.get('zero_update_replay') if alpha == 0 else next((t for t in search.get('trials', []) if t.get('alpha') == 1), None)
        native_actual = None if native_trial is None else D.from_float(float(native_trial['actual_reduction']))
        trials.append({'identity': [str(v) for v in ti], 'alpha': str(alpha),
                       'direct_cost': str(sum((v*v/2 for v in current.values()), ZERO)),
                       'actual_reduction': str(actual), 'requested_original_row_prediction': str(reduction(allbase, requested_delta)),
                       'native_actual_reduction': None if native_actual is None else str(native_actual),
                       'actual_reduction_minus_native': None if native_actual is None else str(actual-native_actual),
                       'actual_minus_requested_prediction': str(actual-reduction(allbase, requested_delta)),
                       'prediction_error_contributions': stats(prediction_error_contributions.items()),
                       'prediction_error_contribution_closure': str(prediction_error_closure),
                       'original_row_residual_discrepancy': stats(errors.items()),
                       'component_actual_reduction': {k: str(v) for k, v in comp_reduction.items()},
                       'component_normalized_residual_changes': {k: stats(v.items()) for k, v in component_delta.items()},
                       'component_accounting_closure': str(closure),
                       'largest_disagreement_rows': largest_rows,
                       'geometry_representation_changes': {k: stats(v) for k, v in geometry_change.items()},
                       'geometry_unavailable_blocks': geometry_missing,
                       'stored_state_attribution': {k: {'normalized_residual': stats(v.items()),
                                                       'times_actual_mean_residual': stats((row, val*(base[row]+current[row])/2) for row, val in v.items())}
                                                    for k, v in state_attribution.items()},
                       'apriori_coordinate_prediction_with_requested_local': str(reduction(allbase, applied)),
                       'stored_native_observation_model_complete': stored_observation_complete,
                       'stored_native_observation_missing_rows': [list(k) for k in set(base)-set(stored)],
                       'stored_native_observation_prediction_with_actual_constraint_changes': None if stored_prediction is None else str(stored_prediction),
                       'actual_minus_stored_native_prediction': None if stored_prediction is None else str(actual-stored_prediction),
                       'apriori_coordinate_store_difference': stats((j, mapped_applied[j]-alpha*x[j]) for j in x),
                       'raw_update_arithmetic': summarize_raw_updates(parameters)})
    native_prediction = D.from_float(float(search['full_step_prediction']))
    result = {'schema': 'orbit-poc-d03-decimal-analysis-v1', 'precision': PRECISION,
              'diagnostic_only': True, 'scientific_validation_complete': False, 'covariance_authorized': False,
              'complete_original_row_accounting': True, 'observation_rows': len(base),
              'separate_constraint_rows': len(constraint_base), 'original_objective_rows': len(allbase),
              'equation_blocks': len(base_eq), 'global_parameters': len(x),
              'baseline_direct_cost': str(sum((v*v/2 for v in allbase.values()), ZERO)),
              'native_objective_before': str(search.get('objective_before')),
              'requested_original_row_prediction': str(reduction(allbase, allrequest)),
              'native_profile_prediction': str(native_prediction),
              'requested_prediction_minus_native': str(reduction(allbase, allrequest)-native_prediction),
              'prediction_arithmetic_comparison': {
                  'precise_targets_decimal_joint': str(reduction(allbase, allrequest)),
                  'rounded_targets_decimal_joint': str(reduction(allrounded, allrequest)),
                  'precise_targets_native_joint': str(reduction(allbase, allnative_influence)),
                  'rounded_targets_native_joint': str(reduction(allrounded, allnative_influence)),
                  'native_qr_prediction': str(native_prediction),
                  'precise_minus_rounded_target_effect': str(reduction(allbase, allrequest)-reduction(allrounded, allrequest)),
                  'decimal_minus_native_joint_effect_at_rounded_targets': str(reduction(allrounded, allrequest)-reduction(allrounded, allnative_influence)),
                  'rounded_native_joint_minus_qr_factor_prediction': str(reduction(allrounded, allnative_influence)-native_prediction),
                  'constraint_influence_arithmetic': 'Independent Decimal coefficient dot requested step; constraint targets remain exact stored binary64.'},
              'native_joint_matvec_rounding': stats(joint_rounding),
              'native_target_rounding_operation': '64-bit-significand long-double high+low, then 53-bit-significand binary64 cast',
              'native_target_double_rounding_difference_from_direct_binary64': stats(double_rounding), 'trials': trials,
              'limitations': ['The apriori coordinate diagnostic is a transformed native coordinate export; it is not a substitute for raw stored clock/bias/ambiguity/STEC state.',
                              'Its local term deliberately remains the requested local update; raw STEC arithmetic is reported separately.',
                              'A complete-row residual discrepancy can contain nonlinear terms, omitted derivatives and rounding. Component changes are evidence, not a unique causal attribution.',
                              'The clock-geometry decomposition is an exact algebraic identity around captured baseline kinematics. Query arithmetic terms are measured errors propagated through that linear coefficient, not a rerun of a corrected forward model; explicit motion and closure residuals retain the difference.',
                              'No scientific acceptance or covariance is authorized by this bounded diagnostic.']}
    return result


def verify_equivalence(path):
    value = json.loads(Path(path).read_text())
    if value.get('schema') != 'orbit-poc-d03-equivalence-v1' or value.get('passed') is not True or len(value.get('checks', [])) != 52 or value.get('last_generation') != 4:
        raise ValueError('A successful exact 52-check D03 equivalence receipt is required')
    if value.get('diagnostic_only') is not True or value.get('scientific_validation_complete') is not False:
        raise ValueError('Equivalence receipt has invalid scientific scope')
    directories = [Path(p).resolve() for p in value.get('directories', [])]
    if len(directories) != 3 or len(set(directories)) != 3:
        raise ValueError('Require three distinct compared replay directories')
    counts = []
    for i, directory in enumerate(directories):
        generations = {int(p.name.split('.')[1]) for p in directory.glob('qr.*.factor.json')}
        if not generations or generations != set(range(1, max(generations)+1)):
            raise ValueError('Compared generations are not contiguous')
        if (i == 0 and max(generations) <= 4) or (i > 0 and max(generations) != 4):
            raise ValueError('Wrong reference or diagnostic generation bounds')
        counts.append(max(generations))
    suffixes = ['R.bin', 'z.bin', 'rhs.bin', 'parameters.tsv', 'delta.tsv',
                'singular_values.txt', 'profile.json', 'bias_coordinates.tsv',
                'nuisance_coordinates.tsv', 'receiver_times.tsv']
    retired = {'R.bin': 'superseded_triangular_factor', 'z.bin': 'superseded_transformed_target', 'rhs.bin': 'superseded_transformed_target_alias'}
    timing = {'peak_child_rss_bytes', 'child_user_seconds', 'child_system_seconds'}
    def strip_timing(v):
        if isinstance(v, list): return [strip_timing(x) for x in v]
        if isinstance(v, dict): return {k: strip_timing(x) for k, x in v.items() if k not in timing}
        return v
    def files_at(check, suffix, generation, rows=False):
        objs = check.get('files', [])
        if len(objs) != 3: raise ValueError('Each comparison must identify exactly three files')
        expected = [d/f'qr.{generation}.{suffix}' for d in directories]
        for obj, p in zip(objs, expected):
            allowed = {p, Path(str(p)+'.gz')} if rows else {p}
            if Path(obj['path']).resolve() not in allowed: raise ValueError('Swapped comparison file identity')
            if rows and p.exists() == Path(str(p)+'.gz').exists(): raise ValueError('Ambiguous or missing original row file')
        return objs
    for generation in range(1, 5):
        block = value['checks'][(generation-1)*13:generation*13]
        for check, suffix in zip(block[:10], suffixes):
            if check.get('kind') != 'exact_bytes_or_original_retired_factor_identity': raise ValueError('Wrong byte check kind')
            objs = files_at(check, suffix, generation)
            for index, obj in enumerate(objs):
                if 'retention_receipt' in obj:
                    if suffix not in retired or generation >= counts[index]: raise ValueError('Illegal retired factor substitution')
                    if Path(obj['path']).exists(): raise ValueError('Retired identity cannot substitute for an existing binary')
                    receipt = obj['retention_receipt']; assert_artifact(receipt)
                    if Path(receipt['path']).resolve() != directories[index]/f'qr.{generation}.retention.json':
                        raise ValueError('Swapped retirement receipt')
                    rr = json.loads(Path(receipt['path']).read_text())
                    if rr.get('schema') != 'orbit-poc-native-factor-retention-v1' or rr.get('status') != 'completed': raise ValueError('Invalid retirement status')
                    matches = [x for x in rr.get('artifacts', []) if x.get('path') == obj['path']]
                    if len(matches) != 1 or matches[0].get('role') != retired[suffix] or any(matches[0].get(k) != obj[k] for k in ('sha256', 'bytes')):
                        raise ValueError('Retirement identity mismatch')
                    if not re.fullmatch('[0-9a-f]{64}', obj['sha256']) or type(obj['bytes']) is not int or obj['bytes'] < 16:
                        raise ValueError('Invalid retired binary identity')
                    fm = json.loads((directories[index]/f'qr.{generation}.factor.json').read_text())
                    if fm.get('keep_intermediate_factors') is not False: raise ValueError('Retirement conflicts with factor policy')
                else: assert_artifact(obj)
            if len({(x['sha256'], x['bytes']) for x in objs}) != 1: raise ValueError('Compared byte identities differ')
        check = block[10]
        if check.get('kind') != 'exact_decompressed_row_bytes': raise ValueError('Wrong original row comparison kind')
        objs = files_at(check, 'rows.tsv', generation, rows=True); row_hashes = []
        for obj in objs:
            assert_artifact(obj); p = Path(obj['path']); raw = p.read_bytes()
            if p.suffix == '.gz': raw = gzip.decompress(raw)
            row_hashes.append(hashlib.sha256(raw).hexdigest())
        if len(set(row_hashes)) != 1 or row_hashes[0] != check.get('sha256'): raise ValueError('Original row hashes differ')
        for check, suffix in zip(block[11:], ('factor.json', 'nuisance_line_search.json')):
            exclusions = ['spool_directory'] if suffix == 'factor.json' else sorted(timing)
            if check.get('kind') != 'exact_json_except_explicit_operational_fields' or check.get('excluded_keys') != exclusions:
                raise ValueError('Wrong JSON comparison kind or exclusions')
            objs = files_at(check, suffix, generation); vals = []
            for obj in objs:
                assert_artifact(obj); v = json.loads(Path(obj['path']).read_text())
                if suffix == 'factor.json':
                    if 'spool_directory' not in v: raise ValueError('Missing explicit spool path')
                    del v['spool_directory']
                else: v = strip_timing(v)
                vals.append(v)
            if not vals[0] == vals[1] == vals[2]: raise ValueError('Compared numerical metadata differ')
    stops = value.get('stop_receipts', [])
    if len(stops) != 2: raise ValueError('Missing diagnostic stop receipts')
    expected_stop = {'schema': 'orbit-poc-d03-generation-stop-v1', 'diagnostic_only': True,
                     'scientific_complete': False, 'completed_generations': 4,
                     'reason': 'bounded diagnostic stopped before generation5'}
    for obj, directory in zip(stops, directories[1:]):
        if Path(obj['path']).resolve() != directory/'qr.diagnostic-incomplete.json': raise ValueError('Swapped stop receipt')
        assert_artifact(obj)
        if json.loads(Path(obj['path']).read_text()) != expected_stop: raise ValueError('Changed diagnostic stop')
    return value


def assert_artifact(obj):
    found = artifact(Path(obj['path']))
    if found['sha256'] != obj['sha256'] or found['bytes'] != obj['bytes']:
        raise ValueError(f'Changed equivalence artifact: {obj["path"]}')


def verify_analysis_paths(eq, factor, search):
    directories = eq.get('directories', [])
    if len(directories) != 3: raise ValueError('Missing comparator replay directory identities')
    replay = Path(directories[2]).resolve()
    if Path(factor).resolve() != replay/'qr.4.factor.json' or Path(search).resolve() != replay/'qr.4.nuisance_line_search.json':
        raise ValueError('Analysis inputs are not the compared trace-on generation4')
    return str(replay/'qr.4')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trace-directory', type=Path, required=True)
    p.add_argument('--equivalence', type=Path, required=True)
    p.add_argument('--factor', type=Path, required=True)
    p.add_argument('--line-search', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists(): p.error('Output already exists')
    try:
        eq = verify_equivalence(args.equivalence)
        expected_stem = verify_analysis_paths(eq, args.factor, args.line_search)
        files = sorted(args.trace_directory.glob('nuisance-trace-*.tsv'))
        if not files: raise ValueError('No diagnostic traces')
        with localcontext() as ctx:
            ctx.prec = PRECISION
            equations, updates, constraints, counts = load_trace(files)
            if any(e.identity[0] not in {str(p) for p in files} for e in equations): raise ValueError('Unexpected trace file identity')
            # Stem identity is checked without keeping every large trace record.
            for path in files:
                first = next(records(path), None)
                if first is None or first.stem != expected_stem: raise ValueError('Trace stem differs from the compared replay')
            result = analyze(equations, updates, constraints, json.loads(args.factor.read_text()), json.loads(args.line_search.read_text()))
        result['trace_counts'] = counts
        result['artifacts'] = {'analyzer': artifact(Path(__file__)), 'equivalence': artifact(args.equivalence),
                               'factor': artifact(args.factor), 'line_search': artifact(args.line_search),
                               'traces': [artifact(path) for path in files]}
        result['status'] = 'completed'
    except Exception as error:
        result = {'schema': 'orbit-poc-d03-decimal-analysis-v1', 'status': 'failed_closed',
                  'error': repr(error), 'scientific_validation_complete': False, 'covariance_authorized': False}
    with args.output.open('x') as f:
        json.dump(result, f, indent=2, sort_keys=True); f.write('\n')
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
