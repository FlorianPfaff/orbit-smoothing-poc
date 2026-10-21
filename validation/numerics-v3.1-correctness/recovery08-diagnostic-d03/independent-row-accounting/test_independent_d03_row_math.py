import importlib.util,json,hashlib,struct,copy
from pathlib import Path
from decimal import Decimal as D,localcontext
import pytest
spec=importlib.util.spec_from_file_location('independent',Path(__file__).with_name('independent_d03_row_math.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def fixture(tmp):
    stage='';stem='/fixture/on/qr.4';events=0;lines=[]
    def row(phase,alpha,ev,stage,value,row=0,col=0,block=(0,1,2)):
        nonlocal events
        events+=1;f=float(value);bits=struct.pack('>d',f).hex()
        lines.append('\t'.join(map(str,[stem,phase,float(alpha).hex(),*block,row,'',stage,'double',col,f.hex(),bits,ev,events,0]))+'\n')
    def residual(phase,alpha,ev,values):
        for i,v in enumerate(values):
            row(phase,alpha,ev,'retained_original_precise.high',v,i);row(phase,alpha,ev,'retained_original_precise.low',0,i);row(phase,alpha,ev,'retained_original_native',v,i)
        row(phase,alpha,ev,'constraint_original_rhs',4 if alpha==0 else 2.5,0,block=(2**64-1,2**64-1,8))
        row(phase,alpha,ev,'constraint_original_coefficient',3,0,block=(2**64-1,2**64-1,8))
    residual('baseline',0,1,[2,3])
    for i,v in enumerate([2,3]):row('joint',0,2,'joint_original_precise.high',v,i);row('joint',0,2,'joint_original_precise.low',0,i)
    row('joint',0,2,'parameter_requested',.5)
    row('joint',0,2,'joint_global_design',2)
    row('joint',0,2,'joint_local_design',1,1)
    row('joint',0,2,'joint_local_requested',.25)
    for i,v in enumerate([1,.25]):row('joint',0,2,'joint_total_native_influence',v,i)
    residual('trial',0,3,[2,3]);residual('trial',1,4,[1.125,2.75])
    path=tmp/'trace.tsv';path.write_text(''.join(lines));pins=[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}]
    analysis={'original_objective_rows':3,'observation_rows':2,'separate_constraint_rows':1,'prediction_arithmetic_comparison':{k:'7.09375' for k in ['precise_targets_decimal_joint','rounded_targets_decimal_joint','precise_targets_native_joint','rounded_targets_native_joint']},'trials':[{'alpha':'0','actual_reduction':'0','requested_original_row_prediction':'0','largest_disagreement_rows':[]},{'alpha':'1','actual_reduction':'6.9609375','requested_original_row_prediction':'7.09375','largest_disagreement_rows':[{'key':[0,1,2,0],'actual_minus_prediction_contribution':'-.1328125'}]}]}
    return pins,stem,analysis

def test_independent_original_joint_cost_and_constraints(tmp_path):
    pins,stem,analysis=fixture(tmp_path)
    with localcontext() as c:
        c.prec=128;ledgers,parts,counts=m.read_rows(pins,stem,set());r=m.compare(ledgers,parts,analysis)
    assert r['original_objective_rows']==3 and D(r['trials'][1]['actual_minus_prediction'])==D('-0.1328125')
    assert all(D(x)==0 for x in r['checks_minus_reported'].values())
@pytest.mark.parametrize('change',['hash','stem','rowcount','prediction','missinglow'])
def test_bad_attribution_or_accounting_fails(tmp_path,change):
    pins,stem,analysis=fixture(tmp_path)
    if change=='hash':pins[0]['sha256']='0'*64
    if change=='stem':stem='/other/qr.4'
    if change=='rowcount':analysis['original_objective_rows']=4
    if change=='prediction':analysis['prediction_arithmetic_comparison']['precise_targets_decimal_joint']='8'
    with localcontext() as c:
        c.prec=128
        with pytest.raises(ValueError):
            ledgers,parts,counts=m.read_rows(pins,stem,set())
            if change=='missinglow':next(v for k,v in ledgers.items() if k[2]=='baseline')['residual_low'].pop((0,0,1,2,0))
            m.compare(ledgers,parts,analysis)
def test_hex_decode_preserves_more_than_binary64():
    with localcontext() as c:
        c.prec=128
        assert m.hexvalue('0x1.0000000000000001p+0')==D(1)+D(2)**-64
        assert m.hexvalue('-0x8.000000000000001p-3')==-D(1)-D(2)**-63

def test_all_row_clock_cache_and_candidate_coefficient(tmp_path):
    pins,stem,analysis=fixture(tmp_path)
    path=Path(pins[0]['path']);raw=path.read_text().splitlines(True);out=[]
    def operand(fields,stage,value,row):
        f=float(value);new=list(fields);new[6]=str(row);new[8]=stage;new[10]='0';new[11]=f.hex();new[12]=struct.pack('>d',f).hex();return '\t'.join(new)+'\n'
    for line in raw:
        fields=line.rstrip('\n').split('\t')
        if fields[8]=='retained_original_precise.high' and fields[6]=='0':
            for stage,value in [('observed',2),('receiver_clock_seconds',.25 if fields[1]!='trial' or float.fromhex(fields[2])==0 else .25+2**-40),('transmitter_clock_seconds',.125),('transmitter_scale',1),('rDotRecv',.001),('rDotTrans',.002)]:out.append(operand(fields,stage,value,0))
            for row in (0,1):out.append(operand(fields,'sigma',2,row))
        out.append(line)
    path.write_text(''.join(out));pins[0].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
    with localcontext() as c:
        c.prec=128;ledgers,parts,counts=m.read_rows(pins,stem,set());r=m.compare(ledgers,parts,analysis)
        assert r['clock_operand_rows']==2 and len(r['clock_row_cache'])==2
        effect=r['trials'][1]['candidate_clock_coefficient_effect_times_actual_mean_residual']
        rr=D.from_float(.001);rt=D.from_float(.002);n=D.from_float(1.+.002-.001)
        scale=D(2)**-40*D(299792458)/2*((D(2)+D('1.125'))/2+(D(3)+D('2.75'))/2)
        assert D(effect['moving_receiver_exact_minus_native'])==((1-rr)/(1-rt)-n)*scale
        assert abs(D(effect['fixed_receiver_exact_minus_native'])-(1/(1-rt)-n)*scale)<D('1e-100')
