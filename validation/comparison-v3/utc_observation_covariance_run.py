"""One-iteration covariance export check, not a converged flight estimate."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json, os, re, sys, time, xml.etree.ElementTree as ET
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
import numpy as np
sys.path.insert(0,str(Path('outputs/orbit-smoothing-poc/src').resolve()))
from orbit_poc.comparison.backend import run_native, read_native_table
from orbit_poc.comparison.protocol import read_json, write_json, file_hash

root=Path('/tmp/orbit-v3-utc-receiver-epoch-check')
binary=root/'groops-final'
assert file_hash(binary)=='74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453'
report={'scope':'One native estimate iteration and covariance export; no converged flight result',
        'native_binary_sha256':file_hash(binary),'force_reference_binary_sha256':file_hash(root/'groops'),
        'reference_or_slr_evaluation':False,'records':[]}
for label in ('normal','blackout'):
    out=root/label
    deadline=time.monotonic()+1800
    while not (out/'one_iteration.execution.json').exists():
        if time.monotonic()>deadline:raise TimeoutError('activation did not complete')
        time.sleep(5)
    assert read_json(out/'one_iteration.execution.json')['returncode']==0
    config=read_json(out/'configured.json')
    audit=Path(config['result_paths']['preprocessing_audit']); audit_before=file_hash(audit)
    tree=ET.parse(config['configs']['estimate']); gnss=tree.find('.//GnssProcessing')
    first=deepcopy(gnss.find('processingStep/estimate'));first.find('maxIterationCount').text='1'
    for step in list(gnss.findall('processingStep')):gnss.remove(step)
    ET.SubElement(gnss,'processingStep').append(first)
    ET.SubElement(ET.SubElement(gnss,'processingStep'),'computeCovarianceMatrix')
    ET.SubElement(ET.SubElement(gnss,'processingStep'),'writeResults')
    dynamic=gnss.find('parametrization/leoDynamicOrbits')
    covariance=out/'output/2024-04-24/state_covariance_observations.txt'
    node=dynamic.find('outputfileCovarianceObservationEpochs')
    if node is None:node=ET.SubElement(dynamic,'outputfileCovarianceObservationEpochs')
    node.text=str(covariance)
    xml=out/'one_iteration_covariance.xml';tree.write(xml,encoding='utf-8',xml_declaration=True)
    execution=run_native(binary,xml,out,'one_iteration_covariance')
    values=read_native_table(covariance,37);blocks=values[:,1:].reshape(-1,6,6)
    nominal_seconds=np.arange(30.,86401.,30.)
    seconds=(values[:,0]-60424.)*86400
    assert len(values)==len(nominal_seconds)==2880
    maximum_epoch_error=float(np.max(np.abs(seconds-nominal_seconds)))
    invalid=[]
    for i,block in enumerate(blocks):
        try:
            sd=np.sqrt(np.diag(block))
            if not np.all(sd>0) or not np.isfinite(sd).all():raise ValueError('nonpositive diagonal')
            if not np.allclose(block,block.T,rtol=1e-9,atol=1e-14):raise ValueError('asymmetric')
            np.linalg.cholesky(block/sd[:,None]/sd[None,:])
        except (ValueError,np.linalg.LinAlgError):invalid.append(i)
    nominal_utc=nominal_seconds-18.
    hidden=(nominal_utc>=39600)&(nominal_utc<46800)
    def epoch_tokens(name):
        return [line.split()[0] for line in (out/f'{name}_ascii.txt').read_text().splitlines()
                if re.match(r'^\s*6042[45]\.\d+',line)]
    times={key:epoch_tokens(key) for key in ('receiver','receiver_orbit','receiver_attitude')}
    geometry_match=times['receiver']==times['receiver_orbit']==times['receiver_attitude']
    record={'mask':label,'receiver_epochs':len(times['receiver']),
        'exact_receiver_orbit_attitude_epoch_tokens_match':geometry_match,
        'covariance_rows':len(values),'nominal_GNSS_epochs_in_UTC_blackout':int(hidden.sum()),
        'covariance_rows_cover_all_withheld_epochs':bool(hidden.sum()==240),
        'maximum_float64_epoch_error_seconds':maximum_epoch_error,
        'invalid_positive_definite_blocks':invalid,
        'audit_sha256':file_hash(audit),'audit_unchanged_from_activation':file_hash(audit)==audit_before,
        'covariance_sha256':file_hash(covariance),'execution':execution}
    record['passed']=geometry_match and not invalid and maximum_epoch_error<.001 and record['audit_unchanged_from_activation']
    report['records'].append(record);write_json(root/'observation_covariance_validation.json',report)
    print(label,record['passed'],len(values),'covariance rows',len(invalid),'invalid blocks',flush=True)
report['complete']=True;report['passed']=all(x['passed'] for x in report['records'])
write_json(root/'observation_covariance_validation.json',report)
