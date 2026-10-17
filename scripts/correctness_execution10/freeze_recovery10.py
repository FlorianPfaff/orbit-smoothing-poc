"""Freeze execution10 with unchanged controls09 and verified immediate09 lineage."""
from pathlib import Path
import copy,hashlib,importlib.util,json,sys
OLD=Path('/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff')
NEW=Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def freeze(old=OLD,new=NEW):
    control=new/'control';execution=json.loads((control/'candidate09-execution.json').read_text());base=copy.deepcopy(execution)
    for name in ('recovery10_supplementary_verifier','recovery10_supplementary_receipt'):
        item=base['runtime_artifacts'].pop(name);require(sha(item['path'])==item['sha256'],'Supplementary identity changed: '+name)
    receipt_item=execution['runtime_artifacts']['recovery10_supplementary_receipt'];receipt=json.loads(Path(receipt_item['path']).read_text())
    require(receipt.get('passed') is True and receipt.get('execution_before_supplementary_pins')==base,'Supplementary verification does not bind current execution')
    verifier_path=Path(execution['runtime_artifacts']['recovery10_supplementary_verifier']['path'])
    require(verifier_path==control/'verify_installer_correction10.py','Wrong supplementary verifier path')
    fresh=module(verifier_path,'freeze10_supplementary').verify(control,new/'source',base)
    require(all(receipt.get(k)==v for k,v in fresh.items() if k!='created_at'),'Fresh supplementary verification disagrees')
    helper=control/'freeze_recovery09.py'
    expected=json.loads((control/'execution10-root-helper-pins.json').read_text())['freeze_recovery09.py']
    require(sha(helper)==expected,'Original reviewed freeze09 helper changed')
    return module(helper,'freeze10_original09').freeze(old=old,new=new)
if __name__=='__main__':print(json.dumps(freeze()))
