#!/usr/bin/env python3
"""Offline, append-only publication of a frozen captured-system diagnostic.

No numerical execution, network access, source mutation, or Git operation. An
actual terminal audit and exact raw records are prerequisites to publication.
"""
from pathlib import Path
from decimal import Decimal
from collections import Counter
import argparse, base64, hashlib, html, json, math, re

TOL = 2e-12
ANCHORS = {
 'historical_large': 'b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2',
 'current_small': 'f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044',
 'current_large': 'b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3',
}
STATES = {'reader_certified', 'numerical_failure', 'timeout',
          'execution_or_protocol_failed', 'identity_failed',
          'not_started_control_failure', 'running'}


def require(condition, message):
 if not condition: raise ValueError(message)


def sha(data): return hashlib.sha256(data).hexdigest()


def loads(data):
 def reject(value): raise ValueError('Non-finite JSON: ' + value)
 return json.loads(data, parse_constant=reject)


def pin(path):
 data = Path(path).read_bytes()
 return {'path': str(path), 'sha256': sha(data), 'bytes': len(data)}


def exact_file(record, root=None):
 path = Path(record['path'])
 require(path.is_absolute() and '..' not in path.parts and path.resolve() == path,
         'Expected canonical non-symlink local path')
 require(path.is_file() and (root is None or path.is_relative_to(root)), 'Local file outside scope')
 data = path.read_bytes()
 require(sha(data) == record['sha256'], 'Local input hash differs: ' + str(path))
 require('bytes' not in record or len(data) == record['bytes'], 'Local input size differs')
 return data


def raw_records(capture):
 records = {}
 for entry in capture['files']:
  require(set(('path', 'sha256', 'bytes', 'base64')) <= entry.keys(), 'Raw record lacks base64 bytes')
  path = entry['path']
  require(path.startswith('/') and '..' not in Path(path).parts and path not in records,
          'Invalid or repeated original path')
  data = base64.b64decode(entry['base64'], validate=True)
  require(sha(data) == entry['sha256'] and len(data) == entry['bytes'], 'Original bytes differ')
  data.decode('utf-8')
  require(b'\0' not in data, 'Binary payload cannot enter compact publication')
  records[path] = (entry, data)
 return records


def resolve_original(record, originals):
 require(record['path'] in originals, 'Required original record not copied: ' + record['path'])
 entry, data = originals[record['path']]
 require(entry['sha256'] == record['sha256'], 'Original identity differs')
 require('bytes' not in record or entry['bytes'] == record['bytes'], 'Original size differs')
 return data


def validate_family(family):
 require(family.get('schema_version') == 1 and family.get('kind') == 'bounded-captured-tangent-rhs-sensitivity', 'Unknown family')
 require(family.get('case_count') == 27 and family.get('attempt_count') == 54, 'Expected27 cases and54 planned calls')
 a = family['acceptance']
 require(a['relative_residual'] == TOL and a['maximum_iterations'] == 120 and a['restart'] == 20, 'Changed acceptance limits')
 require(len(family['anchors']) == 3 and {x['id']: x['sha256'] for x in family['anchors']} == ANCHORS, 'Changed anchors')
 cases = family['cases']; order = family['execution_order']
 require(len(cases) == 27 and len({x['id'] for x in cases}) == 27, 'Missing/repeated case')
 variants = {(None, 0, 0.)} | {(d,s,z) for d in ('smooth','alternating') for s in (-1,1) for z in (1e-12,1e-9)}
 for anchor in ANCHORS:
  rows = [x for x in cases if x['anchor'] == anchor]
  require(len(rows) == 9 and {(x['direction'],x['sign'],x['relative_scale']) for x in rows} == variants, 'Changed perturbation family')
  original = next(x for x in rows if x['direction'] is None)
  require(original['sha256'] == ANCHORS[anchor], 'Unperturbed anchor changed')
 expected = []
 for i, case in enumerate(cases):
  require('/' not in case['id'] and '..' not in case['id'], 'Unsafe case identity')
  for profile in (('baseline','wide') if i % 2 == 0 else ('wide','baseline')):
   expected.append({'attempt_id': f"{len(expected)+1:02d}-{case['id']}-{profile}", 'case_id':case['id'], 'profile':profile})
 require(order == expected, 'Frozen balanced execution order differs')
 return {x['id']:x for x in cases}, order


