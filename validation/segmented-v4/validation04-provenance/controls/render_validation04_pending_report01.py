"""Render the unchanged frozen API's local pending matrix; no gate outcome claim."""
from pathlib import Path
import hashlib,json,sys
C=Path('/mnt/d/orbit-segmented-v4/control')
project=Path('/mnt/d/orbit-segmented-v4/source')
launch=Path('/mnt/d/orbit-segmented-v4/publication-validation04-launch-01')
config_path=launch/'controls/segmented-v4.json'
freeze_path=launch/'controls/source-freeze.json'
out=Path('/mnt/d/orbit-segmented-v4/report-interface-before-prepare-04')
receipt_path=C/'validation04-report-before-prepare-interface-01.json'
assert not out.exists() and not receipt_path.exists()
def pin(p):
    b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
assert pin(config_path)['sha256']=='e23eb3a1b4eafc6c1c279183292513b87e64a366061ac6ef645987700c193fac'
assert pin(freeze_path)['sha256']=='87ad55dcd0c4329cb4e37a37adfe3871cb85d3fb88e8a46b3cff388aa17e9f29'
sys.path.insert(0,str(project/'src'))
from orbit_poc.segmented.config import load_config
from orbit_poc.segmented.report import create_report
from orbit_poc.comparison.protocol import source_snapshot
freeze=json.loads(freeze_path.read_text()); source=source_snapshot(project)
assert source==freeze['comparison_source']
config=load_config(config_path); result=create_report(config,output_dir=out,project=project)
report=json.loads((out/'report.json').read_text())
assert result['terminal_attempts']==0 and report['expected_attempts']==68 and not report['release_ready']
assert report['manifest_hash'] is None and len(report['attempts'])==68 and all(x['status']=='not_run' for x in report['attempts'])
assert source_snapshot(project)==source
receipt={'schema':'orbit-poc-v4-report-before-prepare-interface-check-v1','status':'demonstrated_with_actual_frozen_config_and_source','config':pin(config_path),'source_freeze':pin(freeze_path),'source_sha256':source['sha256'],'output':result,'report_sha256':pin(out/'report.json')['sha256'],'plan_hash':report['plan_hash'],'attempts':68,'terminal_attempts':0,'gate_presentation_limitation':'Both sections are pending_or_failed without the prepared manifest; completed validation context is not read by this path.','runtime_or_native_executed':False,'frozen_source_or_configuration_modified':False,'scope':'API behavior and exact pending matrix only. This local report does not assert a terminal validation outcome.','helper':pin(Path(__file__))}
with receipt_path.open('x') as stream:json.dump(receipt,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({'receipt':pin(receipt_path),'report':pin(out/'report.json'),'html':pin(out/'index.html'),'plan':pin(out/'plan.json')}))
