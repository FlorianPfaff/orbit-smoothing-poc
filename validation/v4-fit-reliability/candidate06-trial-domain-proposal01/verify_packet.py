#!/usr/bin/env python3
"""Read-only stdlib verifier; writes JSON only to stdout, never runs candidate code."""
import argparse
import ast
import difflib
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

class Verification:
 def __init__(self,root,originals=False):self.root=root;self.originals=originals;self.checks=[]
 def check(self,label,condition):self.checks.append({'name':label,'passed':bool(condition)})
 def data(self,name):return json.loads((self.root/name).read_text())
 @staticmethod
 def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
 def run(self):
  m=self.data('manifest.json');s=self.data('summary.json');rows=m['files']
  self.check('immutable manifest',m.get('immutable') is True)
  self.check('no packet launch or release authority',m.get('launch_authority') is False and m.get('release_authority') is False)
  self.check('no packaging native runs or source mutations',m.get('native_runs_by_packaging')==0 and m.get('source_or_control_mutations') is False)
  names=[x['path'] for x in rows];self.check('unique inventory',len(names)==len(set(names))==m['file_count'])
  expected=set(names)|{'manifest.json'}
  actual={str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file()}
  self.check('exact file inventory',actual==expected)
  refs={}
  for row in rows:
   rel=Path(row['path']);p=self.root/rel
   self.check('safe path:'+str(rel),not rel.is_absolute() and '..' not in rel.parts and not p.is_symlink())
   self.check('bytes:'+str(rel),p.stat().st_size==row['bytes'])
   self.check('sha256:'+str(rel),self.sha(p)==row['sha256'])
   if 'original_path' in row:
    refs[(row['original_path'],row['sha256'])]=row['path']
    if self.originals:
     q=Path(row['original_path']);self.check('original:'+str(rel),q.is_file() and q.stat().st_size==row['bytes'] and self.sha(q)==row['sha256'])
  self.check('pending native validation',s['candidate06_native_correctness']=='pending')
  self.check('both cold fits pending',s['candidate06_cold_pulse']==s['candidate06_cold_density']=='pending')
  self.check('no new numerical results or authority',s['numerical_gate_or_cold_fit_results_included'] is False and all(s[x] is False for x in ['launch_authority','release_authority','covariance_authority']))
  self.check('models thresholds and frozen campaigns unchanged',all(s[x] is False for x in ['native_source_changed','native_rebuild_required','physical_or_statistical_model_changes','threshold_changes','frozen_benchmark_changes']))
  self.check('parent publication fixed',s['parent_publication_commit']=='d3d82ed450b43901f9b749f5c4086a6e69211b24')
  snap=self.data('candidate/source-snapshot.json');parent=self.data('candidate/parent-copy.json')
  self.check('source snapshot identity',self.sha(self.root/'candidate/source-snapshot.json')==s['source_snapshot_sha256']=='24c41840ad687aef76111e213b027c8ff613463313ccd7fb8fbf759e253db739')
  self.check('native binary identity',snap['native_binary']['sha256']==s['native_binary_sha256']=='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d')
  self.check('candidate04 inheritance only',parent['parent_candidate']=='candidate04' and parent['candidate05_inherited'] is False and parent['copied_files']==484)
  self.check('full source inventory recorded, not copied',len(snap['files'])==492)
  production=[x for x in snap['changes'] if x['before_sha256'] is not None]
  self.check('exactly two existing production changes',{x['relative_path'] for x in production}==set(s['production_python_files']))
  inv={x['relative_path']:x for x in snap['files']}
  for row in snap['changes']:
   rel=row['relative_path'];p=self.root/'candidate/source'/rel
   self.check('changed source:'+rel,self.sha(p)==row['after_sha256']==inv[rel]['sha256'])
   if row['before_sha256']:
    self.check('parent source:'+rel,self.sha(self.root/'candidate/parent-source'/rel)==row['before_sha256'])
  for rel in s['production_python_files']:
   ast.parse((self.root/'candidate/source'/rel).read_text())
   self.check('production syntax:'+rel,True)
  patch=''
  for rel in ['docs/numerics-trial-domain.md','src/orbit_poc/numerics/backend.py','src/orbit_poc/numerics/optimizer.py','tests/test_numerics_trial_domain.py']:
   before=self.root/'candidate/parent-source'/rel
   a=before.read_text().splitlines(keepends=True) if before.exists() else []
   b=(self.root/'candidate/source'/rel).read_text().splitlines(keepends=True)
   patch+=''.join(difflib.unified_diff(a,b,fromfile='a/'+rel,tofile='b/'+rel))
  self.check('exact text patch reconstructs changed source',patch==(self.root/'candidate/candidate06-python-domain.patch').read_text())
  fixture=self.data('candidate/source/tests/fixtures/density_reference_domain/manifest.json')
  self.check('fixture excludes truth',fixture['truth_inputs'] is False)
  for row in fixture['files']:
   p=self.root/'candidate/source/tests/fixtures/density_reference_domain'/row['fixture']
   self.check('archived fixture:'+row['fixture'],self.sha(p)==row['sha256'] and p.stat().st_size==row['bytes'])
  for attempt in ['unit01','unit02']:
   for row in self.data('candidate/tests/'+attempt+'/source-manifest.json'):
    self.check('focused source:'+attempt+'/'+row['relative_path'],self.sha(self.root/'candidate/tests'/attempt/'source'/row['relative_path'])==row['sha256'])
  self.check('fixture-only development correction',all(self.sha(self.root/'candidate/tests/unit01/source'/x)==self.sha(self.root/'candidate/tests/unit02/source'/x) for x in s['production_python_files']))
  for row in s['tests']:
   name=row['receipt'];d=self.data(name);c=d.get('result',d.get('counts',d))
   for key in ['tests','failures','errors','skipped']:self.check(name+':'+key,c.get(key)==row[key])
   passed=d.get('passed',d.get('status')=='passed');self.check(name+':status',passed is row['passed'])
   junit=(self.root/name).parent/'junit.xml'
   if junit.exists():
    xml=ET.parse(junit).getroot();suites=list(xml.iter('testsuite'))
    for key in ['tests','failures','errors','skipped']:
     self.check(name+':junit:'+key,sum(int(x.attrib.get(key,0)) for x in suites)==row[key])
   else:
    log=(self.root/name).parent/'tests.log';text=log.read_text()
    self.check(name+':logged test count',f"Ran {row['tests']} tests" in text)
    self.check(name+':logged outcome',('\nOK\n' in text) if row['passed'] else 'FAILED (' in text)
  failures={x['receipt'] for x in s['preserved_failures']}
  self.check('all specified earlier failures included',failures=={'candidate/tests/unit01/result.json','controls/sequence/tests01/result.json','reviews/cold-controls-review01.json'})
  for name,approved,count in [('candidate-review01.json',True,1014),('controls-review01.json',True,104),('cold-controls-review01.json',False,104),('cold-controls-review02.json',True,105),('sequence-code-review01.json',True,18)]:
   d=self.data('reviews/'+name);checks=d['checks']
   self.check('review approval:'+name,d['approved'] is approved)
   self.check('review check count:'+name,d['check_count']==count==len(checks))
   self.check('review checks:'+name,all(x is True for x in checks.values()) if approved else any(x is False for x in checks.values()))
   if 'launch_authority' in d:self.check('review limited authority:'+name,d['launch_authority'] is False)
  self.check('source review attribution',self.data('reviews/candidate-review01.json')['candidate_source_snapshot_sha256']==s['source_snapshot_sha256'])
  d=self.data('reviews/cold-controls-review02.json');self.check('reviewer-only correction explained',d['audit_correction']['preserved_attempt']=='cold-controls-review01.json' and 'reviewer' in d['audit_correction']['cause'].lower())
  for area in ['correctness','cold']:
   d=self.data('controls/'+area+'/controls-manifest01.json')
   for row in d['files']:
    p=self.root/'controls'/area/'source'/Path(row['path']).name
    self.check('control source:'+area+'/'+p.name,self.sha(p)==row['sha256'])
  final=self.data('controls/sequence/tests02/result.json');first=self.data('controls/sequence/tests01/result.json')
  self.check('final sequence driver pinned',self.sha(self.root/'controls/sequence/sequence.py')==final['driver_sha256']=='f346321a5bbdd9fdc38f65db5f5eb56d25a934cbf4613cff40c9a2d82423b7f5')
  self.check('failed sequence driver preserved',self.sha(self.root/'controls/sequence/tests01/sequence.py')==first['driver_sha256'])
  self.check('source test failures cannot imply pass',first['status']=='failed' and first['native_runs']==0 and final['passed'] is True and final['native_runs']==0)
  proposal=self.data('reviews/proposal-audit01.json');diag=self.data('diagnosis/reference-domain-analysis02.json');replay=self.data('diagnosis/native-reference-probe01/replay-result.json');supervisor=self.data('diagnosis/native-reference-probe01/supervisor.json')
  self.check('proposal independently approved',proposal['approved'] is True)
  self.check('saved damped proposal matches independent solution',proposal['trial_density_max_discrepancy']<2e-12)
  self.check('measured replay nonelliptic domain',diag['first_invalid_domain_update']['a']<0 and diag['first_invalid_domain_eccentricity']>1)
  self.check('measured replay six nonfinite fitted elements',all(diag['first_nonfinite_elements_update'][x] is None for x in ['a','h','k','p','q','l0']))
  self.check('exact terminal guard',diag['terminal_error']['guard_error']=='Nonfinite equinoctial reference input')
  self.check('replay explicitly separate from fit',replay['returncode']==0 and 'no force propagation or fit' in replay['scope'])
  self.check('replay supervised and clean',supervisor['status']=='complete' and supervisor['cleanup']['verified'] is True and supervisor['cleanup']['empty_tree_certificate']=='kernel_ECHILD')
  rr=self.data('reviews/reference-replay-review01.json');self.check('independent replay review approved',rr['approved'] is True and all(x is True for x in rr['checks'].values()))
  # Verify only original path+hash references whose content is actually included.
  def pins(value,where):
   if isinstance(value,dict):
    if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
     key=(value['path'],value['sha256'])
     if key in refs:
      p=self.root/refs[key];self.check('included pin:'+where+':'+refs[key],self.sha(p)==value['sha256'] and ('bytes' not in value or p.stat().st_size==value['bytes']))
    for x in value.values():pins(x,where)
   elif isinstance(value,list):
    for x in value:pins(x,where)
  for row in rows:
   if row['path'].endswith('.json') and row['path']!='external-pins.json':pins(self.data(row['path']),row['path'])
  ext=self.data('external-pins.json');self.check('external artifacts not claimed verified',all(x['portable_verified'] is False for x in ext['files']))
  class Links(HTMLParser):
   def __init__(self):super().__init__();self.links=[]
   def handle_starttag(self,tag,attrs):
    for key,value in attrs:
     if key in ['href','src']:self.links.append(value)
  parser=Links();parser.feed((self.root/'index.html').read_text())
  for link in parser.links:
   u=urlsplit(link)
   if not u.scheme and not u.netloc:
    p=Path(unquote(u.path));self.check('report link:'+link,not p.is_absolute() and '..' not in p.parts and (self.root/p).is_file())
  self.check('report states pending and no authority','All new native correctness checks and both cold full fits remain pending' in (self.root/'index.html').read_text())
  return {'schema':'candidate06-proposal-packet-verification-v1','passed':all(x['passed'] for x in self.checks),'checks':len(self.checks),'failed_checks':[x for x in self.checks if not x['passed']],'manifest_sha256':self.sha(self.root/'manifest.json'),'verify_originals':self.originals,'file_count_including_manifest':len(rows)+1,'external_artifacts_verified':False,'native_runs':0,'remote_mutations':0,'scope':'Packet identity, bounded source/patch/receipt consistency and explicit limitations; not a native correctness run, full-fit audit, launch or release approval.'}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--packet',type=Path,default=Path(__file__).resolve().parent);parser.add_argument('--verify-originals',action='store_true');a=parser.parse_args()
 try: result=Verification(a.packet.resolve(),a.verify_originals).run()
 except Exception as exc:result={'passed':False,'error':type(exc).__name__+': '+str(exc),'native_runs':0,'remote_mutations':0}
 print(json.dumps(result,indent=2));return 0 if result.get('passed') is True else 1
if __name__=='__main__':sys.exit(main())