def trace_outcome(data, record, profile, anchor):
 lines = data.decode().splitlines(); rows = [loads(line) for line in lines]
 require(rows and rows[0].get('kind') == 'input' and rows[-1].get('kind') == 'terminal', 'Incomplete numerical trace')
 require(sum(x.get('kind')=='input' for x in rows)==1 and sum(x.get('kind')=='terminal' for x in rows)==1, 'Ambiguous trace attribution')
 expected = {'profile': profile, 'epochs': anchor['epochs'], 'dt': anchor['dt'], 'duration': anchor['duration'],
             'tolerance': TOL, 'maximum_iterations': 120, 'restart': 20, 'extended_digits': 64}
 require(all(rows[0].get(k)==v for k,v in expected.items()), 'Trace input/profile/limits differ')
 require(rows[0] == record['input'] and rows[-1] == record['terminal'] and len(rows)==record['record_count'], 'Result/trace differ')
 terminal = rows[-1]
 require(type(terminal.get('iterations')) is int and 0 <= terminal['iterations'] <= 120, 'Invalid iteration count')
 exact = json.loads(lines[-1], parse_float=Decimal)
 q = exact.get('physical_double_quad_relative_residual')
 certified = (isinstance(q,(Decimal,int)) and not isinstance(q,bool) and Decimal(q).is_finite()
              and 0 <= Decimal(q) <= Decimal.from_float(TOL))
 if record['status'] == 'reader_certified':
  require(record['returncode']==0 and terminal['status']=='passed' and terminal['kernel_status']=='passed' and certified,
          'Success lacks returned physical binary64 certificate')
  r = exact.get('relative_residual')
  require(isinstance(r,(Decimal,int)) and not isinstance(r,bool) and Decimal(r).is_finite()
          and 0 <= Decimal(r) <= Decimal.from_float(TOL), 'Success exceeds kernel guard')
  certificates = [json.loads(line,parse_float=Decimal) for line in lines
                  if loads(line).get('kind')=='physical_double_quad_residual' and loads(line).get('selection')=='returned']
  require(len(certificates)==1 and certificates[0].get('binary_digits')==113
          and certificates[0].get('iteration')==terminal['iterations']
          and certificates[0].get('relative_residual')==q, 'Certificate targets a different state')
 else:
  require(record['returncode']==1 and terminal['status']=='failed' and terminal['kernel_status'] in ('passed','failed')
          and not(terminal['kernel_status']=='passed' and certified), 'Inconsistent numerical failure')
 return terminal


