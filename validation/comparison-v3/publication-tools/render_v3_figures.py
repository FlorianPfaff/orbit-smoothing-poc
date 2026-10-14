#!/usr/bin/env python3
"""Fixed postprocessing figures for completed compact v3 reports (Python 3.11+).

Uses existing paired-seed statistics and Wilson intervals, never raw trajectories.
The deliberately fictional QA mode is separate and visibly watermarked.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

PRIMARY='leo500/disturbed/blackout'
DENSITY='groops_log_drag_ou'
PULSES='groops_pulses'
METHODS=(DENSITY,PULSES)
LABELS={DENSITY:'Log-density OU',PULSES:'Reduced-dynamic pulses'}
COLORS={DENSITY:'#bf5b17',PULSES:'#24679c'}
ORBITS=('leo300','leo500','leo800','eccentric')
ORBIT_LABELS={'leo300':'300 km','leo500':'500 km','leo800':'800 km','eccentric':'Eccentric orbit'}
SCENARIOS=(('quiet','normal'),('quiet','blackout'),('disturbed','normal'),('disturbed','blackout'))
PLANNED=('primary-paired-rmse','primary-fixed-epoch-coverage','secondary-whole-arc-rmse')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def load_json(path):
    path=Path(path)
    if not path.exists() and Path(str(path)+'.gz').is_file():path=Path(str(path)+'.gz')
    payload=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    return json.loads(payload),{'path':str(path),'sha256':sha(path),
        'uncompressed_payload_sha256':hashlib.sha256(payload).hexdigest()}


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def oriented(row):
    """Always density minus pulses; a fixed display convention, not an outcome choice."""
    order=(row['method_a'],row['method_b'])
    if set(order)!=set(METHODS):raise ValueError('Expected exactly the two primary comparison methods')
    if row.get('bootstrap_unit')!='paired independent seed':
        raise ValueError('Paired intervals must use independent seeds, not trajectory epochs')
    mean=row.get('mean_difference_a_minus_b');interval=row.get('bootstrap_95_interval')
    if mean is not None and not finite(mean):raise ValueError('Nonfinite paired mean')
    if interval is not None and (len(interval)!=2 or not all(finite(x) for x in interval) or interval[0]>interval[1]):
        raise ValueError('Invalid paired interval')
    if mean is None and interval is not None:raise ValueError('A paired interval cannot exist without a mean')
    valid,planned,missing=(row[key] for key in ('valid_seed_pairs','planned_seed_pairs','failed_or_missing_seed_pairs'))
    if not all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in (valid,planned,missing)) or valid+missing!=planned:
        raise ValueError('Invalid or concealed seed-pair denominator')
    if planned!=50:raise ValueError('The predeclared primary/secondary comparison requires 50 planned seed pairs')
    if valid==0 and (mean is not None or interval is not None):raise ValueError('No valid pairs can supply a mean or CI')
    if order==(PULSES,DENSITY):
        mean=-mean if mean is not None else None
        interval=[-interval[1],-interval[0]] if interval is not None else None
    return {'mean':mean,'interval':interval,'valid':valid,'planned':planned,'missing':missing,
            'source_method_a':order[0],'source_method_b':order[1]}


def comparison(rows,cell,metric):
    selected=[row for row in rows if row.get('cell_id')==cell and row.get('metric')==metric]
    if len(selected)!=1 or not selected[0].get('applicable'):
        raise ValueError(f'Exactly one applicable frozen comparison is required: {cell}/{metric}')
    return oriented(selected[0])


def coverage_row(rows,method,hour):
    selected=[row for row in rows if row.get('cell_id')==PRIMARY and row.get('method_id')==method
              and row.get('hours_since_start')==hour]
    if len(selected)!=1:raise ValueError(f'Missing/duplicate fixed-epoch coverage: {method}/{hour}')
    row=selected[0]
    trials,planned,missing=(row[key] for key in ('trials','planned_seeds','failed_or_unavailable_seeds'))
    counts=(trials,planned,missing,row['successes'])
    if (not all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in counts)
            or planned!=50 or trials+missing!=planned or not 0<=row['successes']<=trials):
        raise ValueError('Coverage must retain the 50-seed denominator')
    interval=row.get('interval');estimate=row.get('estimate')
    if trials==0:
        if estimate is not None or interval is not None:raise ValueError('Empty coverage cannot have an estimate/interval')
    elif (not finite(estimate) or interval is None or len(interval)!=2
          or not all(finite(x) for x in interval) or not 0<=interval[0]<=estimate<=interval[1]<=1):
        raise ValueError('Invalid Wilson interval')
    elif row.get('confidence')!=.95 or not math.isclose(estimate,row['successes']/trials,rel_tol=1e-12,abs_tol=1e-12):
        raise ValueError('Coverage estimate or confidence level disagrees with reported counts')
    return row


def plot_interval(ax,y,row,color='#24679c'):
    """Draw unavailable estimates as text; never replace a missing value with zero."""
    if row['mean'] is None:
        ax.text(.5,y,'Mean and CI unavailable',transform=ax.get_yaxis_transform(),
            ha='center',va='center',fontsize=9,color='#555555')
    else:
        # Percentile intervals need not enclose their estimated mean. Draw their
        # endpoints directly instead of requiring nonnegative error-bar distances.
        if row['interval'] is not None:
            lo,hi=row['interval'];ax.plot([lo,hi],[y,y],color=color,lw=2)
            ax.plot([lo,lo],[y-.07,y+.07],color=color,lw=1.4)
            ax.plot([hi,hi],[y-.07,y+.07],color=color,lw=1.4)
        ax.plot(row['mean'],y,'o',ms=6,color=color)
        if row['interval'] is None:
            ax.annotate('CI unavailable',(row['mean'],y),xytext=(7,7),textcoords='offset points',
                fontsize=8,color='#555555')


def style_axis(ax,plt):
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='x',alpha=.20)
    ax.axvline(0,color='#555555',lw=1,ls='--',zorder=0)
    ax.set_xlabel('Density − pulses RMSE (m)')
    ax.ticklabel_format(axis='x',style='sci',scilimits=(-3,4),useOffset=False)


def watermark(fig,fixture):
    if fixture:
        fig.text(.5,.98,'FICTIONAL QA — NO EXPERIMENTAL RESULTS',ha='center',va='top',
            color='#a32020',fontsize=13,weight='bold')
        fig.text(.52,.5,'FICTIONAL FIXTURE',ha='center',va='center',rotation=28,
            color='#a32020',alpha=.13,fontsize=38,weight='bold')


def save_figure(fig,output,name,fixture,plt):
    name=('fixture-' if fixture else '')+name
    records=[]
    for extension in ('png','svg'):
        path=output/(name+'.'+extension)
        if path.exists():raise ValueError(f'Refusing to overwrite figure: {path}')
        fig.savefig(path,dpi=240,facecolor='white',bbox_inches='tight',
            metadata={'Description':'Explicitly fictional QA data' if fixture else 'Fixed predeclared v3 statistical display; no raw orbit data'})
        records.append({'path':path.name,'sha256':sha(path),'bytes':path.stat().st_size})
    plt.close(fig)
    return records


def render_data(summary,report,output,*,fixture=False,input_records=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':12,
        'axes.labelsize':10,'svg.fonttype':'none','svg.hashsalt':'orbit-comparison-v3-fixed-figures'})
    figures=[]
    primary=[comparison(report['paired_metrics'],PRIMARY,metric) for metric in
        ('whole_arc.position_rmse_m','gap.position_rmse_m')]
    fig,ax=plt.subplots(figsize=(10,4.4))
    fig.subplots_adjust(left=.31,right=.95,top=.77 if fixture else .84,bottom=.30)
    for y,row in zip((1,0),primary):plot_interval(ax,y,row)
    ax.set_yticks([1,0],labels=[f'{label}\n{r["valid"]}/{r["planned"]} valid pairs; {r["missing"]} missing/failed'
        for label,r in zip(('Whole 24-hour arc','11–13 h blackout'),primary)])
    ax.set_ylim(-.6,1.6);style_axis(ax,plt)
    if all(row['mean'] is None for row in primary):ax.set_xticks([])
    fig.suptitle('Primary scenario: 500 km · disturbed atmosphere · two-hour blackout',y=.88 if fixture else .97,fontsize=13)
    fig.text(.5,.065,'Mean paired RMSE difference and 95% paired-seed bootstrap interval.\n'
        'Negative favors density; positive favors pulses. Missing pairs remain in the denominator labels.',ha='center',fontsize=9)
    watermark(fig,fixture);figures+=save_figure(fig,output,PLANNED[0],fixture,plt)

    fig,axes=plt.subplots(1,2,figsize=(10.5,5.8),sharey=True)
    fig.subplots_adjust(left=.09,right=.97,bottom=.31,top=.77 if fixture else .83,wspace=.22)
    for ax,method in zip(axes,METHODS):
        ax.set_title(LABELS[method],color=COLORS[method])
        ax.axhline(.95,color='#555555',ls='--',lw=1,label='Nominal 95%')
        ax.set_ylim(-.015,1.06);ax.set_xlim(10.6,13.4);ax.set_xticks([11,12,13],labels=['Entry\n11 h','Midpoint\n12 h','Exit\n13 h'])
        ax.set_yticks([0,.25,.5,.75,.95,1],labels=['0%','25%','50%','75%','95%','100%'])
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.15)
        for hour in (11,12,13):
            row=coverage_row(report['fixed_epoch_coverage'],method,hour)
            if row['estimate'] is not None:
                estimate=row['estimate'];lo,hi=row['interval']
                ax.errorbar(hour,estimate,yerr=[[estimate-lo],[hi-estimate]],fmt='o',
                    color=COLORS[method],capsize=4,ms=6)
            else:
                ax.text(hour,.48,'Unavailable',ha='center',va='center',fontsize=9,color='#555555',rotation=90)
            ax.text(hour,-.18,f'{row["successes"]}/{row["trials"]} covered\n{row["failed_or_unavailable_seeds"]} unavailable\n50 planned',
                transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=8)
    axes[0].set_ylabel('95% position ellipsoid coverage')
    fig.suptitle('Primary scenario: fixed-epoch uncertainty coverage',y=.88 if fixture else .97,fontsize=13)
    fig.text(.5,.065,'Points: coverage across independent seeds at each fixed epoch. Bars: Wilson 95% intervals.\n'
        'The three epochs are correlated within each seed; their intervals are separate diagnostics.\n'
        'Formal covariance is conditional on selected hyperparameters and fixed measurement weights.',ha='center',fontsize=9)
    watermark(fig,fixture);figures+=save_figure(fig,output,PLANNED[1],fixture,plt)

    # A fixed four-panel layout displays all 15 secondary cells, regardless of
    # outcome. Each orbit uses a labeled independent x scale for legibility.
    fig,axes=plt.subplots(2,2,figsize=(13,8.2))
    fig.subplots_adjust(left=.19,right=.96,bottom=.16,top=.80 if fixture else .88,hspace=.58,wspace=.74)
    for ax,orbit in zip(axes.ravel(),ORBITS):
        rows=[];labels=[]
        for atmo,coverage in SCENARIOS:
            cell='/'.join((orbit,atmo,coverage))
            rows.append(None if cell==PRIMARY else comparison(report['paired_metrics'],cell,'whole_arc.position_rmse_m'))
            labels.append(atmo.title()+' / '+('tracking' if coverage=='normal' else 'blackout'))
        for y,row in zip(range(3,-1,-1),rows):
            if row is None:
                ax.text(.5,y,'Primary scenario: see separate figure',transform=ax.get_yaxis_transform(),
                    ha='center',va='center',fontsize=8,color='#555555')
            else:plot_interval(ax,y,row)
        ax.set_yticks([3,2,1,0],labels=[label+(f'\n{row["valid"]}/50 valid; {row["missing"]} missing' if row else '')
            for label,row in zip(labels,rows)])
        ax.tick_params(axis='y',labelsize=8);ax.set_ylim(-.65,3.65);style_axis(ax,plt)
        ax.set_title(ORBIT_LABELS[orbit])
        if all(row is None or row['mean'] is None for row in rows):ax.set_xticks([])
    fig.suptitle('Secondary scenarios: whole-arc paired RMSE differences',y=.9 if fixture else .97,fontsize=14)
    fig.text(.5,.055,'Mean density − pulses difference with 95% paired-seed bootstrap interval. Panels use separate x scales.\n'
        'All 15 secondary cells are displayed in the frozen order; no metric or cell is selected by its outcome.\n'
        'Each label retains the 50 planned seed pairs. Unavailable means or intervals are not replaced with zero.',ha='center',fontsize=9)
    watermark(fig,fixture);figures+=save_figure(fig,output,PLANNED[2],fixture,plt)
    manifest={'schema_version':1,'fictional_fixture':fixture,'planned_figures':list(PLANNED),
        'renderer_sha256':sha(__file__),'matplotlib_version':matplotlib.__version__,'numpy_version':np.__version__,
        'source_hash':summary.get('source_hash'),'protocol_hash':summary.get('protocol_hash'),
        'inputs':input_records or [],'figures':figures,'statistics_recomputed':False,
        'comparison_orientation':'density minus pulses; if original A/B order is reversed, negate the mean and reverse/negate CI bounds',
        'inference_scope':'Existing paired independent-seed bootstrap CIs and fixed-epoch Wilson intervals; no correlated time samples counted as independent, no automatic significance or superiority claim',
        'created_at_utc':datetime.now(timezone.utc).isoformat()}
    name=('fixture-' if fixture else '')+'figure-manifest.json'
    (output/name).write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest


def render_bundle(bundle):
    bundle=Path(bundle).resolve()
    if (bundle/'publication.json').exists():
        raise ValueError('A published bundle is immutable; render only in the collector staging directory before inventory hashing')
    summary,first=load_json(bundle/'summary.json')
    report,second=load_json(bundle/'report-synthetic/report.json')
    if not summary.get('execution_complete') or not report.get('orchestration_complete') or not report.get('planned_design_complete'):
        raise ValueError('Figures require completed compact report data')
    if report.get('metrics_error') or report.get('source_hash')!=summary.get('source_hash') or report.get('protocol_hash')!=summary.get('protocol_hash'):
        raise ValueError('Figure inputs have inconsistent provenance or invalid metric aggregation')
    if report.get('primary_cell')!=PRIMARY.split('/'):
        raise ValueError('Figure primary cell differs from the predeclared design')
    for item in (first,second):item['path']=str(Path(item['path']).relative_to(bundle))
    return render_data(summary,report,bundle/'figures',input_records=[first,second])


def fixture():
    """Invented constants solely for readable rendering QA, never evidence."""
    paired=[]
    for i,orbit in enumerate(ORBITS):
        for j,(atmo,coverage) in enumerate(SCENARIOS):
            cell='/'.join((orbit,atmo,coverage));value=(-.7+.18*j)*(10**(1-i))
            for metric in ('whole_arc.position_rmse_m','gap.position_rmse_m'):
                paired.append({'cell_id':cell,'metric':metric,'method_a':DENSITY,'method_b':PULSES,
                    'bootstrap_unit':'paired independent seed',
                    'applicable':True,'valid_seed_pairs':45,'planned_seed_pairs':50,'failed_or_missing_seed_pairs':5,
                    'mean_difference_a_minus_b':value*(2 if metric.startswith('gap') else 1),
                    'bootstrap_95_interval':[value-abs(value)*.5-.01,value+abs(value)*.5+.01]})
    # Explicitly exercise unavailable values, which must not appear as zero.
    paired[0].update(valid_seed_pairs=0,failed_or_missing_seed_pairs=50,mean_difference_a_minus_b=None,bootstrap_95_interval=None)
    paired[2].update(valid_seed_pairs=3,failed_or_missing_seed_pairs=47,bootstrap_95_interval=None)
    coverage=[]
    for method,counts in ((DENSITY,[(47,50),(44,48),(46,49)]),(PULSES,[(46,50),(42,47),(0,0)])):
        for hour,(successes,trials) in zip((11,12,13),counts):
            if trials:
                p=successes/trials;z=1.959963984540054;den=1+z*z/trials
                center=(p+z*z/(2*trials))/den;half=z/den*math.sqrt(p*(1-p)/trials+z*z/(4*trials*trials))
                interval=[max(0,center-half),min(1,center+half)]
            else:p=None;interval=None
            coverage.append({'cell_id':PRIMARY,'method_id':method,'hours_since_start':hour,
                'successes':successes,'trials':trials,'planned_seeds':50,'failed_or_unavailable_seeds':50-trials,
                'estimate':p,'interval':interval})
            if trials:coverage[-1]['confidence']=.95
    return {'execution_complete':True,'source_hash':'fictional-qa','protocol_hash':'fictional-qa'}, {
        'paired_metrics':paired,'fixed_epoch_coverage':coverage,'primary_cell':PRIMARY.split('/'),
        'orchestration_complete':True,'planned_design_complete':True,'source_hash':'fictional-qa','protocol_hash':'fictional-qa'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--staging-bundle',type=Path,help='Completed collector staging directory; no publication.json yet')
    mode.add_argument('--fixture',action='store_true',help='Render explicitly fictional QA only')
    parser.add_argument('--output',type=Path,help='Required only for fictional QA')
    args=parser.parse_args()
    if args.fixture:
        if args.output is None:parser.error('--fixture requires --output')
        summary,report=fixture()
        value=render_data(summary,report,args.output,fixture=True)
    else:
        if args.output is not None:parser.error('--output is only for fictional QA; bundle figures stay inside staging')
        value=render_bundle(args.staging_bundle)
    print(json.dumps({'fictional_fixture':value['fictional_fixture'],'figures':len(value['figures'])}))


if __name__=='__main__':main()
