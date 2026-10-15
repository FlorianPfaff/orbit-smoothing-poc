"""Independent128-digit accounting from retained D03 rows; no native execution."""
import argparse,hashlib,json,struct
from pathlib import Path
from collections import defaultdict
from decimal import Decimal as D,localcontext
ZERO=D(0)
MAIN={'retained_original_precise.high','retained_original_precise.low','retained_original_native','joint_original_precise.high','joint_original_precise.low','joint_global_design','joint_local_design','joint_local_requested','joint_total_native_influence','parameter_requested','constraint_original_rhs','constraint_original_coefficient'}
PAIRS={'range_distance','range_relativistic_dot','range_clock','range_residual','after_receiver_correction','after_transmitter_correction','after_ambiguity','after_models'}
CLOCK={'rDotRecv','rDotTrans','receiver_clock_seconds','transmitter_clock_seconds','sigma','transmitter_scale'}
PARTS={n+suffix for n in PAIRS for suffix in ('.high','.low')}|{'sigma','transmitter_scale','range_shapiro','observed'}
def require(ok,message):
    if not ok:raise ValueError(message)
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def hexvalue(raw):
    s=raw.decode() if isinstance(raw,bytes) else raw
    sign=-1 if s.startswith('-') else 1;s=s.lstrip('+-');mant,exp=s.split('p');whole,*fraction=mant[2:].split('.');tail=fraction[0] if fraction else ''
    return D(sign*int(whole+tail,16))*D(2)**(int(exp)-4*len(tail))
def put(mapping,key,value):
    require(key not in mapping,'Duplicate original captured field '+repr(key));mapping[key]=value

def read_rows(pins,stem,top_rows):
    ledgers={};frames={};selected_parts={};trace_counts=[]
    for pin in pins:
        path=Path(pin['path']);h=hashlib.sha256();count=0
        with path.open('rb') as stream:
            for line in stream:
                h.update(line);count+=1
                require(line.count(b'\t')==15,'Bad trace column count')
                fields=line.rstrip(b'\n').split(b'\t',9);stage=fields[8].decode()
                if stage not in MAIN and stage not in PARTS and stage not in CLOCK:continue
                tail=fields[9].split(b'\t');require(len(tail)==7,'Bad selected trace layout')
                if tail[6]!=b'0':continue
                phase=fields[1].decode();alpha=float.fromhex(fields[2].decode())
                require(fields[0].decode()==stem and phase in ('baseline','joint','trial'),'Wrong trace attribution')
                if phase=='trial':require(alpha in (0.,1.),'Unexpected trial alpha')
                ident=(path.name,int(tail[4]),phase,alpha)
                block=tuple(int(v) for v in fields[3:6]);row=int(fields[6]);column=int(tail[1]);key=(0,*block,row)
                ledger=ledgers.setdefault(ident,defaultdict(dict))
                value=hexvalue(tail[2])
                if tail[0]==b'double':
                    native=struct.unpack('>d',bytes.fromhex(tail[3].decode()))[0]
                    require(D.from_float(native)==value,'Binary64 bits differ from numeric operand')
                if stage.startswith('retained_original_precise.'):
                    part=stage.rsplit('.',1)[1];put(ledger['residual_'+part],key,value)
                    if part=='low':
                        current=frames.get((ident,block),{})
                        if key in top_rows:selected_parts[ident,key]=dict(current)
                        if (row,0,'sigma') in current:
                            ledger['clock_operands'][key]={n:current[(row if n=='sigma' else 0),0,n] for n in CLOCK}
                elif stage=='retained_original_native':put(ledger['native_target'],key,value)
                elif stage.startswith('joint_original_precise.'):put(ledger['joint_'+stage.rsplit('.',1)[1]],key,value)
                elif stage=='parameter_requested':require(column==0,'Requested step is not a vector');put(ledger['x'],row,value)
                elif stage=='joint_global_design':put(ledger['A'],(key,column),value)
                elif stage=='joint_local_design':put(ledger['B'],(key,column),value)
                elif stage=='joint_local_requested':require(column==0,'Local step is not a vector');put(ledger['local'],(block,row),value)
                elif stage=='joint_total_native_influence':require(column==0,'Native influence is not a vector');put(ledger['native_influence'],key,value)
                elif stage=='constraint_original_rhs':put(ledger['constraint_rhs'],(1,block[2],row),value)
                elif stage=='constraint_original_coefficient':put(ledger['constraint_A'],((1,block[2],row),column),value)
                elif stage=='observed' and row==0 and column==0:frames[ident,block]={}
                elif (stage in CLOCK and fields[7]==b'') or any(k[1:4]==block for k in top_rows):
                    frames.setdefault((ident,block),{})[(row,column,stage)]=value
        require(h.hexdigest()==pin['sha256'] and path.stat().st_size==pin['bytes'],'Raw trace identity changed')
        trace_counts.append({'path':str(path),'sha256':h.hexdigest(),'bytes':path.stat().st_size,'records':count})
    return ledgers,selected_parts,trace_counts

