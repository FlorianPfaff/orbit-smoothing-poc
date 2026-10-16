"""Freeze a bounded deterministic RHS sensitivity family, before solver execution.

This modifies only external captured RHS arrays, never physical/benchmark inputs.
It declares both signs of two directions at two scales for each exact anchor.
"""
from __future__ import annotations
import argparse, array, hashlib, json, math, pathlib, struct, sys
ANCHORS=(
 ('historical_large','tangent-telemetry-02/run/replay/captured-system.bin','b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'),
 ('current_small','tangent-telemetry-03/run/replay/captured-system.bin','f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044'),
 ('current_large','tangent-telemetry-04/run/replay/captured-system.bin','b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3'),
)
def sha(data):return hashlib.sha256(data).hexdigest()
def decode(raw):
    if len(raw)<72 or raw[:16]!=b'OPCTANGENT001\n\0\0':raise ValueError('capture magic/length')
    version,n,intervals,terms,count,dt,duration=struct.unpack_from('<5Q2d',raw,16)
    if version!=1 or n<2 or n>1000000 or intervals!=n-1 or count!=6*n or terms>100*intervals:raise ValueError('dimensions')
    if not math.isfinite(dt) or not math.isfinite(duration) or min(dt,duration)<=0:raise ValueError('time')
    pos=72+2*n*18*8;counted=0
    if pos>len(raw):raise ValueError('Jacobian truncation')
    for k in range(intervals):
        if pos+8>len(raw):raise ValueError('interval truncation')
        amount=struct.unpack_from('<Q',raw,pos)[0];pos+=8
        if amount>100 or counted+amount>terms or pos+amount*24>len(raw):raise ValueError('interval terms')
        for j in range(amount):
            index,integral,moment=struct.unpack_from('<Q2d',raw,pos+j*24)
            if index>=n or not all(map(math.isfinite,(integral,moment))):raise ValueError('invalid term')
        counted+=amount;pos+=amount*24
    if counted!=terms or pos+count*8!=len(raw):raise ValueError('capture size/term total')
    rhs=array.array('d');rhs.frombytes(raw[pos:])
    if sys.byteorder!='little':rhs.byteswap()
    if any(not math.isfinite(v) for v in rhs):raise ValueError('nonfinite RHS')
    return pos,rhs,n,dt,duration

def encode(values):
    a=array.array('d',values)
    if sys.byteorder!='little':a.byteswap()
    return a.tobytes()

def perturb(rhs,scale,direction,sign):
    half=len(rhs)//2
    balanced=[v if i<half else v*1000. for i,v in enumerate(rhs)]
    norm=math.sqrt(math.fsum(v*v for v in balanced))
    if not norm>0:raise ValueError('anchor has zero norm')
    # Explicit order over [r0...rN, 1000*v0...1000*vN]; no random draws.
    d=[math.sin(2.*math.pi*(i+1)/len(rhs)) if direction=='smooth' else (1. if i%2==0 else -1.) for i in range(len(rhs))]
    dn=math.sqrt(math.fsum(v*v for v in d))
    size=sign*scale*norm/dn
    out=[math.fsum((v,size*d[i]/(1. if i<half else 1000.))) for i,v in enumerate(rhs)]
    actual=[(out[i]-rhs[i])*(1. if i<half else 1000.) for i in range(len(rhs))]
    relative=math.sqrt(math.fsum(v*v for v in actual))/norm
    changed=sum(a!=b for a,b in zip(out,rhs))
    if not changed or not .99*scale<=relative<=1.01*scale:raise ValueError('perturbation did not survive binary64 rounding')
    return out,{'changed_entries':changed,'actual_relative_balanced_norm':relative,'anchor_balanced_norm':norm}

def generate(base,output):
    if output.exists():raise FileExistsError('immutable family destination already exists')
    # Verify every exact anchor before creating any output.
    sources=[]
    for name,relative,expected in ANCHORS:
        path=base/relative;raw=path.read_bytes()
        if sha(raw)!=expected:raise ValueError('anchor identity mismatch: '+name)
        decoded=decode(raw);sources.append((name,path,raw,decoded))
    output.mkdir(parents=True);(output/'captures').mkdir()
    cases=[];anchors=[]
    for name,path,raw,(offset,rhs,n,dt,duration) in sources:
        anchors.append({'id':name,'path':str(path),'sha256':sha(raw),'operator_bytes':offset,'operator_sha256':sha(raw[:offset]),'epochs':n,'dt':dt,'duration':duration})
        variants=[('original',None,0.,0,None)]
        variants += [(f'{direction}-{scale:g}-{sign:+d}',direction,scale,sign,None) for direction in ('smooth','alternating') for scale in (1e-12,1e-9) for sign in (-1,1)]
        for label,direction,scale,sign,_ in variants:
            metadata={'changed_entries':0,'actual_relative_balanced_norm':0.}
            payload=raw
            if direction:
                values,metadata=perturb(rhs,scale,direction,sign);payload=raw[:offset]+encode(values)
            case_id=name+'-'+label;target=output/'captures'/(case_id+'.bin')
            target.write_bytes(payload)
            if target.read_bytes()[:offset]!=raw[:offset]:raise AssertionError('operator changed')
            cases.append({'id':case_id,'path':str(target),'sha256':sha(payload),'bytes':len(payload),'anchor':name,'direction':direction,'sign':sign,'relative_scale':scale,**metadata})
    order=[]
    for i,case in enumerate(cases):
        modes=('baseline','wide') if i%2==0 else ('wide','baseline')
        for profile in modes:order.append({'attempt_id':f'{len(order)+1:02d}-{case["id"]}-{profile}','case_id':case['id'],'profile':profile})
    manifest={'schema_version':1,'kind':'bounded-captured-tangent-rhs-sensitivity','generator_sha256':sha(pathlib.Path(__file__).read_bytes()),
      'scope':'diagnostic only; not a scientific trial, production fit or benchmark replacement',
      'input_units':'physical binary64 positions and velocities; balance velocity by1000 only for norm/direction',
      'direction_definition':{'smooth':'sin(2*pi*(i+1)/M), i=0..M-1 in balanced [r,1000v] coordinates','alternating':'(-1)^i, i=0..M-1 in balanced [r,1000v] coordinates','normalization':'Euclidean norm using math.fsum; actual final binary64 capture bytes frozen by SHA256'},
      'acceptance':{'relative_residual':2e-12,'maximum_iterations':120,'restart':20,'certificate':'113-bit independent operator on actual returned physical binary64 state, using double tolerance cast to long double'},
      'failure_policy':'retain every numerical failure and continue; never replace cases or alter criteria based on outcomes',
      'anchors':anchors,'cases':cases,'execution_order':order,'case_count':27,'attempt_count':54}
    assert len(cases)==27 and len(order)==54
    text=json.dumps(manifest,indent=2,sort_keys=True)+'\n';(output/'manifest.json').write_text(text)
    return {'manifest':str(output/'manifest.json'),'sha256':sha(text.encode()),'cases':27,'attempts':54}
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True)
    args=parser.parse_args();print(json.dumps(generate(args.base,args.output),sort_keys=True))
