"""Local decoder-only recheck; never relabel the failed original native attempt."""
import json
from pathlib import Path
import gates
from orbit_poc.comparison.backend import read_native_table

C=Path('/mnt/d/orbit-segmented-v4/control')
R=C/'wide-flight-pair01-terminal01'
T=C/'wide-flight-native-time-readback01'
A=Path('/mnt/d/orbit-segmented-v4/validation-07-results/terminal-01/terminal-capture-01')
for path,sha in ((R/'manifest.json','e4fa1a31914c325d7cd98cfd6f0c3833dfd537a4b91f1d92d018c5ba34920c8e'),(T/'manifest.json','38b656b3b24665f9ea90f346265c3b3c84899b774c1be76d85a0f0247f151819')):
    gates.verify({'path':str(path),'sha256':sha})
    for rec in json.loads(path.read_text())['records']:
        gates.verify({'path':str(path.parent/rec['relative']),'sha256':rec['sha256']})
x=json.loads((R/'control/request.json').read_text())
original=A/'run/validation/attempt-0001/flight-refinement/result/result.json'
gates.verify({'path':str(original),'sha256':x['historical_result']['sha256']})
ref=T/'retained/coarse/closure-03/orbit.dat'
gates.verify({'path':str(ref),'sha256':x['reference_orbit']['sha256']})
decoder_path=Path('/mnt/d/orbit-segmented-v4/validation-07-packet/source/src/orbit_poc/segmented/tangent_export.py')
decoder=gates.load_decoder({'path':str(decoder_path),'sha256':x['decoder']['sha256']})
e=R/'run/pair/export';b=R/'run/pair/no-export'
result=gates.check_flight(gates.jsonl(e/'local-tangent.jsonl'),read_native_table(e/'physical-stm.txt',43),
 read_native_table(b/'orbit.txt',10),read_native_table(e/'orbit.txt',10),json.loads((e/'derivatives.json').read_text()),
 json.loads(original.read_text()),decoder,gates.retained_orbit_times(ref.read_bytes()))
result.update(schema='orbit-poc-preserved-flight-output-decoder-recheck-v1',original_failed_attempt_preserved=True,
 original_capture={'path':str(R/'manifest.json'),'sha256':gates.digest(R/'manifest.json')},
 input_time_readback={'path':str(T/'manifest.json'),'sha256':gates.digest(T/'manifest.json')},
 guard_sha256=gates.digest(gates.__file__),native_executions=0,
 scope='Decoder-only recheck of exact preserved native outputs; original attempt01 remains failed_diagnostic. Independent packet and outcome audit still required.')
gates.write_fresh(C/'wide-flight-preserved-independent03-result01.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ['rounding','effective_anchored_offgrid_drag_indices']},indent=2))
