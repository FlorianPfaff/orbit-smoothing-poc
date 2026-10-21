"""Run the original analytical compensation fixture once for a completed build."""
from pathlib import Path
import argparse,hashlib,json
import complete_native_replay_attribution02 as attribution
import compensation_native_regression02 as regression
SCHEMA='orbit-poc-nominal-complete-supplemental-plan-v1'
INPUTS={'build_result','build_audit','supplemental_fixture'}
def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);q=a.parse_args(argv)
 if hashlib.sha256(q.plan.read_bytes()).hexdigest()!=q.sha256:raise ValueError('Plan changed')
 p=json.loads(q.plan.read_text())
 if p['schema']!=SCHEMA or set(p['inputs'])!=INPUTS:raise ValueError('Exact supplemental plan required')
 for item in p['inputs'].values():attribution.check(item)
 built,bound=attribution.verify(p['inputs'],p['native']);fixture=attribution.check(p['inputs']['supplemental_fixture']);root=Path(p['output'])
 if not root.is_absolute() or '..'in root.parts or root.exists():raise ValueError('Fresh canonical supplemental output required')
 root.mkdir();result={'schema':'orbit-poc-complete-native-analytical-supplemental-v1','status':'running','build_result':p['inputs']['build_result'],'build_audit':p['inputs']['build_audit'],'native':p['native'],'build_attribution':bound,'native_propagations':0,'fit_attempts':0,'original_test_inventories_changed':False}
 def save():(root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 save()
 try:
  result['regression']=regression.run(root/'analytical-fixture',built,fixture)
  for item in p['inputs'].values():attribution.check(item)
  attribution.check(p['native']);result['status']='passed'
 except BaseException as error:result.update(status='failed',error=repr(error));raise
 finally:save()
 return 0
if __name__=='__main__':raise SystemExit(main())