def expansion(ledger,prefix):
    hi=ledger[prefix+'_high'];lo=ledger[prefix+'_low'];require(hi.keys()==lo.keys(),'Expansion support differs')
    return {k:hi[k]+lo[k] for k in hi}
def reduction(b,delta):
    require(b.keys()==delta.keys(),'Cost row support differs')
    return sum((b[k]*delta[k]-delta[k]*delta[k]/2 for k in sorted(b)),ZERO)
def close(a,b,label):
    err=a-b;require(abs(err)<=D('1e-90')*max(D(1),abs(a),abs(b)),label+' independent arithmetic differs');return str(err)
def weighted_components(parts,row):
    get=lambda stage:parts[row,0,stage]
    pair=lambda stage:get(stage+'.high')+get(stage+'.low')
    if (row,0,'sigma') not in parts:return None
    sigma=get('sigma');w=D.from_float(1./float(sigma));scale=parts[0,0,'transmitter_scale']
    rr=pair('range_residual');rc=pair('after_receiver_correction');tc=pair('after_transmitter_correction');am=pair('after_ambiguity');mo=pair('after_models')
    return {'distance':-scale*pair('range_distance')*w,'relativistic':-scale*D(2)/D(299792458)*pair('range_relativistic_dot')*w,'clock':-scale*pair('range_clock')*w,'shapiro':-scale*get('range_shapiro')*w,'receiver_correction':(rc-rr)*w,'transmitter_correction':(tc-rc)*w,'ambiguity':(am-tc)*w,'models_STEC':(mo-am)*w}

def compare(ledgers,parts,analysis):
    baseline=[k for k,v in ledgers.items() if k[2]=='baseline' and v.get('residual_high')];joint=[k for k,v in ledgers.items() if k[2]=='joint' and v.get('x')]
    trials=[k for k,v in ledgers.items() if k[2]=='trial' and v.get('residual_high')]
    require(len(baseline)==1 and len(joint)==1 and sorted(k[3] for k in trials)==[0.,1.],'Expected one baseline/joint and two ordinary trials')
    bi,ji=baseline[0],joint[0];bl,jl=ledgers[bi],ledgers[ji];bobs=expansion(bl,'residual');require(bobs==expansion(jl,'joint'),'Joint recovery changes original residuals')
    b={**bobs,**bl['constraint_rhs']};rounded={**bl['native_target'],**bl['constraint_rhs']};require(rounded.keys()==b.keys(),'Native target support differs')
    x=jl['x'];pred={k:ZERO for k in b};native={**jl['native_influence']}
    for (row,col),coef in jl['A'].items():require(row in pred and col in x,'Global design support differs');pred[row]+=coef*x[col]
    for (row,col),coef in jl['B'].items():pred[row]+=coef*jl['local'][(row[1:4],col)]
    for (row,col),coef in bl['constraint_A'].items():pred[row]+=coef*x[col]
    for row in bl['constraint_rhs']:native[row]=pred[row]
    require(len(b)==analysis['original_objective_rows'] and len(bobs)==analysis['observation_rows'] and len(bl['constraint_rhs'])==analysis['separate_constraint_rows'],'Complete objective row counts differ')
    expected=analysis['prediction_arithmetic_comparison'];checks={}
    combos={'precise_targets_decimal_joint':reduction(b,pred),'rounded_targets_decimal_joint':reduction(rounded,pred),'precise_targets_native_joint':reduction(b,native),'rounded_targets_native_joint':reduction(rounded,native)}
    for key,val in combos.items():checks[key]=close(val,D(expected[key]),key)
    trial_results=[];clock_cache=[]
    for ti in sorted(trials,key=lambda k:k[3]):
        tl=ledgers[ti];t={**expansion(tl,'residual'),**tl['constraint_rhs']};require(t.keys()==b.keys(),'Trial row support changed')
        require(tl['constraint_A']==bl['constraint_A'],'Separate constraint design changed')
        delta={k:b[k]-t[k] for k in b};alpha=D.from_float(ti[3]);request={k:alpha*pred[k] for k in pred}
        actual=reduction(b,delta);prediction=reduction(b,request);reported=next(v for v in analysis['trials'] if D(v['alpha'])==alpha)
        if alpha==0:require(all(v==0 for v in delta.values()),'Zero-update retained rows changed')
        errors={k:(delta[k]-request[k])*(b[k]-(delta[k]+request[k])/2) for k in b}
        checks['actual_'+str(alpha)]=close(actual,D(reported['actual_reduction']),'actual reduction')
        checks['prediction_'+str(alpha)]=close(prediction,D(reported['requested_original_row_prediction']),'requested reduction')
        require(abs(sum(errors.values(),ZERO)-(actual-prediction))<D('1e-90'),'Independent row discrepancy does not conserve objective difference')
        top=[]
        for item in reported['largest_disagreement_rows']:
            oldkey=item['key'];key=(1,*oldkey[1:]) if oldkey[0]=='constraint' else (0,*oldkey)
            err=errors[key];check=close(err,D(item['actual_minus_prediction_contribution']),'top row discrepancy')
            record={'key':oldkey,'independent_discrepancy':str(err),'minus_reported':check}
            if key[0]==0 and (bi,key) in parts and (ti,key) in parts:
                bc=weighted_components(parts[bi,key],key[-1]);tc=weighted_components(parts[ti,key],key[-1])
                if bc is not None and tc is not None:
                    changes={n:bc[n]-tc[n] for n in bc};reported_changes=item['component_changes'];record['component_changes']={n:str(v) for n,v in changes.items()}
                    for name in ('distance','relativistic','clock','shapiro','ambiguity','models_STEC'):
                        close(changes[name],D(reported_changes[name]),'selected component '+name)
                    record['receiver_equation_change_minus_primitive_parts']=str(changes['receiver_correction']-D(reported_changes['receiver_bias'])-D(reported_changes['receiver_antenna']))
                    record['transmitter_equation_change_minus_primitive_parts']=str(changes['transmitter_correction']-D(reported_changes['transmitter_bias'])-D(reported_changes['transmitter_antenna']))
            top.append(record)
        clock_effects=defaultdict(lambda:ZERO)
        if bl.get('clock_operands'):
            require(bl['clock_operands'].keys()==tl['clock_operands'].keys(),'Stored clock operand support changed')
            for key,before in bl['clock_operands'].items():
                after=tl['clock_operands'][key];require(before['sigma']==after['sigma'] and before['transmitter_scale']==after['transmitter_scale'],'Clock weight/scale changed')
                rr,rt=before['rDotRecv'],before['rDotTrans'];sigma=before['sigma'];w=D.from_float(1./float(sigma))
                change=(after['receiver_clock_seconds']-before['receiver_clock_seconds'])*D(299792458)
                native=D.from_float(1.+float(rt)-float(rr))
                factor=change*w*(b[key]+t[key])/2
                clock_effects['fixed_receiver_exact_minus_native']+=(1/(1-rt)-native)*factor
                clock_effects['moving_receiver_exact_minus_native']+=((1-rr)/(1-rt)-native)*factor
                if alpha==1:
                    clock_cache.append({'key':list(key[1:]),'baseline_residual':str(b[key]),'trial_residual':str(t[key]),'before':{n:str(v) for n,v in before.items()},'after':{n:str(v) for n,v in after.items()}})
        trial_results.append({'alpha':str(alpha),'actual_reduction':str(actual),'requested_prediction':str(prediction),'actual_minus_prediction':str(actual-prediction),'observation_rows':len(bobs),'constraint_rows':len(bl['constraint_rhs']),'top_rows_cross_checked':top,'candidate_clock_coefficient_effect_times_actual_mean_residual':{k:str(v) for k,v in clock_effects.items()}})
    return {'original_objective_rows':len(b),'observation_rows':len(bobs),'constraint_rows':len(bl['constraint_rhs']),'global_parameters':len(x),'clock_operand_rows':len(bl.get('clock_operands',{})),'clock_row_cache':clock_cache,'checks_minus_reported':checks,'independent_prediction_combinations':{k:str(v) for k,v in combos.items()},'trials':trial_results}

