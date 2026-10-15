#!/usr/bin/env python3
"""Freeze independently reviewed source05; preserve earlier source and failures."""
from pathlib import Path
import argparse, datetime, hashlib, json, subprocess, tarfile
C=Path('/mnt/d/orbit-numerics-v3.1/correctness/control')
S=C.parent/'source-05'
R=Path('/mnt/seagate10tb/orbit-v31-correctness-09-florianpfaff')
PREVIOUS=C.parent/'remote-recovery-08-terminal-01/control'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path):return {'path':str(path),'sha256':sha(path)}
def save(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
def require(ok,message):
    if not ok:raise RuntimeError(message)
def check_inventory(previous,files,regression_files,count):
    before=previous['source']['files']
    require(set(before)<=set(files),'Cannot delete frozen source files')
    for name in before:
        if name.startswith('tests/') or name.startswith('scripts/validate_numerics_') or name=='src/orbit_poc/numerics/backend.py':
            require(before[name]==files[name],'Existing test/gate implementation changed: '+name)
    require(previous['regression_suite']['expected_count']==40,'Previous40 regressions changed')
    old=previous['regression_suite']['files']
    require(regression_files and len(regression_files)==len(set(regression_files)),'New regression files required')
    require(all(name.startswith('tests/test_') and name.endswith('.py') and name in files and name not in before for name in regression_files),'Regressions must be separate new tracked test files')
    require(type(count) is int and count>40,'New regression total must preserve40 and add tests')
    return {'files':old+regression_files,'expected_count':count}

def freeze(expected_commit,review_path,new_regressions,regression_count):
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=S).strip(),'Commit the independently reviewed source first')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=S,text=True).strip();require(commit==expected_commit,'Reviewed source commit differs')
    review=json.loads(review_path.read_text());require(review.get('passed') is True,'Independent source review must pass before freeze')
    names=subprocess.check_output(['git','ls-files','-z'],cwd=S).decode().split('\0')[:-1]
    files={name:sha(S/name) for name in sorted(names)}
    oldpins=json.loads((PREVIOUS/'candidate07-pins.json').read_text())
    require(sha(PREVIOUS/'candidate07-pins.json')=='91b84d5a702c0b782f80cbebf68d2576c54797f809e9247eceaf4caeceee57d5','Original08 pins changed')
    require(sha(PREVIOUS/'candidate07-source-freeze.json')==oldpins['new_source_freeze']['sha256'],'Previous source freeze changed')
    previous=json.loads((PREVIOUS/'candidate07-source-freeze.json').read_text())
    require(previous['commit']=='8e4d36f7c47d57acdb9fa30d15a6005189bbf221' and previous['source']['sha256']=='774d6d777e1f5caf09b5599a8b469e421327f2e1f962eb75a5af17b0bc8bf8c2' and len(previous['source']['files'])==771,'Wrong immediate previous source')
    regression=check_inventory(previous,files,new_regressions,regression_count)
    lineage_path=PREVIOUS/'candidate07-correction-lineage.json';oldlineage=json.loads(lineage_path.read_text());oldpins=json.loads((PREVIOUS/'candidate07-pins.json').read_text())
    require(sha(lineage_path)==oldpins['correction_lineage']['sha256'],'Executed08 lineage changed')
    changes={name:{'before':previous['source']['files'].get(name),'after':value} for name,value in files.items() if previous['source']['files'].get(name)!=value}
    inventory={'files':files,'sha256':hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    require(review.get('source_sha256')==inventory['sha256'] and review.get('source_file_count')==len(files),'Independent source review does not identify the current tracked bytes')
    measured=C/'d03-analysis04-attribution-review-01.json'
    require(sha(measured)=='ccb45608af591fa6b5f1d0d962317801b40bd4740d98b00c4862ec9cba7d6a98','Measured defect review changed')
    freeze={'schema':'orbit-poc-candidate09-source-freeze-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'commit':commit,'previous_source_commit':previous['commit'],'original_source_commit':'e7c93a97603cddcbef2f163257a34f48577c5516','original_native_test_count':106,'source':inventory,'regression_suite':regression,'independent_review':{'path':str(R/'control'/review_path.name),'sha256':sha(review_path)},'scope':'Preserve expansion precision through light-time distance/division/clock addition and split-Time subtraction; no physics, statistical model, derivative, convergence, closure threshold, original14 input or original106 gate changes. Native validation pending.'}
    for name in ('candidate09-source-freeze.json','candidate09-correction-lineage.json','candidate09-source.tar','candidate09-source-packaging.json'):
        require(not (C/name).exists() and not (C/name).is_symlink(),'No implicit source packaging retry: '+name)
    fp=C/'candidate09-source-freeze.json';save(fp,freeze)
    staged_review={'path':str(R/'control'/measured.name),'sha256':sha(measured)}
    lineage={'schema':'orbit-poc-correctness-correction-lineage-v3','original_source_freeze':oldlineage['original_source_freeze'],'previous_source_freeze':oldlineage['new_source_freeze'],'new_source_freeze':{'path':str(R/'control'/fp.name),'sha256':sha(fp)},'previous_correction_lineage':oldpins['correction_lineage'],'original_source_sha256':oldlineage['original_source_sha256'],'previous_source_sha256':previous['source']['sha256'],'new_source_sha256':inventory['sha256'],'changes':changes,**{key:oldlineage[key] for key in ('failed_pipeline04','failed_pipeline05','failed_pipeline06')},'failed_pipeline07':{'path':'/mnt/seagate10tb/orbit-v31-correctness-07-florianpfaff/validation-07/pipeline.json','sha256':sha(C.parent/'remote-recovery-07-terminal-01/validation-07/pipeline.json')},'failed_pipeline08':{'path':'/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff/validation-07/pipeline.json','sha256':sha(C.parent/'remote-recovery-08-terminal-01/validation-07/pipeline.json')},'measured_defect':staged_review,'purpose':'Correct the dominant clock-plus-travel duration rounding measured across all8064 GNSS rows, preserving native physical model and every existing acceptance threshold.'}
    lp=C/'candidate09-correction-lineage.json';save(lp,lineage)
    target=C/'candidate09-source.tar'
    with tarfile.open(target,'x') as stream:
        for name in names:stream.add(S/name,arcname=name,recursive=False)
    receipt={'schema':'orbit-poc-candidate09-source-packaging-v1','commit':commit,'source_files':len(files),'source_sha256':inventory['sha256'],'incremental_changes':len(changes),'source_freeze':pin(fp),'lineage':pin(lp),'source_archive':pin(target),'source_review':pin(review_path),'native_validation_complete':False}
    save(C/'candidate09-source-packaging.json',receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--expected-commit',required=True);p.add_argument('--source-review',type=Path,required=True);p.add_argument('--new-regression-file',action='append',required=True);p.add_argument('--regression-count',type=int,required=True);args=p.parse_args()
    print(json.dumps(freeze(args.expected_commit,args.source_review,args.new_regression_file,args.regression_count)))