def summarize(family, result, originals, binary):
 cases, order = validate_family(family)
 require(result['phase']=='run' and result['fit_attempts']==0 and result['groops_propagations']==0
         and result['release_evidence'] is False, 'Scope changed')
 require(result['planned_attempts']==order and result['binary']==binary, 'Plan or common reader changed')
 observed = result['attempts']
 require(len(observed)<=54, 'Extra calls')
 require([x['attempt_id'] for x in observed]==[x['attempt_id'] for x in order[:len(observed)]], 'Repeated, replaced, or reordered call')
 anchors = {x['id']:x for x in family['anchors']}; rows=[]
 for number,item in enumerate(order):
  case = cases[item['case_id']]
  row = dict(item, ordinal=number+1, anchor=case['anchor'], direction=case['direction'], sign=case['sign'],
             relative_scale=case['relative_scale'], actual_relative_balanced_norm=case['actual_relative_balanced_norm'],
             capture={'path':case['path'],'sha256':case['sha256'],'bytes':case['bytes']})
  if number>=len(observed):
   row.update(status='missing_not_recorded', source_status=None, accepted=False, outcome=None)
  else:
   r=observed[number]
   require(all(r.get(k)==v for k,v in item.items()), 'Attempt identity differs')
   require(r['status'] in STATES, 'Unknown outcome status')
   row.update(status=('incomplete_record' if r['status']=='running' else r['status']), source_status=r['status'], accepted=False, outcome=r)
   if r['status'] != 'not_started_control_failure':
    require(r['capture']=={'path':case['path'],'sha256':case['sha256']} and r['binary']==binary
            and r['argv']==[binary['path'],item['profile'],case['path']], 'Call input/binary/argv differs')
    require(r['fit_attempts']==0, 'Unexpected fit scope')
   if r['status'] in ('reader_certified','numerical_failure'):
    data=resolve_original(r['trace'],originals)
    row['terminal']=trace_outcome(data,r,item['profile'],anchors[case['anchor']]);row['accepted']=r['status']=='reader_certified'
   for key in ('trace','stderr'):
    if key in r: resolve_original(r[key],originals)
   if 'elapsed_seconds' in r:
    require(math.isfinite(r['elapsed_seconds']) and r['elapsed_seconds']>=0, 'Invalid measured time')
  rows.append(row)
 if result['status']=='completed_all_planned_calls':
  require(len(observed)==54 and all(x['status'] in ('reader_certified','numerical_failure','timeout') for x in rows), 'Completion hides missing or incomplete work')
 else:
  require(result['status'] in ('running','stopped_on_control_or_runtime_failure'), 'Unknown worker state')
 paired=[]
 for case in family['cases']:
  pair={r['profile']:r for r in rows if r['case_id']==case['id']}
  baseline,wide=pair['baseline'],pair['wide']
  terminal_states={'reader_certified','numerical_failure'}
  classification=('unresolved_pair' if baseline['status'] not in terminal_states or wide['status'] not in terminal_states
                  else 'both_certified' if baseline['accepted'] and wide['accepted']
                  else 'baseline_only_certified' if baseline['accepted']
                  else 'wide_only_certified' if wide['accepted'] else 'both_failed')
  paired.append({'case_id':case['id'],'anchor':case['anchor'],'classification':classification,
                 'baseline_attempt':baseline['attempt_id'],'wide_attempt':wide['attempt_id'],
                 'baseline_status':baseline['status'],'wide_status':wide['status']})
 return {'paired_cases':paired,'paired_counts':dict(Counter(x['classification'] for x in paired)),
         'wide_regressions':[x for x in paired if x['classification']=='baseline_only_certified'],
         'planned_calls':54,'recorded_calls':len(observed),'status_counts':dict(Counter(x['status'] for x in rows)),
         'by_profile':{p:dict(Counter(x['status'] for x in rows if x['profile']==p)) for p in ('baseline','wide')},
         'attempts':rows,'all_planned_calls_recorded':len(observed)==54,
         'benchmark_attempts':0,'groops_propagations':0,'native_correction_verified':False,'release_ready':False}


def baseline_comparison(summary, attribution, local_read, originals=None):
 require(attribution.get('before_planned_family_calls') is True and len(attribution['rows'])==3, 'Missing pre-outcome baseline attribution')
 require({x['anchor'] for x in attribution['rows']} == set(ANCHORS), 'Missing baseline anchor')
 output=[]
 for mapping in attribution['rows']:
  require(mapping['new_profile']=='baseline', 'Wrong baseline profile')
  old_data=local_read(mapping['prior_trace']);old_rows=[loads(line) for line in old_data.decode().splitlines()]
  require(old_rows[-1].get('kind')=='terminal', 'Historical trace lacks terminal')
  current=next(x for x in summary['attempts'] if x['case_id']==mapping['new_case_id'] and x['profile']=='baseline')
  require(current['anchor']==mapping['anchor'] and current['direction'] is None, 'Baseline mapping differs')
  old=old_rows[-1];now=current.get('terminal')
  fields=('status','iterations','relative_residual')
  changed=None if now is None else any(old.get(k)!=now.get(k) for k in fields)
  events_equal=None;old_event_count=None;new_event_count=None
  if originals is not None and current.get('outcome',{}).get('trace'):
   new_data=resolve_original(current['outcome']['trace'],originals)
   def normalized(data):
    events=[]
    for line in data.decode().splitlines():
     value=json.loads(line,parse_float=Decimal);kind=value.get('kind','').removeprefix('legacy_')
     if kind not in ('true_residual','projected_residual'):continue
     events.append((kind,value['iteration'],value.get('native_relative_residual',value.get('relative_residual')),value.get('final')))
    return events
   before,after=normalized(old_data),normalized(new_data)
   events_equal=before==after;old_event_count=len(before);new_event_count=len(after)
  output.append({'normalized_kernel_events_identical':events_equal,'prior_event_count':old_event_count,'current_event_count':new_event_count,
                 'anchor':mapping['anchor'],'prior_trace':mapping['prior_trace'],'prior_terminal':old,
                 'current_attempt_id':current['attempt_id'],'current_status':current['status'],'current_terminal':now,
                 'changed_status_iterations_or_kernel_residual':changed,
                 'interpretation':'Different reader binaries/code generation and certificate semantics are retained; source equality does not establish numerical identity. No speed claim.'})
 return output


