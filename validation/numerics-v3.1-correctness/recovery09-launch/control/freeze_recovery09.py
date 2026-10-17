"""Root-only09 control freeze/admission; no native launch or scientific result."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import os
import sys

OLD=Path('@EXECUTION_08_ROOT@')
NEW=Path('@EXECUTION_09_ROOT@')
PREVIOUS_PINS_SHA256='91b84d5a702c0b782f80cbebf68d2576c54797f809e9247eceaf4caeceee57d5'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path):return {'path':str(path),'sha256':sha(path)}
def require(condition,message):
    if not condition:raise RuntimeError(message)
def save(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
def load_driver(path):
    spec=importlib.util.spec_from_file_location('reviewed09_freeze',path)
    driver=importlib.util.module_from_spec(spec);sys.modules[spec.name]=driver;spec.loader.exec_module(driver);return driver

def freeze(old=OLD,new=NEW):
    old,new=Path(old),Path(new);control=new/'control';previous=old/'control/candidate07-pins.json'
    require(sha(previous)==PREVIOUS_PINS_SHA256,'Previous08 control pins changed')
    previous_pins=json.loads(previous.read_bytes());pins=dict(previous_pins)
    ep=control/'candidate09-execution.json';execution=json.loads(ep.read_bytes())
    freeze_path=control/'candidate09-source-freeze.json';frozen=json.loads(freeze_path.read_bytes())
    lineage_path=control/'candidate09-correction-lineage.json';lineage=json.loads(lineage_path.read_bytes())
    require(lineage.get('schema')=='orbit-poc-correctness-correction-lineage-v3','Reviewed incremental09 lineage is required')
    require(lineage.get('original_source_freeze')==previous_pins['source_freeze']
            and lineage.get('new_source_freeze')==pin(freeze_path)
            and lineage.get('previous_source_freeze',{}).get('sha256')==previous_pins['new_source_freeze']['sha256'],
            'Lineage does not retain original03 and exact previous07 source freezes')
    require(lineage.get('previous_correction_lineage')==previous_pins['correction_lineage'],
            'New lineage must preserve the executed08 correction lineage')
    pp=control/'candidate09-pins.json'
    require(not pp.exists() and not pp.is_symlink() and not (control/'recovery09-freeze.json').exists(),
            'Freeze cannot overwrite existing09 pins or receipt')
    pins.update(schema='orbit-poc-correctness-candidate09-pins-v1',source_sha256=frozen['source']['sha256'],
        source_file_count=len(frozen['source']['files']),driver_sha256=sha(control/'validate_candidate_09.py'),
        wrapper_sha256=sha(control/'with_correctness_namespace_09.py'),execution_sha256=sha(ep),
        previous_source_freeze=lineage['previous_source_freeze'],new_source_freeze=pin(freeze_path),
        previous_correction_lineage=lineage['previous_correction_lineage'],
        correction_lineage=pin(lineage_path),allowed_correction_paths=sorted(lineage['changes']),
        regression_suite=frozen['regression_suite'],recovery_verifier_sha256=sha(control/'recovery_evidence_09.py'))
    require(pins['input_artifacts']==previous_pins['input_artifacts'] and len(pins['input_artifacts'])==14,
            'Exactly14 original scientific inputs must remain unchanged')
    save(pp,pins)
    result={'schema':'orbit-poc-recovery09-freeze-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'execution':pin(ep),'pins':pin(pp),'previous08_pins':pin(previous),'correctness_resolved':False,'native_launched':False}
    try:
        driver=load_driver(control/'validate_candidate_09.py')
        config=driver.load_execution(ep);checked=driver.load_required_pins(pp,ep)
        source=driver.verify_pins(checked,config,ep);admitted=driver.admission(config)
        require(all(not Path(execution['paths'][key]).exists() and not Path(execution['paths'][key]).is_symlink()
                    for key in driver.MUTABLE_KEYS),'Fresh09 native output directories must remain absent')
        result.update(status='passed',source_sha256=source['sha256'],source_files=len(source['files']),
                      scientific_inputs_unchanged=True,admission=admitted)
    except BaseException as error:
        result.update(status='failed',error=type(error).__name__+': '+str(error))
        save(control/'recovery09-freeze-failed.json',result);raise
    save(control/'recovery09-freeze.json',result)
    return result

if __name__=='__main__':print(json.dumps(freeze()))
