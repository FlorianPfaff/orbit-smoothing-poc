#!/usr/bin/env python3
"""Run four read-only pair comparisons after all eight process attempts close."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,default=Path('/home/emper/orbit-v4-failure-investigation'))
    p.add_argument('--number',type=int,required=True)
    args=p.parse_args();base=args.base.resolve();script=base/'source/scripts/check_nuisance_cost_only_pair.py'
    spec=importlib.util.spec_from_file_location('cost_check',script);check=importlib.util.module_from_spec(spec)
    exec(compile(script.read_bytes(),str(script),'exec'),check.__dict__)
    runs=base/f'cost-pairs{args.number:02}';out=base/f'outputs/cost-pairs{args.number:02}-checks'
    actual=check.base.strict_json((runs/'result.json').read_bytes())
    if actual.get('all_planned_attempts_executed') is not True or len(actual.get('results',[]))!=8:
        raise ValueError('The complete eight-attempt execution aggregate is required')
    out.mkdir();items=[]
    for method in ('pulses','log_drag_ou'):
        for accumulate in (0,1):
            name=f'{method}-accumulate{accumulate}'
            value=check.compare(runs/(name+'-cost0'),runs/(name+'-cost1'),freeze=runs/'freeze.json')
            target=out/(name+'.json')
            with target.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
            item={'pair':name,'passed':value['passed'],'artifact_equality':value['artifact_equality'],
                  'comparisons':value['scientific_comparison_count'],'issues':value['issues'],**check.base.analysis.artifact(target)[0]}
            items.append(item);print(json.dumps(item),flush=True)
    index={'schema':'cost-only-pair-check-execution-index-v1','created_at':datetime.now(timezone.utc).isoformat(),
           'runner':check.base.analysis.artifact(__file__)[0],'checker':check.base.analysis.artifact(script)[0],
           'freeze':check.base.analysis.artifact(runs/'freeze.json')[0],'pairs':items,'native_execution':False,
           'full_fit_verified':False,'release_authority':False}
    with (out/'index.json').open('x') as stream:json.dump(index,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    return 0 if all(item['passed'] for item in items) else 1


if __name__=='__main__':raise SystemExit(main())
