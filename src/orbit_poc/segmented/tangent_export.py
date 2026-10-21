"""Bounded exact decoder/lift for native tangent v1 and typed batch v2.

The complete interpolation algebra is dyadic-rational until the explicit
binary64 materialization boundary. This does not alter the GNSS query path.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
import re

V1 = 'orbit-poc-segmented-tangent-v1'
V2 = 'orbit-poc-segmented-tangent-v2'
SEMANTICS = 'actual_batch_mode_anchor_high_low_v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Expected finite native binary64 coefficient')
    return Fraction(value)


def hexadecimal(value):
    """Decode both stored long-double components without a float intermediate."""
    require(isinstance(value, str) and len(value) <= 160, 'Invalid hexadecimal component')
    match = re.fullmatch(r'([+-]?)0x([0-9a-fA-F]+)(?:\.([0-9a-fA-F]*))?p([+-]?\d+)', value)
    require(match is not None, 'Expected exact native hexadecimal component')
    sign, whole, part, exponent = match.groups()
    part = part or ''
    power = int(exponent)-4*len(part)
    require(abs(power) <= 20000 and len(whole+part) <= 128, 'Hexadecimal component outside declared range')
    significand = int(whole+part, 16) * (-1 if sign == '-' else 1)
    return Fraction(significand*2**power) if power >= 0 else Fraction(significand, 2**(-power))


@dataclass(frozen=True)
class ExactStencil:
    mode: str
    indices: tuple
    high: tuple
    low: tuple
    anchor: int | None

    def evaluate(self, values):
        """Apply the actual branch, with no coefficient normalization guess."""
        x = [Fraction(values[i]) for i in self.indices]
        weights = [h+l for h,l in zip(self.high,self.low)]
        if self.mode == 'exact':
            return x[0]
        if self.mode == 'anchored_twofold':
            ref = x[self.anchor]
            return ref + sum((w*(value-ref) for w,value in zip(weights,x)), Fraction(0))
        return sum((w*value for w,value in zip(weights,x)), Fraction(0))

    def coefficients(self):
        """Exact algebraic substitution of the branch into deterministic rows."""
        weights = [h+l for h,l in zip(self.high,self.low)]
        if self.mode == 'exact':
            weights = [Fraction(1)]
        elif self.mode == 'anchored_twofold':
            # The anchor term w_a*(x_a-x_a) is exactly zero. Preserve the
            # non-normalized stored weights and form1-sum(w_i,i!=a) exactly.
            weights[self.anchor] = 1-sum((w for i,w in enumerate(weights) if i != self.anchor), Fraction(0))
        return tuple(zip(self.indices, weights))


def decode_stencil(record, schema, epochs):
    if schema == V1:
        require(isinstance(record,list) and bool(record), 'Empty legacy flat halo')
        terms=[]
        for row in record:
            require(isinstance(row,list) and len(row)==4, 'Invalid legacy flat halo term')
            index, rounded, high, low = row
            require(type(index) is int and 0<=index<epochs, 'Legacy halo index outside grid')
            h,l=hexadecimal(high),hexadecimal(low)
            number(rounded)
            try: combined=float(h+l)
            except OverflowError as error: raise ValueError('Legacy halo coefficient overflow') from error
            require(math.isfinite(combined) and abs(combined-rounded)<=math.ulp(rounded), 'Legacy rounded coefficient disagrees')
            terms.append((index,h,l))
        mode,anchor='legacy_flat',None
    elif schema == V2:
        require(isinstance(record,dict) and set(record)=={'mode','derivative','anchor','terms'}, 'Unknown typed stencil fields')
        mode=record['mode'];anchor=record['anchor']
        require(mode in ('exact','ordinary','anchored_twofold') and type(record['derivative'])is int and record['derivative']==0, 'Unsupported typed stencil mode/derivative')
        require(isinstance(record['terms'],list) and bool(record['terms']), 'Empty typed stencil')
        terms=[]
        for row in record['terms']:
            require(isinstance(row,list) and len(row)==3, 'Invalid typed stencil term')
            index,high,low=row
            require(type(index)is int and 0<=index<epochs, 'Typed stencil index outside grid')
            terms.append((index,hexadecimal(high),hexadecimal(low)))
        if mode=='anchored_twofold':
            require(type(anchor)is int and 0<=anchor<len(terms), 'Actual anchor outside typed stencil')
        else:
            require(anchor is None, 'Unanchored mode cannot invent an anchor')
        if mode=='exact':
            require(len(terms)==1 and terms[0][1]==1 and terms[0][2]==0, 'Exact stencil must be identity')
    else:
        raise ValueError('Unsupported tangent export schema')
    require(len({x[0]for x in terms})==len(terms), 'Repeated interpolation node')
    return ExactStencil(mode,tuple(x[0]for x in terms),tuple(x[1]for x in terms),tuple(x[2]for x in terms),anchor)


@dataclass
class ExactTangentLift:
    metadata: dict
    rows: list
    initial_rhs: list
    stencils: dict

    def binary64(self):
        """One explicit rounding boundary with a complete nonzero-error ledger.

        Existing sparse QR is binary64. No tiny nonzero coefficient may be
        silently discarded: overflow and underflow-to-zero fail closed.
        """
        entries=[];rhs=[];errors=[]
        def convert(value,location):
            try: rounded=float(value)
            except OverflowError as error: raise ValueError('Lifted coefficient overflows binary64') from error
            require(math.isfinite(rounded) and (value==0 or rounded!=0), 'Nonzero lifted coefficient lost at binary64 boundary')
            error=Fraction.from_float(rounded)-value
            require(abs(error)<=Fraction(math.ulp(rounded))/2, 'Unexpected binary64 conversion error')
            if error:
                errors.append({'location':location,'exact_numerator':str(value.numerator),'exact_denominator':str(value.denominator),
                               'rounded_hex':rounded.hex(),'error_numerator':str(error.numerator),'error_denominator':str(error.denominator)})
            return rounded
        for row,terms in enumerate(self.rows):
            for column,value in sorted(terms.items()):
                if value:entries.append((row,column,convert(value,('matrix',row,column))))
        for row,values in enumerate(self.initial_rhs):
            rhs.append([convert(value,('rhs',row,column))for column,value in enumerate(values)])
        receipt={'schema':'orbit-poc-exact-tangent-materialization-v1','input_schema':self.metadata['schema'],
                 'interpolation_algebra':'exact_dyadic_branch_and_anchor','rounding_boundary':'explicit_once_after_exact_row_coalescence',
                 'rounded_nonexact_entries':errors,'nonzero_coefficients_discarded':0,'shape':[len(self.rows),len(self.rows)],
                 'scope':'This arithmetic ledger does not certify native/lifted agreement or numerical convergence.'}
        return entries,rhs,receipt


def lift_tangent_export(records, maximum_epochs=1000):
    """Build the same local x=b+Kx equations from strict v1 or typed v2 data."""
    require(isinstance(records,list) and len(records)>=3 and records[-1]=={'kind':'complete'}, 'Incomplete tangent export')
    meta=records[0]
    required={'kind','schema','profile','epochs','dt','initial_velocity_scale','maximum_tangent_relative_residual',
              'nominal_force_history','new_process_priors','forcing_design'}
    schema=meta.get('schema')
    require(schema in (V1,V2), 'Unsupported tangent export schema')
    require(set(meta)==required|({'interpolation_semantics'}if schema==V2 else set()), 'Unknown tangent metadata fields')
    require(meta['kind']=='metadata' and meta['profile'] in ('synthetic_complete_v1','flight_gravity_drag_v1'), 'Invalid tangent profile')
    require(meta['nominal_force_history']=='unchanged_whole_arc' and meta['new_process_priors'] is False
            and meta['forcing_design']=='separate_native_variation_of_constants_export', 'Changed tangent physical scope')
    if schema==V2:require(meta['interpolation_semantics']==SEMANTICS, 'Unknown typed interpolation semantics')
    n=meta['epochs'];dt=number(meta['dt']);scale=number(meta['initial_velocity_scale']);residual=number(meta['maximum_tangent_relative_residual'])
    require(type(n)is int and 2<=n<=maximum_epochs and dt>0 and scale>0 and 0<=residual<=number(2e-12), 'Invalid tangent dimensions/guard or bounded lift resource limit')
    samples={};quadrature={};stencils={}
    for item in records[1:-1]:
        kind=item.get('kind');channel=item.get('channel')
        require(channel in ('main','drag'), 'Unknown tangent force channel')
        if kind=='sample':
            keys=('position_halo','velocity_halo')if schema==V1 else('position_stencil','velocity_stencil')
            require(set(item)=={'kind','channel','index','time','Ar','Av',*keys}, 'Unknown or mixed tangent sample schema')
            index=item['index'];require(type(index)is int and index>=0 and (channel,index)not in samples, 'Invalid/repeated tangent sample')
            time=item['time'];require(isinstance(time,list)and len(time)==2 and type(time[0])is int and 0<=number(time[1])<1, 'Invalid split epoch')
            jac=[]
            for key in ('Ar','Av'):
                require(isinstance(item[key],list)and len(item[key])==9, 'Invalid force Jacobian')
                jac.append(tuple(number(value)for value in item[key]))
            decoded=tuple(decode_stencil(item[key],schema,n)for key in keys)
            if channel=='main' or index<n:
                require(index<n and all(s.coefficients()==((index,Fraction(1)),)for s in decoded), 'Native grid sample is not exact direct state')
            samples[channel,index]=(jac,decoded);stencils[channel,index]=decoded
        elif kind=='quadrature':
            require(set(item)=={'kind','channel','interval','terms'}, 'Unknown quadrature fields')
            k=item['interval'];require(type(k)is int and 0<=k<n-1 and (channel,k)not in quadrature, 'Invalid/repeated quadrature interval')
            require(isinstance(item['terms'],list), 'Invalid quadrature terms')
            terms=[]
            for term in item['terms']:
                require(isinstance(term,list)and len(term)==3 and type(term[0])is int and term[0]>=0, 'Invalid quadrature term')
                terms.append((term[0],number(term[1]),number(term[2])))
            quadrature[channel,k]=terms
        else:raise ValueError('Unknown tangent export record')
    channels={channel for channel,_ in samples}
    require('main'in channels and {channel for channel,_ in quadrature}==channels, 'Missing tangent channel')
    expected_channels={'main'} if meta['profile']=='synthetic_complete_v1' else {'main','drag'}
    require(channels==expected_channels, 'Tangent force channels disagree with configured profile')
    for channel in channels:
        ids=sorted(index for name,index in samples if name==channel)
        require(ids==list(range(len(ids)))and len(ids)>=n and (channel!='main'or len(ids)==n), 'Incomplete tangent sample grid')
        require(sorted(k for name,k in quadrature if name==channel)==list(range(n-1)), 'Incomplete tangent quadrature')
    rows=[{}for _ in range(6*n)];rhs=[[Fraction(0)for _ in range(6)]for _ in rows]
    for c in range(6):rows[c][c]=Fraction(1);rhs[c][c]=Fraction(1)if c<3 else scale
    for k in range(n-1):
        for c in range(6):
            row=rows[6*(k+1)+c];row[6*(k+1)+c]=Fraction(1);row[6*k+c]=Fraction(-1)
            if c<3:row[6*k+c+3]=-dt
            for channel in sorted(channels):
                for sample,integral,moment in quadrature[channel,k]:
                    require((channel,sample)in samples, 'Quadrature refers to absent sample')
                    jac,interp=samples[channel,sample];factor=dt*integral-moment if c<3 else integral
                    for offset,derivative,stencil in ((0,jac[0],interp[0]),(3,jac[1],interp[1])):
                        for epoch,weight in stencil.coefficients():
                            for component in range(3):
                                column=6*epoch+offset+component
                                row[column]=row.get(column,Fraction(0))-factor*derivative[3*(c%3)+component]*weight
    return ExactTangentLift(meta,rows,rhs,stencils)
