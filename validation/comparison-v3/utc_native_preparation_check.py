from pathlib import Path
from decimal import Decimal
import json,sys,numpy as np
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
from orbit_poc.comparison.data import sha256_file,write_json,_gps1b_text
from orbit_poc.comparison.synthetic import read_receiver_ascii
root=Path('/tmp/orbit-v3-utc-final');records={};epoch_data={}
for label in ['normal','blackout']:
    folder=root/label;manifest=json.loads((folder/'preparation_manifest.json').read_text())
    grids={}
    for name in ['orbit','attitude']:
        rows=[line.split() for line in (folder/f'{name}_ascii.txt').read_text().splitlines() if line.strip() and line.split()[0].startswith(('60424.','60425.'))]
        times=[(Decimal(row[0])-Decimal(60424))*Decimal(86400) for row in rows]
        errors=[abs(t-Decimal(18+5*i)) for i,t in enumerate(times)]
        grids[name]={'epochs':len(times),'first_gps_seconds_after_midnight':float(times[0]),'last_gps_seconds_after_midnight':float(times[-1]),'maximum_exact_grid_error_seconds':float(max(errors))}
    receiver=read_receiver_ascii(folder/'receiver_ascii.txt')
    def seconds(e):return int(np.rint((e['mjd']-np.longdouble(60424))*86400))
    epoch_data[label]={seconds(e):e for e in receiver}
    times=sorted(epoch_data[label]);gap=[t for t in times if 39618<=t<46818]
    records[label]={'native_grids':grids,'receiver_epochs':len(receiver),'first_receiver_utc_seconds':times[0]-18,'last_receiver_utc_seconds':times[-1]-18,
        'epochs_in_utc_blackout_window':len(gap),'last_epoch_before_blackout_utc_seconds':max(t for t in times if t<39618)-18,
        'first_epoch_after_blackout_utc_seconds':min(t for t in times if t>=46818)-18,
        'bootstrap_solved_epochs':manifest['preprocessing']['bootstrap']['solved_epochs'],
        'bootstrap_sha256':manifest['preprocessing']['bootstrap']['sha256'],'preprocessing_hash':manifest['preprocessing_hash'],
        'native_inputs':{name:sha256_file(manifest['native_paths'][name]) for name in ['orbit','attitude','receiver']},
        'preparation_manifest_sha256':sha256_file(folder/'preparation_manifest.json')}
normal,masked=epoch_data['normal'],epoch_data['blackout']
paired=all(t in normal and a['types']==normal[t]['types'] and a['satellites']==normal[t]['satellites'] and np.array_equal(a['observations'],normal[t]['observations']) for t,a in masked.items())
report={'passed':all(g['epochs']==17281 and g['maximum_exact_grid_error_seconds']<1e-9 for r in records.values() for g in r['native_grids'].values()) and paired and records['blackout']['epochs_in_utc_blackout_window']==0 and len(normal)-len(masked)==240,
 'scope':'Input conversion, epoch precision, masking, pairing and GNSS-only initialization; not orbit-fit accuracy or numerical propagation acceptance',
 'date':'2024-04-24','native_binary_sha256':sha256_file(root/'groops'),'records':records,'retained_observations_identical_between_masks':paired,
 'removed_receiver_epochs':len(normal)-len(masked),'bootstrap_recomputed_after_mask':records['normal']['bootstrap_sha256']!=records['blackout']['bootstrap_sha256'],
 'attitudes_identical_between_masks':records['normal']['native_inputs']['attitude']==records['blackout']['native_inputs']['attitude'],
 'epoch_check_method':'Decimal arithmetic on native long-double ASCII exports against exact integer-second UTC-aligned grid; no binary64 MJD subtraction',
 'provider_boundary_epoch_status':'GPS00:00:00 of adjacent day excluded by preserved provider phase-break quality flags; no fabricated or replacement measurements',
 'reference_inputs_used':False,'production_fits_run':False,
 'runtime_source_sha256':{n:sha256_file(Path('outputs/orbit-smoothing-poc/src/orbit_poc/comparison')/n) for n in ['data.py','groops_config.py','slr.py']}}
write_json('outputs/orbit-smoothing-poc/validation/comparison-v3/utc_native_preparation.json',report)
print(json.dumps(report,indent=2))