def render(summary):
 esc=lambda x:html.escape(str(x))
 lead=('All27 wide captured systems passed the bounded diagnostic.' if summary['by_profile']['wide'].get('reader_certified',0)==27 and not summary['wide_regressions'] else 'The bounded diagnostic is incomplete or retains failures.')
 rows=[]
 for row in summary['attempts']:
  t=row.get('terminal',{})
  rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (row['ordinal'],row['case_id'],row['profile'],row['status'],t.get('iterations','—'),t.get('relative_residual','—'),t.get('physical_double_quad_relative_residual','—')) )+'</tr>')
 return ('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Frozen captured-system RHS diagnostic</title><style>body{font:15px system-ui;max-width:1350px;margin:2rem auto;line-height:1.5}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #bbb;padding:.4rem;text-align:left}code{overflow-wrap:anywhere}</style><h1>Repeated captured-system diagnostic</h1><p><strong>'''+esc(lead)+''' Wide regressions against certified paired baselines: '''+str(len(summary['wide_regressions']))+'''. This does not establish native trajectory closure.</strong> Every frozen call is retained below.</p><p>Certified results: baseline '''+str(summary['by_profile']['baseline'].get('reader_certified',0))+'''/27; wide '''+str(summary['by_profile']['wide'].get('reader_certified',0))+'''/27. The first54-call candidate was rejected for two paired regressions; its immutable <a href="../tangent-rhs-family01/index.html">earlier report</a> is retained separately.</p><p><strong>This is a bounded diagnostic, not the 68-fit orbit benchmark. V4 remains at 0/68 benchmark fits.</strong> No native trajectory closure, accepted covariance, general robustness, speedup or release readiness follows from these results.</p><p>Three preserved anchors each contribute the original RHS and eight signed smooth/alternating perturbations at relative scales 1e-12 and 1e-9. The frozen 54-call order, original inputs, common reader, 120-step limit, restart20 and 2e-12 threshold are retained. Success requires an independent113-bit residual on the actual returned physical binary64 state.</p><p>The first preflight compilation failure and fixture-only replacement remain preserved. This repeat uses separately reviewed candidate03, whose refinement starts from the returned binary64 state and its residual. Its fresh preflight and all27 input hashes plus54-call order were independently checked against the original frozen family. No acceptance limit changed.</p><p>All planned entries appear below, including missing, incomplete, failed or timed-out calls. Related RHS variants are not independent scientific trials. Baseline attribution compares the three original calls to prior traces and flags changes without assuming identical code generation.</p><p>Independent audit of all repeated baseline cases: '''+str(summary.get('repeat_baseline_audit',{}).get('identical_cases',0))+'''/27 have identical complete traces and outcomes against the first run; the exact per-case comparisons and source audit are in summary.json. The three older original-anchor comparisons are also retained.</p><p>Recorded calls: '''+str(summary['recorded_calls'])+'''/54. Outcome counts: <code>'''+esc(summary['status_counts'])+'''</code>.</p><p>Paired outcomes: <code>'''+esc(summary['paired_counts'])+'''</code>. Wide regressions against a certified paired baseline: <strong>'''+str(len(summary['wide_regressions']))+'''</strong>. Any paired failure remains explicit. A bounded captured-system pass supports further integration review only; complete native closure, the full correctness suite and the68-fit benchmark remain outstanding.</p><table><tr><th>Order</th><th>Case</th><th>Profile</th><th>Recorded outcome</th><th>Steps</th><th>Kernel residual</th><th>Returned-state113-bit residual</th></tr>'''+''.join(rows)+'''</table><ul><li><a href="summary.json">All outcomes, audit binding and scope</a></li><li><a href="baseline-attribution.json">Original baseline comparisons</a></li><li><a href="family-manifest.json">Exact frozen cases and order</a></li><li><a href="external-evidence.json">Explicit copies and external payload pins</a></li><li><a href="manifest.json">Publication manifest</a></li></ul></html>''').encode()