def main():
    p=argparse.ArgumentParser();p.add_argument('--analysis',type=Path,required=True);p.add_argument('--analysis-sha256',required=True);a=p.parse_args()
    try:
        require(digest(a.analysis)==a.analysis_sha256,'Analysis identity changed');analysis=json.loads(a.analysis.read_text());require(analysis['status']=='completed' and analysis['scientific_validation_complete'] is False,'Analysis is not completed diagnostic evidence')
        factor=Path(analysis['artifacts']['factor']['path']);require(digest(factor)==analysis['artifacts']['factor']['sha256'],'Factor changed');stem=str(factor).removesuffix('.factor.json')
        top_rows={(0,*i['key']) for t in analysis['trials'] for i in t['largest_disagreement_rows'] if i['key'][0]!='constraint'}
        with localcontext() as ctx:
            ctx.prec=128
            ledgers,parts,traces=read_rows(analysis['artifacts']['traces'],stem,top_rows);result=compare(ledgers,parts,analysis)
        require(digest(a.analysis)==a.analysis_sha256,'Analysis changed during independent scan')
        result.update(schema='orbit-poc-d03-independent-row-accounting-v1',status='passed',analysis={'path':str(a.analysis),'sha256':a.analysis_sha256},trace_inventory=traces,precision=128,scientific_validation_complete=False,covariance_authorized=False,scope='Independent retained-row, joint-design and selected component arithmetic only. No new native fit or scientific acceptance. Decimal comparison tolerance1e-90 is diagnostic arithmetic agreement, not an estimator threshold.')
    except Exception as error:result={'schema':'orbit-poc-d03-independent-row-accounting-v1','status':'failed_closed','error':repr(error),'scientific_validation_complete':False,'covariance_authorized':False}
    print(json.dumps(result,indent=2,sort_keys=True));return 0 if result['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
