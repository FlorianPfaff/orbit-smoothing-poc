"""Limited native receiver activation check; no converged orbit/evaluation claim."""
from pathlib import Path
from copy import deepcopy
import json, os, shutil, sys, xml.etree.ElementTree as ET

os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[-2:])
project=Path('outputs/orbit-smoothing-poc').resolve()
sys.path.insert(0,str(project/'src'))
from orbit_poc.comparison.groops_config import build_day_configs
from orbit_poc.comparison.backend import run_native
from orbit_poc.comparison.protocol import read_json,write_json,file_hash,source_snapshot

root=Path('/tmp/orbit-v3-utc-receiver-epoch-check').resolve();root.mkdir(exist_ok=True)
binary=root/'groops'
if not binary.exists():shutil.copy2('/tmp/orbit-v3-runtime/groops-build/groops',binary)
source=source_snapshot()['sha256']
report={'scope':'Limited native receiver activation; one estimate iteration, no covariance or converged orbit claims',
        'source_sha256':source,'native_binary_sha256':file_hash(binary),
        'reference_or_slr_evaluation':False,'full_fits_started':False,'records':[]}
raw=read_json('work/v3/prepared-utc/2024-04-24/data_manifest.json')
for label,intervals in [('normal',[]),('blackout',[[39600,46800]])]:
    out=root/label
    config=build_day_configs(raw,'work/v3/native-example/scenarioLeoReducedDynamicOrbit','work/v3/groops-data',out,
        mask={'intervals_seconds':intervals,'cadence_seconds':30,'time_scale':'UTC'})
    # Converted transmitter inputs are immutable and byte-identical across
    # these masks; only new receiver observations/bootstrap are regenerated.
    previous=Path('/tmp/orbit-v3-utc-final')/label/'data/2024-04-24'
    for directory in ('orbit','attitude','clock','signalBias'):
        target=out/'data/2024-04-24'/directory
        if not target.exists():target.symlink_to(previous/directory,target_is_directory=True)
    write_json(out/'configured.json',config)
    executions=[run_native(binary,config['configs']['convert_receiver'],out,'convert_receiver')]
    convert=ET.Element('groops')
    for name in ('receiver','receiver_orbit','receiver_attitude','orbit','attitude'):
        p=ET.SubElement(ET.SubElement(convert,'program'),'FileConvert')
        ET.SubElement(p,'inputfile').text=config['native_paths'][name]
        ET.SubElement(p,'outputfile').text=str(out/f'{name}_ascii.txt')
    ET.ElementTree(convert).write(out/'geometry_ascii.xml',encoding='utf-8',xml_declaration=True)
    executions.append(run_native(binary,out/'geometry_ascii.xml',out,'geometry_ascii'))
    print(label,'exact receiver geometry converted',flush=True)
    executions.append(run_native(binary,config['configs']['variational'],out,'variational'))
    tree=ET.parse(config['configs']['estimate'])
    gnss=tree.find('.//GnssProcessing')
    first=deepcopy(gnss.find('processingStep/estimate'))
    first.find('maxIterationCount').text='1'
    for step in list(gnss.findall('processingStep')):gnss.remove(step)
    ET.SubElement(gnss,'processingStep').append(first)
    # This engineering check deliberately does not compute/export covariance.
    dynamic=gnss.find('parametrization/leoDynamicOrbits')
    for node in list(dynamic):
        if node.tag.startswith('outputfile'):dynamic.remove(node)
    tree.write(out/'one_iteration.xml',encoding='utf-8',xml_declaration=True)
    executions.append(run_native(binary,out/'one_iteration.xml',out,'one_iteration'))
    audit=out/'output/2024-04-24/preprocessing_audit.txt'
    count=sum(1 for line in audit.read_text().splitlines() if line and not line.startswith('#')) if audit.exists() else 0
    record={'mask':label,'native_execution':executions,'audit_rows':count,
            'audit_sha256':file_hash(audit) if audit.exists() else None,
            'native_receiver_remained_enabled':count>0,'status':'completed' if count>0 else 'failed'}
    report['records'].append(record);write_json(root/'receiver_activation.json',report)
    print(label,'one native estimate iteration complete; audit rows',count,flush=True)
report['complete']=True
report['passed']=len(report['records'])==2 and all(row['native_receiver_remained_enabled'] for row in report['records'])
write_json(root/'receiver_activation.json',report)
