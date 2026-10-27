#!/usr/bin/env python3
"""Preserve isolated archive tamper cases; no scientific imports or subprocesses."""
import argparse, json, re, shutil
from datetime import datetime, timezone
from pathlib import Path
import verify_packet as v

ROOT=Path(__file__).resolve().parent
CASES=(
 ('manifest_total','manifest totals',False),
 ('report_success','report exact recomputation from evidence',True),
 ('cold_fit_claim','report exact recomputation from evidence',True),
 ('cleanup_claim','report exact recomputation from evidence',True),
 ('competitor_claim','report exact recomputation from evidence',True),
 ('audit_changed','exact independent audit trust anchor',True),
 ('missing_responsibility','README.md essential disclosure',True),
 ('missing_timing_limit','README.md essential disclosure',True),
 ('omitted_member','manifest exact planned paths',True),
 ('extra_member','manifest exact planned paths',True),
 ('remapped_provenance','exact14 original copy mapping',True),
 ('unlaunched_stage_pass','report exact recomputation from evidence',True))

def pin(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':v.sha(p)}
def save(p,value):
 with p.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def replace_json(p,change):
 value=v.load(p);change(value);p.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def refresh(packet):
 files=[{'path':str(p.relative_to(packet)),'bytes':p.stat().st_size,'sha256':v.sha(p)} for p in sorted(packet.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json']
 (packet/'artifact-manifest.json').write_text(json.dumps({'schema':'immutable-publication-manifest-v1','scope':'Isolated tamper fixture only','files':files,'file_count':len(files),'total_bytes':sum(p['bytes'] for p in files)},indent=2,sort_keys=True)+'\n')
def mutate(packet,name):
 report=packet/'report.json'
 if name=='manifest_total':replace_json(packet/'artifact-manifest.json',lambda x:x.update(total_bytes=x['total_bytes']+1))
 elif name=='report_success':replace_json(report,lambda x:x.update(status='passed',aggregate_qualified=True))
 elif name=='cold_fit_claim':replace_json(report,lambda x:x.update(cold_fits_launched=2))
 elif name=='cleanup_claim':replace_json(report,lambda x:x['completed_evidence'][0]['cleanup'].update(remaining=[{'pid':123,'start_ticks':456}]))
 elif name=='competitor_claim':replace_json(report,lambda x:x['stop']['observed_process'].update(pid=1))
 elif name=='audit_changed':replace_json(packet/'evidence/terminal-audit/audit01.json',lambda x:x['checks'][0].update(passed=False))
 elif name in ('missing_responsibility','missing_timing_limit'):
  old,new=('scheduling mistake','coordination issue') if name=='missing_responsibility' else ('not uncontended benchmark measurements','observed validation timings')
  p=packet/'README.md';text=p.read_text()
  if old not in text:raise ValueError('Tamper fixture missing expected disclosure')
  p.write_text(text.replace(old,new))
 elif name=='omitted_member':(packet/'evidence/refinements/pulses.json').unlink()
 elif name=='extra_member':(packet/'unplanned.txt').write_text('Isolated extra-file tamper fixture\n')
 elif name=='remapped_provenance':replace_json(packet/'provenance.json',lambda x:x['files'][0].update(original_path='/foreign/unrelated-plan.json'))
 elif name=='unlaunched_stage_pass':replace_json(report,lambda x:x['outcomes'][4].update(status='passed'))
 else:raise ValueError('Unknown tamper fixture')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--packet',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 if not args.output.is_absolute() or args.output.parent!=ROOT or args.output.resolve()!=args.output or not re.fullmatch(r'tamper[0-9]+',args.output.name):raise ValueError('Fresh ordinary tamperNN child under draft root required')
 if not args.packet.is_absolute() or args.packet.resolve()!=args.packet or args.packet.name!='packet' or args.packet.parent.parent!=ROOT or not re.fullmatch(r'assembly[0-9]+',args.packet.parent.name):raise ValueError('Use a separate assembled packet under this draft root')
 args.output.mkdir();baseline_manifest=pin(args.packet/'artifact-manifest.json');before=[pin(p) for p in sorted(args.packet.rglob('*')) if p.is_file()]
 save(args.output/'intent.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'packet':str(args.packet),'manifest':baseline_manifest,'checker':pin(ROOT/'verify_packet.py'),'harness':pin(Path(__file__)),'case_registry':CASES,'scope':'Fresh copied archive fixtures only. No original evidence or published packet is changed.'})
 baseline=v.verify(args.packet);save(args.output/'baseline.json',baseline);results=[]
 if baseline['passed']:
  for name,expected,rehashed in CASES:
   folder=args.output/name;folder.mkdir();copy=folder/'packet'
   try:
    shutil.copytree(args.packet,copy)
    mutate(copy,name)
    if rehashed:refresh(copy)
    observed=v.verify(copy);save(folder/'verification.json',observed)
    failed_name=next((x['name'] for x in observed['checks'] if not x['passed']),None)
    success=observed['passed'] is False and failed_name==expected
    row={'name':name,'passed':success,'manifest_refreshed':rehashed,'expected_failure':expected,'actual_failure':failed_name,'verification':pin(folder/'verification.json'),'mutated_manifest':pin(copy/'artifact-manifest.json')}
   except Exception as exc:row={'name':name,'passed':False,'error':repr(exc),'partial_fixture_preserved':True}
   save(folder/'result.json',row);results.append({**row,'result':pin(folder/'result.json')})
 unchanged=before==[pin(p) for p in sorted(args.packet.rglob('*')) if p.is_file()]
 result={'schema':'candidate06-terminal-packet-tamper-tests-v1','passed':baseline['passed'] and len(results)==len(CASES) and all(x['passed'] for x in results) and unchanged,'tests':1+len(results),'expected_tests':1+len(CASES),'case_registry':[x[0] for x in CASES],'cases':results,'baseline':pin(args.output/'baseline.json'),'manifest_sha256':baseline_manifest['sha256'],'original_packet_unchanged':unchanged,'checker':pin(ROOT/'verify_packet.py'),'harness':pin(Path(__file__)),'scientific_code_executed':False,'native_runs':0}
 save(args.output/'result.json',result);print(json.dumps({k:val for k,val in result.items() if k!='cases'}));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