def walk(value):
 if isinstance(value,dict):
  if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):yield value
  for child in value.values():yield from walk(child)
 elif isinstance(value,list):
  for child in value:yield from walk(child)


def validate_repeat_lineage(source_audit, passed_audit, recipe):
 require(source_audit.get('schema')=='orbit-poc-wide-candidate03-independent-source-review-v1'
         and source_audit.get('passed') is True
         and source_audit.get('changed_files')==['include/wideSixStateTangent.h']
         and source_audit.get('actual_predecessor_outcomes')==recipe['previous_terminal_audit']
         and passed_audit.get('source_review')==recipe['replacement_source_audit'], 'Repeated candidate source attribution differs')
 require(passed_audit.get('original_family_audit')==recipe['previous_preflight_audit']
         and passed_audit.get('repeat_reference')==recipe['previous_family_manifest']
         and passed_audit.get('checks',{}).get('all27case_hashes_and54order_identical_to_first_family') is True
         and passed_audit.get('checks',{}).get('complete_manifest_equal_except_case_paths') is True,
         'Repeated family attribution differs')


def verify_repeated_family(original, repeated):
 validate_family(original);validate_family(repeated)
 # Only the case payload storage path may change. Every case byte hash,
 # perturbation, baseline anchor, acceptance setting and order stays exact.
 original=loads(json.dumps(original));repeated=loads(json.dumps(repeated))
 for before,after in zip(original['cases'],repeated['cases']):before['path']=after['path']
 require(original==repeated,'Repeated frozen family changed beyond case storage paths')


def repeated_baseline_evidence(audit, summary, previous_audit, source):
 require(audit.get('first_run_audit')==previous_audit, 'Wrong previous baseline audit')
 rows=audit.get('repeat_baseline_comparisons')
 expected={r['case_id']:r for r in summary['attempts'] if r['profile']=='baseline'}
 require(isinstance(rows,list) and len(rows)==27 and len({r['case_id']for r in rows})==27
         and {r['case_id']for r in rows}==set(expected), 'Incomplete all27 baseline audit')
 keys=('normalized_kernel_events_identical','status_iterations_and_kernel_residual_identical',
       'complete_trace_semantically_identical','attempt_status_identical')
 for row in rows:
  require(row['attempt_id']==expected[row['case_id']]['attempt_id']
          and row['current_trace']==(expected[row['case_id']].get('outcome')or{}).get('trace'), 'Baseline trace attribution differs')
  require(all(type(row.get(key))is bool for key in keys), 'Unresolved baseline comparison')
 return {'source':source,'case_count':27,'identical_cases':sum(all(row[key]for key in keys)for row in rows),'comparisons':rows}


