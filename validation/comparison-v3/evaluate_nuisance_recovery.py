"""Read-only physical nuisance diagnostics, with one global IF datum only."""
from pathlib import Path
import argparse,json
import numpy as np
from orbit_poc.comparison.data import sha256_file,write_json
from orbit_poc.comparison.synthetic import read_receiver_ascii
C=299792458.;F1=1575.42e6;F2=1227.60e6;ALPHA=F1**2/(F1**2-F2**2)

def find_export(value):
    if isinstance(value,dict):
        if isinstance(value.get('slips'),list):return value
        for child in value.values():
            answer=find_export(child)
            if answer is not None:return answer
    return None

def assess(fit_output,generation,manifest,mask=None):
    fit_output,generation,manifest=map(Path,(fit_output,generation,manifest))
    truth=[]
    for line in (generation/'ambiguity_truth.txt').read_text().splitlines():
        if line.startswith('#') or not line.strip():continue
        prn,typ,start,end,value=line.split();truth.append((int(prn),typ,float(start),float(end),float(value)))
    metadata=json.loads(manifest.read_text());export=find_export(metadata);slips={x['prn']:x for x in export['slips']}
    mask=metadata.get('case',{}).get('mask',{}) if mask is None else mask;mask_intervals=mask.get('intervals_seconds',[])
    if mask.get('time_scale','elapsed')!='elapsed':raise ValueError('Nuisance fixture mask must use elapsed seconds')
    clock_truth=np.loadtxt(generation/'simulated_clock.txt',skiprows=6,ndmin=2)
    epoch=float(np.floor(clock_truth[0,0]));clock=np.loadtxt(fit_output/'receiver_clock.txt',skiprows=6,ndmin=2)
    times={round(t*86400,4):v for t,v in clock_truth};clock_errors=[]
    for t,v in clock:
        if round(t*86400,4) not in times:raise ValueError('Clock epochs do not match injected truth')
        clock_errors.append((v-times[round(t*86400,4)])*C)
    ce=np.array(clock_errors);cg=float(ce.mean())
    records=[];missing=[]
    for line in (fit_output/'phase_recovery.txt').read_text().splitlines():
        if line.startswith('#') or not line.strip():continue
        f=line.split();mjd=float(f[0]);prn=int(f[1]);typ=f[2];v=list(map(float,f[3:]));elapsed=(mjd-epoch)*86400
        targets=[r for r in truth if r[0]==prn and r[1]==typ and r[2]-1e-9<=mjd<=r[3]+1e-9]
        if len(targets)!=1:missing.append([mjd,prn,typ]);continue
        target=targets[0][-1];slip=slips.get(prn)
        if slip and elapsed>=slip['elapsed_seconds']:
            target+=C/(F1 if typ[1]=='1' else F2)*slip['cycles_l'+typ[1]]
        effective=v[0]-v[1]-v[2]+v[3]+v[4]
        records.append({'t':round(elapsed,4),'prn':prn,'type':typ[:3],'estimate':effective,'truth':target,
            'error':effective-target,'track_start':(v[-2]-epoch)*86400,'track_end':(v[-1]-epoch)*86400})
    retained_epochs={round((epoch+r['t']/86400)*86400,4) for r in records}
    ce=np.array([(v-times[round(t*86400,4)])*C for t,v in clock if round(t*86400,4) in retained_epochs])
    cg=float(ce.mean())
    groups={}
    for row in records:groups.setdefault((row['t'],row['prn']),{})[row['type']]=row
    pairs=[]
    for (t,p),r in groups.items():
        if 'L1W' in r and 'L2W' in r:
            pairs.append({'t':t,'prn':p,'error':ALPHA*r['L1W']['error']+(1-ALPHA)*r['L2W']['error'],
                          'estimate':ALPHA*r['L1W']['estimate']+(1-ALPHA)*r['L2W']['estimate'],
                          'truth':ALPHA*r['L1W']['truth']+(1-ALPHA)*r['L2W']['truth']})
    errors=np.array([r['error'] for r in pairs]);gauge=float(errors.mean())
    raw={}
    for e in read_receiver_ascii(generation/'receiver_unmasked.txt'):
        for satellite in e['satellites']:raw.setdefault(int(satellite[-2:]),[]).append(float((e['mjd']-epoch)*86400))
    events=[]
    for prn,slip in sorted(slips.items()):
        t=slip['elapsed_seconds'];before=[r for r in pairs if r['prn']==prn and r['t']<t];after=[r for r in pairs if r['prn']==prn and r['t']>=t]
        rawbefore=[x for x in raw.get(prn,[]) if x<t];rawafter=[x for x in raw.get(prn,[]) if x>=t]
        rawvisible=bool(rawbefore and rawafter and min(rawafter)-max(rawbefore)<=30.001)
        bracket_times=[max(rawbefore),min(rawafter)] if rawvisible else []
        bracket_masked=any(a<=q<b for q in bracket_times for a,b in mask_intervals)
        crossing=any(r['prn']==prn and r['track_start']<t<r['track_end'] for r in records)
        event={'prn':prn,'injected_seconds':t,'raw_two_sided_30s_visibility':rawvisible,'retained_track_crosses_slip':crossing,
            'status':'not_two_sided_after_mask_or_preprocessing','estimated_jump_error_m':None,
            'unavailable_reason':'not visible on both sides of injection' if not rawvisible else 'at least one bracketing observation excluded by fixed mask' if bracket_masked else 'native preprocessing removed at least one nearby segment',
            'retained_IF_epochs_before':len(before),'retained_IF_epochs_after':len(after)}
        if before and after and min(r['t'] for r in after)-max(r['t'] for r in before)<=30.001:
            a=max(before,key=lambda r:r['t']);b=min(after,key=lambda r:r['t'])
            event.update(status='segmented' if not crossing else 'crossing_track_requires_repair_check',
                last_retained_before_seconds=a['t'],first_retained_after_seconds=b['t'],unavailable_reason=None,
                estimated_jump_error_m=(b['estimate']-a['estimate'])-(b['truth']-a['truth']))
        events.append(event)
    return {'clock':{'epochs':len(ce),'total_clock_file_epochs':len(clock),'selection':'epochs with retained fitted carrier phases; gap clocks are unobserved','global_gauge_offset_m':cg,'raw_rms_m':float(np.sqrt(np.mean(ce**2))),
                'gauge_aligned_rms_m':float(np.std(ce)),'gauge_aligned_max_abs_m':float(np.max(abs(ce-cg)))},
            'phase':{'rows':len(records),'missing_truth_matches':missing,'IF_pairs':len(errors),'raw_error_mean_m':gauge,'applied_global_clock_datum_m':cg,
                'gauge_aligned_rms_m':float(np.sqrt(np.mean((errors+cg)**2))),'gauge_aligned_max_abs_m':float(np.max(abs(errors+cg))),
                'raw_rms_m':float(np.sqrt(np.mean(errors**2)))},
            'slips':events,'physical_formula':'effective ambiguity = input_phase - processed_phase - removed_windup + fitted_track_ambiguity + fitted_receiver_signal_bias; IF = alpha*L1W + (1-alpha)*L2W',
            'gauge':'one joint receiver-clock datum: subtract mean clock error from clock and add the same value to IF ambiguity; no independent phase, per-track, per-satellite, trend or epoch-specific truth alignment',
            'uncertainty_claim':False,'source_sha256':{str(p.name):sha256_file(p) for p in [manifest,generation/'ambiguity_truth.txt',generation/'simulated_clock.txt',fit_output/'receiver_clock.txt',fit_output/'phase_recovery.txt']}}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fit-output',type=Path,required=True);p.add_argument('--generation',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--case-request',type=Path);args=p.parse_args()
    mask=json.loads(args.case_request.read_text())['case']['mask'] if args.case_request else None
    result=assess(args.fit_output,args.generation,args.manifest,mask=mask);write_json(args.output,result);print(json.dumps(result,indent=2))
