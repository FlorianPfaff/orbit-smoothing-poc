import hashlib, importlib.util, json, shutil, tempfile
from pathlib import Path
BASE=Path('/home/emper/orbit-nuisance-performance/source')
OUT=Path('/home/emper/orbit-nuisance-performance/control/wholefit-checker-review03')
p=BASE/'tests/test_nuisance_wholefit_analysis.py'
s=importlib.util.spec_from_file_location('review_wholefit_fixtures',p); f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
records=[]
for case in ['baseline','both_stale_optimizer','one_point_deleted','both_points_deleted','zero_complete_wall']:
    with tempfile.TemporaryDirectory(prefix='wholefit-independent-'+case+'-') as tmp:
        root=f.success_pair(Path(tmp))
        if case=='both_stale_optimizer':
            for cache in (0,1): f.write(root/f'cache{cache}'/'iterations.json',{'status':'failed','converged':False,'history':[],'confirmation_checks':[],'elapsed_seconds':50})
        if case in ('one_point_deleted','both_points_deleted'):
            for cache in ([1] if case=='one_point_deleted' else [0,1]): shutil.rmtree(root/f'cache{cache}'/'point-001-initial')
        if case=='zero_complete_wall':
            run=root/'cache1';supervisor=f.read(run/'supervisor.json');supervisor['elapsed_seconds']=0.;f.write(run/'supervisor.json',supervisor);f.refresh(run)
        try:
            result=f.check.analyze(root)
            record={'case':case,'analysis_status':result['analysis_status'],'scientific_equivalence':result['scientific_equivalence']['status'],'issues':result['issues'],'scientific_gate_modules':result['scientific_gate_modules']}
            if case=='baseline': assert result['analysis_status']=='valid' and result['scientific_equivalence']['status']=='passed'
            else: assert result['analysis_status']=='invalid' and result['scientific_equivalence']['status']!='passed'
            (OUT/(case+'.json')).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        except ZeroDivisionError as error:
            assert case=='zero_complete_wall'
            record={'case':case,'exception_type':type(error).__name__,'error':str(error),'false_scientific_acceptance':False}
        records.append(record)
(OUT/'counterexamples.json').write_text(json.dumps({'checker_sha256':hashlib.sha256((BASE/'scripts/analyze_nuisance_wholefit.py').read_bytes()).hexdigest(),'records':records},indent=2,sort_keys=True)+'\n')
print(json.dumps([dict((k,v) for k,v in r.items() if k!='scientific_gate_modules') for r in records],indent=2))