def publish(recipe):
 require(recipe['schema']=='orbit-poc-rhs-family-repeat-publication-recipe-v1', 'Unknown recipe')
 root=Path(recipe['local_control_root']);output=Path(recipe['output'])
 require(root.is_absolute() and output.is_absolute() and '..' not in output.parts and not output.exists(), 'Publication must be new')
 audit_data=exact_file(recipe['terminal_audit'],root);audit=loads(audit_data)
 failed_audit=loads(exact_file(recipe['failed_preflight_audit'],root))
 passed_audit=loads(exact_file(recipe['passed_preflight_audit'],root))
 source_audit=loads(exact_file(recipe['replacement_source_audit'],root))
 require(failed_audit.get('passed') is True and failed_audit.get('outcome')=='failed_fixture_compilation'
         and failed_audit.get('fixture_executions')==0 and failed_audit.get('family_generated') is False
         and failed_audit.get('planned_family_calls_executed')==0, 'Historical failed preflight attribution differs')
 require(passed_audit.get('passed') is True and passed_audit.get('family_manifest')==recipe['family_manifest']
         and passed_audit.get('binary')==recipe['binary'] and passed_audit.get('checks',{}).get('planned_calls')==54
         and passed_audit.get('checks',{}).get('planned_family_calls_started')==0, 'Successful preflight/freeze attribution differs')
 validate_repeat_lineage(source_audit,passed_audit,recipe)
 require(audit.get('passed') is True, 'Independent actual terminal audit required')
 # The recipe declares exact audit JSON pointers; no audit bytes or paths are rewritten.
 def audit_field(pointer):
  value=audit
  for key in pointer:value=value[key]
  return value
 originals={};capture_payloads=[]
 for entry in recipe['raw_captures']:
  data=exact_file(entry['pin'],root);records=raw_records(loads(data));capture_payloads.append((entry,data,records))
  for path,record in records.items():
   require(path not in originals, 'Repeated original across captures');originals[path]=record
 for name in ('family_manifest','result','run_capture'):
  require(audit_field(recipe['audit_bindings'][name])==recipe[name], 'Audit binding differs: '+name)
 require(any(entry['pin']==recipe['run_capture'] for entry,_,_ in capture_payloads), 'Run capture missing')
 require(any(entry['pin']==failed_audit['capture'] for entry,_,_ in capture_payloads), 'Failed preflight raw capture missing')
 require(any(entry['pin']==passed_audit['raw_capture'] for entry,_,_ in capture_payloads), 'Passed preflight raw capture missing')
 family_data=resolve_original(recipe['family_manifest'],originals);family=loads(family_data)
 verify_repeated_family(loads(resolve_original(recipe['previous_family_manifest'],originals)),family)
 result=loads(resolve_original(recipe['result'],originals));summary=summarize(family,result,originals,recipe['binary'])
 require(audit_field(recipe['audit_bindings']['binary'])==recipe['binary'], 'Audited reader differs')
 require(audit_field(recipe['audit_bindings']['planned_calls'])==54, 'Audit does not cover frozen54')
 require(audit_field(recipe['audit_bindings']['recorded_calls'])==summary['recorded_calls'], 'Audit/result count differs')
 attribution=loads(exact_file(recipe['baseline_attribution'],root))
 comparisons=baseline_comparison(summary,attribution,lambda r:exact_file(r,root),originals)
 local_files={r['path']:r for r in recipe['local_files']}
 for record in [recipe['terminal_audit'],recipe['baseline_attribution'],recipe['failed_preflight_audit'],recipe['passed_preflight_audit'],recipe['replacement_source_audit'],recipe['previous_terminal_audit'],recipe['previous_preflight_audit']]+[x['pin'] for x in recipe['raw_captures']]+[x['prior_trace'] for x in attribution['rows']]:
  if record['path'] in local_files:require(local_files[record['path']]['sha256']==record['sha256'],'Contradictory local pin')
  local_files[record['path']]=record
 payloads=[];values={};copies={};remote_copies={}
 def add(rel,data,original=None,kind=None):
  require(rel not in {x[0] for x in payloads} and not rel.startswith('/') and '..' not in Path(rel).parts, 'Duplicate/unsafe publication member')
  data.decode('utf-8');require(b'\0' not in data,'Binary member')
  meta={'path':rel,'sha256':sha(data),'bytes':len(data)}
  if original:meta['original']=original;copies[(original['path'],original['sha256'])]=rel
  if kind:meta['attribution']=kind
  payloads.append((rel,data,meta))
  if rel.endswith('.json'):
   try:values[rel]=loads(data)
   except ValueError:pass
 def add_json(rel,value):add(rel,(json.dumps(value,indent=2,allow_nan=False)+'\n').encode())
 for record in sorted(local_files.values(),key=lambda r:r['path']):
  add('evidence/'+str(Path(record['path']).relative_to(root)),exact_file(record,root),record,'Exact local record/source bytes; identical deployed source is not inferred remote acquisition.')
 for group,_,records in capture_payloads:
  require(re.fullmatch('[a-z0-9_-]+',group['label']) is not None,'Unsafe capture label')
  for i,(path,(record,data)) in enumerate(records.items(),1):
   rel=f"original/{group['label']}/{i:03d}-{Path(path).name}";original={k:record[k] for k in ('path','sha256','bytes')}
   add(rel,data,original,'Exact original remote bytes decoded from audited base64; CR/LF preserved.');remote_copies[(path,record['sha256'])]=rel
 add('family-manifest.json',family_data,recipe['family_manifest'],'Exact original frozen manifest; path provenance retained.')
 summary.update(schema='orbit-poc-captured-rhs-family-publication-v1',audit=recipe['terminal_audit'],family_manifest=recipe['family_manifest'],worker_result=recipe['result'],reader=recipe['binary'],scope='Captured-system diagnostics only; not independent scientific trials, native closure, or the68-fit benchmark.',baseline_changed=any(x['changed_status_iterations_or_kernel_residual'] is True or x['normalized_kernel_events_identical'] is False for x in comparisons))
 summary['repeat_baseline_audit']=repeated_baseline_evidence(audit,summary,recipe['previous_terminal_audit'],recipe['terminal_audit'])
 add_json('summary.json',summary);add_json('baseline-attribution.json',{'frozen_mapping':recipe['baseline_attribution'],'comparisons':comparisons})
 refs={}
 for member,value in values.items():
  for record in walk(value):
   if not record['path'].startswith('/') or len(record['sha256'])!=64:continue
   key=(record['path'],record['sha256']);ref=refs.setdefault(key,{'path':key[0],'sha256':key[1],'recorded_in':[]})
   if 'bytes' in record:ref['bytes']=record['bytes']
   if member not in ref['recorded_in']:ref['recorded_in'].append(member)
   if key in remote_copies:ref.update(availability='copied_exact_remote_record',copy=remote_copies[key])
   elif key in copies:ref.update(availability='copied_exact_local_record_or_source',copy=copies[key])
   else:ref['availability']='external_payload_not_copied_by_this_publication'
 add_json('external-evidence.json',{'schema':'orbit-poc-explicit-publication-reference-inventory-v1','records':list(refs.values()),'scope':'Capture arrays, binaries and original datasets remain external. Local equal source bytes do not imply a remote acquisition; empty files are never associated by hash alone.'})
 add('index.html',render(summary))
 output.mkdir()
 for rel,data,_ in payloads:
  p=output/rel;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb') as f:f.write(data)
 manifest={'schema':'orbit-poc-compact-publication-manifest-v1','files':[r for _,_,r in payloads],'file_count':len(payloads),'total_bytes':sum(len(b) for _,b,_ in payloads),'scope':summary['scope']}
 with(output/'manifest.json').open('x')as f:json.dump(manifest,f,indent=2);f.write('\n')
 return {'output':str(output),'manifest':pin(output/'manifest.json'),'recorded_calls':summary['recorded_calls'],'planned_calls':54,'file_count':len(payloads),'total_bytes':manifest['total_bytes']}


def main():
 p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,required=True);p.add_argument('--sha256',required=True);args=p.parse_args()
 recipe=loads(exact_file({'path':str(args.recipe),'sha256':args.sha256}))
 print(json.dumps(publish(recipe),indent=2))
if __name__=='__main__':main()
