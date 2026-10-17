"""Render the frozen report API's pending68 matrix without running a gate."""
from pathlib import Path
import base64,hashlib,json,sys
C=Path('/mnt/d/orbit-segmented-v4/control');R=C.parent
project=R/'validation-05-packet/source'
inputs=R/'validation05-report-inputs01'
out=R/'report-interface-before-prepare-05'
receipt_path=C/'validation05-report-before-prepare-interface-01.json'
assert not inputs.exists() and not out.exists() and not receipt_path.exists()
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
readback=json.loads((C/'preparation04-cache-inputs01-readback.json').read_text())
expected={'config':'d7d66e175353213889ce32d8606a572d219bc2138ad58f1041558e49b014486b','source_freeze':'87b220cf9a66737e72ed2037c3a80895eb445bf3058918fad32d38e79df8078c'}
inputs.mkdir()
for key,name in [('config','segmented-v4.json'),('source_freeze','source-freeze.json')]:
 a=readback['artifacts'][key];raw=base64.b64decode(a['raw_base64'],validate=True)
 assert hashlib.sha256(raw).hexdigest()==a['sha256']==expected[key]
 assert len(raw)==a['bytes'] and json.loads(raw)==a['value']
 with (inputs/name).open('xb') as f:f.write(raw)
config_path=inputs/'segmented-v4.json';freeze_path=inputs/'source-freeze.json'
sys.path.insert(0,str(project/'src'))
from orbit_poc.segmented.config import load_config
from orbit_poc.segmented.report import create_report
from orbit_poc.comparison.protocol import source_snapshot
freeze=json.loads(freeze_path.read_text());source=source_snapshot(project)
assert source==freeze['comparison_source']
assert source['sha256']=='c267e581d7839a39fa09cde4d6211e8b1139e6f65b0b146f5167647dea958718'
assert freeze['source']['sha256']=='87a3a10ab538d606837e1ebcfa579c1b5cc6bfe57f2b3220b47bfe340cab1130'
config=load_config(config_path);result=create_report(config,output_dir=out,project=project)
report=json.loads((out/'report.json').read_text())
assert result['terminal_attempts']==0 and report['expected_attempts']==68 and not report['release_ready']
assert report['manifest_hash'] is None and len(report['attempts'])==68 and all(x['status']=='not_run' for x in report['attempts'])
assert source_snapshot(project)==source
receipt={'schema':'orbit-poc-v4-report-before-prepare-interface-check-v1','status':'demonstrated_with_actual_frozen_config_and_source','config':pin(config_path),'source_freeze':pin(freeze_path),'source_sha256':source['sha256'],'output':result,'report_sha256':pin(out/'report.json')['sha256'],'plan_hash':report['plan_hash'],'attempts':68,'terminal_attempts':0,'gate_presentation_limitation':'Both sections are pending_or_failed without the prepared manifest; completed validation context is not read by this path.','runtime_or_native_executed':False,'frozen_source_or_configuration_modified':False,'scope':'API behavior and exact pending matrix only. This local report does not assert any terminal validation outcome.','helper':pin(Path(__file__)),'input_readback':pin(C/'preparation04-cache-inputs01-readback.json')}
with receipt_path.open('x') as f:json.dump(receipt,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps({'receipt':pin(receipt_path),'report':pin(out/'report.json'),'html':pin(out/'index.html'),'plan':pin(out/'plan.json')}))
